"""Phase 2: gapper criteria, HOD event scanner, regime, watchlist validation."""
from datetime import datetime, timedelta, timezone

from src.config import Config
from src.checkpoints.validate_watchlist import validate_watchlist
from src.data.corp_actions import CorpActionsGuard, SplitEvent
from src.data.floats import CrossValidatedFloat, StaticFloatProvider
from src.models import Bar, NewsItem, Regime, Tick
from src.scanners.gapper import (
    Snapshot, evaluate_snapshot, freeze_watchlist, rank, render_table,
    rvol_time_of_day, scan, write_watchlist_json,
)
from src.scanners.hod_momentum import HodScanner
from src.scanners.regime import classify_regime, required_score

NOW = datetime(2026, 7, 6, 12, 30, tzinfo=timezone.utc)   # 08:30 ET pre-market
CFG = Config()


def floats(**mapping):
    m = {k: float(v) for k, v in mapping.items()}
    return CrossValidatedFloat([StaticFloatProvider(m, "a"),
                                StaticFloatProvider(m, "b")], 0.25)


def snap(symbol="ABCD", last=5.5, prior=4.4, vol=2_000_000, baseline=250_000,
         exchange="NASDAQ", headline="FDA approval for lead drug", news_age_h=2.0,
         pm_high=5.8, pm_low=5.0):
    news = [NewsItem(symbol=symbol, ts=NOW - timedelta(hours=news_age_h),
                     headline=headline)] if headline else []
    return Snapshot(symbol=symbol, exchange=exchange, last=last, prior_close=prior,
                    premkt_vol=vol, premkt_high=pm_high, premkt_low=pm_low,
                    cum_vol_baseline=baseline, news=news)


# ── §2.1 five-point criteria ──
def test_qualifier_passes_all_five():
    c = evaluate_snapshot(snap(), CFG, floats(ABCD=8_000_000), CorpActionsGuard(), NOW)
    assert c is not None
    assert c.a_grade                      # verified float < 10M
    assert c.gap_pct > 0.10 and c.rvol >= 5.0


def test_price_band_rejects():
    assert evaluate_snapshot(snap(last=1.50, prior=1.20), CFG, floats(ABCD=8e6),
                             CorpActionsGuard(), NOW) is None
    assert evaluate_snapshot(snap(last=25.0, prior=20.0), CFG, floats(ABCD=8e6),
                             CorpActionsGuard(), NOW) is None


def test_low_rvol_rejects():
    assert evaluate_snapshot(snap(vol=500_000, baseline=250_000), CFG,
                             floats(ABCD=8e6), CorpActionsGuard(), NOW) is None


def test_big_float_rejects():
    assert evaluate_snapshot(snap(), CFG, floats(ABCD=50_000_000),
                             CorpActionsGuard(), NOW) is None


def test_small_gap_rejects():
    assert evaluate_snapshot(snap(last=4.6, prior=4.4), CFG, floats(ABCD=8e6),
                             CorpActionsGuard(), NOW) is None


def test_missing_catalyst_rejects_when_required():
    assert evaluate_snapshot(snap(headline=""), CFG, floats(ABCD=8e6),
                             CorpActionsGuard(), NOW) is None


def test_stale_catalyst_rejects():
    assert evaluate_snapshot(snap(news_age_h=30), CFG, floats(ABCD=8e6),
                             CorpActionsGuard(), NOW) is None


def test_offering_hard_excludes():
    s = snap(headline="Prices $40M registered direct offering")
    assert evaluate_snapshot(s, CFG, floats(ABCD=8e6), CorpActionsGuard(), NOW) is None


def test_otc_exchange_rejected():
    assert evaluate_snapshot(snap(exchange="OTC"), CFG, floats(ABCD=8e6),
                             CorpActionsGuard(), NOW) is None


def test_unverified_float_blocks_a_grade_but_not_listing():
    cv = CrossValidatedFloat([StaticFloatProvider({"ABCD": 5e6}, "a"),
                              StaticFloatProvider({"ABCD": 9.9e6}, "b")], 0.25)
    c = evaluate_snapshot(snap(), CFG, cv, CorpActionsGuard(), NOW)
    assert c is not None and c.float_unverified and not c.a_grade


def test_reverse_split_gap_is_neutralized():
    guard = CorpActionsGuard([SplitEvent("ABCD", NOW.date(), ratio=0.1)])
    # raw prior 0.50 makes 5.20 look like a +940% gap; the 1-for-10 adjustment
    # (prior -> 5.00) reveals a real gap of +4%, below the +10% floor.
    s = snap(last=5.2, prior=0.50)
    assert evaluate_snapshot(s, CFG, floats(ABCD=8e6), CorpActionsGuard(), NOW) is not None  # unguarded: absurd gap passes
    assert evaluate_snapshot(s, CFG, floats(ABCD=8e6), guard, NOW) is None                   # guarded: excluded


def test_rvol_time_of_day_math():
    assert rvol_time_of_day(2_000_000, 250_000) == 8.0
    assert rvol_time_of_day(100, 0) == 0.0


