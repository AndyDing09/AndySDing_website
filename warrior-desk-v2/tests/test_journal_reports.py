"""Phase 5: expectancy engine, journal math, EOD report + validation, alerts."""
from datetime import datetime, timedelta, timezone

import pytest

from src.alerts import AlertRouter
from src.checkpoints.stats_weekly import two_proportion_test, weekly_stats
from src.checkpoints.validate_report import validate_trades
from src.config import Config
from src.data.store import Store
from src.execution.broker import SimBroker
from src.journal.expectancy import (RollingMonitor, breakeven_win_rate, compute,
                                    cut_by, time_bucket, wilson_interval)
from src.journal.journal import Journal, simulate_skipped
from src.models import (Bar, Position, Quote, SetupName, Signal, SignalStatus,
                        TradeRecord)
from src.reporting.eod_report import write_eod_report
from src.reporting.live_export import (export_expectancy, export_positions,
                                       export_signals, export_watchlist)

CFG = Config()
NOW = datetime(2026, 7, 6, 14, 0, tzinfo=timezone.utc)


def trade(pnl, r, **kw):
    d = dict(signal_ts=NOW, closed_at=NOW + timedelta(minutes=10), symbol="ABCD",
             setup=SetupName.BULL_FLAG, entry_intended=5.0, entry_fill=5.0,
             exit_fill=5.0 + r * 0.2, stop=4.8, target=5.6, qty=int(abs(pnl / (r * 0.2)) or 1)
             if r else 100, realized_r=r, pnl_usd=pnl, mae=-0.05, mfe=0.3,
             hold_seconds=600, exit_reason="target" if pnl > 0 else "stop")
    d.update(kw)
    return TradeRecord(**d)


# ── expectancy math (§6) ──
def test_expectancy_identity():
    trades = [trade(40, 2.0), trade(40, 2.0), trade(-20, -1.0)]
    s = compute(trades, min_sample_n=3)
    # (win% x avg win) − (loss% x avg loss) == mean pnl, exactly
    assert s.expectancy_usd == pytest.approx(
        s.win_rate * s.avg_win_usd - (1 - s.win_rate) * s.avg_loss_usd)
    assert s.expectancy_usd == pytest.approx(60 / 3)


def test_breakeven_case_33_4_pct():
    """§10: the 33.4% breakeven case. With 2R wins and 1R losses the breakeven
    win rate is exactly 1/3; at win rate 1/3 expectancy is zero; a hair above
    is positive, a hair below (33% -> the '33.4% after costs' rule) is negative."""
    assert breakeven_win_rate(2.0, 1.0) == pytest.approx(1 / 3)
    # exactly at breakeven: 1 win (+2R=$100), 2 losses (-1R=-$50 each)
    flat = [trade(100, 2.0), trade(-50, -1.0), trade(-50, -1.0)]
    assert compute(flat, 3).expectancy_usd == pytest.approx(0.0)
    # one extra win tips it positive; one extra loss tips it negative
    assert compute(flat + [trade(100, 2.0)], 3).expectancy_usd > 0
    assert compute(flat + [trade(-50, -1.0)], 3).expectancy_usd < 0


def test_wilson_interval_sane():
    lo, hi = wilson_interval(10, 20)
    assert 0.27 < lo < 0.5 < hi < 0.73          # known Wilson bounds for 10/20
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_insufficient_sample_flagged():
    s = compute([trade(40, 2.0)] * 5, min_sample_n=30)
    assert s.insufficient_sample and "do not conclude" in s.note


def test_rolling_monitor_red_banner_never_buried():
    m = RollingMonitor(window=20, min_sample_n=30)
    m.update([trade(-50, -1.0)] * 20)
    assert m.red and "UNPROFITABLE" in m.banner()
    m.update([trade(100, 2.0)] * 20)
    assert not m.red and m.banner() is None


def test_cut_by_and_time_bucket():
    trades = [trade(40, 2.0).model_dump(), trade(-20, -1.0, setup=SetupName.GAP_AND_GO).model_dump()]
    for t in trades:
        t["setup"] = t["setup"].value if hasattr(t["setup"], "value") else t["setup"]
    cuts = cut_by(trades, "setup", min_sample_n=1)
    assert set(cuts) == {"bull_flag", "gap_and_go"}
    assert time_bucket(NOW) == "10:00-10:30"    # 14:00 UTC = 10:00 ET


# ── journal round-trip R math ──
def test_journal_realized_r_uses_planned_risk():
    store = Store(":memory:")
    j = Journal(store)
    b = SimBroker(CFG)
    sig = Signal(ts=NOW, symbol="ABCD", setup=SetupName.BULL_FLAG, entry=5.0,
                 stop=4.8, target=5.5, shares=250)
    q = Quote(symbol="ABCD", ts=NOW, bid=4.99, ask=5.01, feed="test")
    pos = b.submit_bracket(sig, NOW, q)                       # fills 5.02
    exit_fill = b.exit_position(pos, "target", NOW + timedelta(minutes=8), q)
    tr = j.record_close(pos, b.fills[0], exit_fill, sig, "target",
                        NOW + timedelta(minutes=8))
    # R measured against PLANNED risk (5.00-4.80): (5.50-5.02)/0.20 = 2.4
    assert tr.realized_r == pytest.approx(2.4, abs=0.01)
    assert tr.pnl_usd == pytest.approx((5.50 - 5.02) * 250, abs=0.01)
    assert store.last_trades(1)[0]["symbol"] == "ABCD"