# ── ranking / freeze / outputs ──
def _cands():
    snaps = [snap(symbol="AAAA", last=6.6, prior=4.4, vol=5_000_000),      # +50%
             snap(symbol="BBBB", last=5.28, prior=4.4, vol=1_500_000),     # +20%
             snap(symbol="CCCC", last=4.95, prior=4.4, vol=1_400_000)]     # +12.5%
    f = floats(AAAA=8e6, BBBB=9e6, CCCC=15e6)
    return scan(snaps, CFG, f, CorpActionsGuard(), NOW)


def test_scan_sorts_by_gap_and_ranks_obviousness():
    cands = _cands()
    assert [c.symbol for c in cands] == ["AAAA", "BBBB", "CCCC"]
    assert cands[0].obviousness_rank == 1          # gap% x rvol leader = the obvious one


def test_freeze_prefers_a_grade_and_respects_bounds():
    cands = _cands()
    frozen = freeze_watchlist(cands, CFG)
    assert 3 <= len(frozen) <= 5 or len(frozen) == len([c for c in cands if c.a_grade])
    assert all(c.a_grade for c in frozen[:2])


def test_watchlist_json_written(tmp_path):
    p = write_watchlist_json(_cands(), NOW, tmp_path)
    assert p.exists() and p.name == "watchlist_2026-07-06.json"


def test_render_table_contains_rows():
    text = render_table(_cands())
    assert "AAAA" in text and "Top Gappers" in text


# ── HOD scanner ──
def _tick(sym, price, sec):
    return Tick(symbol=sym, ts=NOW + timedelta(seconds=sec), price=price, size=100,
                feed="test")


def test_hod_alerts_only_on_qualifying_new_highs():
    hs = HodScanner()
    hs.set_qualifying({"ABCD"})
    assert hs.on_tick(_tick("ABCD", 5.00, 0)) is None      # seed, no alert
    assert hs.on_tick(_tick("ABCD", 4.90, 1)) is None      # not a new high
    a = hs.on_tick(_tick("ABCD", 5.10, 2))
    assert a is not None and a.prev_hod == 5.00
    # non-qualifying symbol never alerts, even on a new high
    hs.on_tick(_tick("JUNK", 2.00, 3))
    assert hs.on_tick(_tick("JUNK", 2.50, 4)) is None


def test_hod_fast_mover_annotation():
    hs = HodScanner(realert_window_seconds=180)
    hs.set_qualifying({"ABCD"})
    hs.on_tick(_tick("ABCD", 5.00, 0))
    a1 = hs.on_tick(_tick("ABCD", 5.05, 10))
    a2 = hs.on_tick(_tick("ABCD", 5.10, 20))
    a3 = hs.on_tick(_tick("ABCD", 5.15, 30))
    assert (a1.fast_mover, a2.fast_mover, a3.fast_mover) == (False, False, True)
    assert a3.repeats_in_window == 3


def test_halt_suppresses_until_two_minutes_after_resume():
    hs = HodScanner(halt_quiet_minutes=2)
    hs.set_qualifying({"ABCD"})
    hs.on_tick(_tick("ABCD", 5.00, 0))
    hs.on_halt("ABCD", NOW + timedelta(seconds=5))
    assert hs.on_tick(_tick("ABCD", 5.50, 10)) is None          # halted
    hs.on_resume("ABCD", NOW + timedelta(seconds=60))
    assert hs.on_tick(_tick("ABCD", 6.00, 90)) is None          # inside quiet window
    a = hs.on_tick(_tick("ABCD", 6.50, 60 + 121))
    assert a is not None                                        # quiet window elapsed


# ── regime ──
def _spy_bars(closes, vol=1_000_000):
    return [Bar(symbol="SPY", ts=NOW + timedelta(minutes=5 * i), open=c, high=c + 0.2,
                low=c - 0.2, close=c, volume=vol, feed="test")
            for i, c in enumerate(closes)]


def test_regime_trending():
    closes = [500 + i * 0.5 for i in range(20)]     # steady climb above vwap+ema
    call = classify_regime(_spy_bars(closes))
    assert call.regime == Regime.TRENDING


def test_regime_chop_on_ema_whipsaw():
    closes = [500, 501, 500, 501, 500, 501, 500, 501, 500, 501, 500, 501]
    call = classify_regime(_spy_bars(closes))
    assert call.regime == Regime.CHOP


def test_chop_raises_required_score():
    assert required_score(60, Regime.CHOP, 10) == 70
    assert required_score(60, Regime.TRENDING, 10) == 60


# ── validation checkpoint ──
def test_validate_watchlist_passes_on_clean_rows():
    snaps = {s.symbol: s for s in
             [snap(symbol="AAAA", last=6.6, prior=4.4, vol=5_000_000)]}
    cands = scan(list(snaps.values()), CFG, floats(AAAA=8e6), CorpActionsGuard(), NOW)
    res = validate_watchlist(cands, snaps)
    assert res.ok, res.failures


def test_validate_watchlist_catches_corrupted_gap():
    snaps = {s.symbol: s for s in
             [snap(symbol="AAAA", last=6.6, prior=4.4, vol=5_000_000)]}
    cands = scan(list(snaps.values()), CFG, floats(AAAA=8e6), CorpActionsGuard(), NOW)
    cands[0].gap_pct = 0.99                       # corrupt the row
    res = validate_watchlist(cands, snaps)
    assert not res.ok
    assert "gap% mismatch" in res.failures[0]
    assert res.banner.startswith("WARNING")