# ── skipped-signal simulation ──
def _bars_seq(prices):
    return [Bar(symbol="ABCD", ts=NOW + timedelta(minutes=i), open=p, high=p + 0.05,
                low=p - 0.05, close=p, volume=1000, feed="test")
            for i, p in enumerate(prices)]


def test_simulate_skipped_target_and_stop():
    row = {"symbol": "ABCD", "setup": "bull_flag", "status_reason": "insufficient_rr",
           "entry": 5.0, "stop": 4.8, "target": 5.4}
    win = simulate_skipped(row, _bars_seq([4.9, 5.0, 5.2, 5.4]))     # fills then target
    assert win.would_have == "target" and win.would_r == pytest.approx(2.0)
    loss = simulate_skipped(row, _bars_seq([4.9, 5.0, 4.79]))        # fills then stop
    assert loss.would_have == "stop" and loss.would_r == -1.0
    never = simulate_skipped(row, _bars_seq([4.5, 4.6]))             # never fills
    assert never.would_have == "open"


# ── EOD report + validation checkpoint ──
def _seeded_store():
    store = Store(":memory:")
    j = Journal(store)
    for i, (pnl, r) in enumerate([(40, 2.0), (-20, -1.0), (44, 2.2)]):
        t = trade(pnl, r, closed_at=NOW + timedelta(minutes=10 + i))
        store.write_trade(t)
    sig = Signal(ts=NOW, symbol="SKIP", setup=SetupName.VWAP_BREAKOUT, entry=9.0,
                 stop=8.9, target=9.1, status=SignalStatus.SKIPPED,
                 status_reason="insufficient_rr")
    store.write_signal(sig)
    return store


def test_eod_report_contains_required_sections(tmp_path):
    store = _seeded_store()
    m = RollingMonitor(window=20, min_sample_n=30)
    dest = write_eod_report(store, NOW - timedelta(hours=5), NOW + timedelta(hours=3),
                            m, skipped=[], carryover=["ABCD"], reports_dir=tmp_path)
    html = dest.read_text()
    for needle in ("Equity curve", "Today's trades", "Setup breakdown",
                   "skipped signals", "Data-quality incidents", "carry-over",
                   "not financial advice"):
        assert needle in html
    assert "ABCD" in html


def test_eod_report_shows_red_banner_when_unprofitable(tmp_path):
    store = Store(":memory:")
    for i in range(20):
        store.write_trade(trade(-25, -1.0, closed_at=NOW + timedelta(minutes=i)))
    m = RollingMonitor(window=20, min_sample_n=30)
    dest = write_eod_report(store, NOW - timedelta(hours=5), NOW + timedelta(hours=3),
                            m, skipped=[], carryover=[], reports_dir=tmp_path)
    assert "UNPROFITABLE" in dest.read_text()


def test_validate_report_passes_clean_and_catches_corruption():
    trades = [trade(120.0, 2.4, entry_fill=5.02, exit_fill=5.50, qty=250).model_dump()]
    ok = validate_trades(trades, claimed_day_pnl=120.0)
    assert ok.ok, ok.failures

    bad = dict(trades[0])
    bad["realized_r"] = 9.9                                  # corrupt the aggregate
    res = validate_trades([bad])
    assert not res.ok and "does not recompute" in res.failures[0]

    dup = validate_trades(trades + trades)                   # double-counted close
    assert not dup.ok and any("duplicate" in f for f in dup.failures)


def test_two_proportion_test_needs_sample_and_significance():
    r = two_proportion_test(20, 40, 10, 40)                  # 50% vs 25%, n=40 each
    assert r.significant_at_5pct
    small = two_proportion_test(4, 6, 1, 5)                  # tiny samples
    assert not small.significant_at_5pct
    assert "do not conclude" in small.conclusion


def test_weekly_stats_shape():
    store = _seeded_store()
    out = weekly_stats(store, min_sample_n=30)
    assert out["overall"]["n"] == 3
    assert "bull_flag" in out["per_setup"]
    assert "insufficient" in out["overall"]["note"]


# ── live export contract ──
def test_live_export_files_and_schema(tmp_path):
    from src.models import Candidate
    export_watchlist([Candidate(symbol="ABCD", last=5.0)], NOW, tmp_path)
    pos = Position(symbol="ABCD", qty=100, entry=5.0, stop=4.8, target=5.6,
                   opened_at=NOW, signal_ts=NOW, setup=SetupName.BULL_FLAG)
    export_positions([pos], {"ABCD": 5.4}, NOW, tmp_path)
    export_signals([Signal(ts=NOW, symbol="ABCD", setup=SetupName.BULL_FLAG,
                           entry=5, stop=4.8, target=5.6)], NOW, tmp_path)
    export_expectancy(compute([trade(40, 2.0)], 30), breaker_state="", red=False,
                      now=NOW, live_dir=tmp_path)
    import json
    for name in ("watchlist", "positions", "signals", "expectancy"):
        data = json.loads((tmp_path / f"{name}.json").read_text())
        assert data["schema"] == 1
    pos_data = json.loads((tmp_path / "positions.json").read_text())
    assert pos_data["rows"][0]["unrealized_r"] == pytest.approx(2.0)


# ── alert routing ──
def test_alert_router_distinct_prefixes_and_fault_isolation(capsys):
    seen = []
    def good(kind, msg): seen.append((kind, msg))
    def bad(kind, msg): raise RuntimeError("sink down")
    r = AlertRouter(sinks=[bad, good])
    r.send("HOD", "ABCD new high 5.55")
    r.send("BREAKER", "daily max loss")
    assert seen == [("HOD", "ABCD new high 5.55"), ("BREAKER", "daily max loss")]
