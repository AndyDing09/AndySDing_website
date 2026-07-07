"""The §5 checkpoint loop, end-to-end on a replayed session.

replay a captured day → journal populated → run every checkpoint job →
artifacts exist, are well-formed, and the validators pass on clean data.
This is the automation path; the installed .claude/skills are the interactive
path — both share the reports/ contract.
"""
from datetime import datetime, timedelta, timezone

from src.checkpoints import analyze_eod, explore_source, stats_weekly, validate_report
from src.config import Config
from src.data.store import Store
from src.engine import SessionEngine
from src.execution.broker import SimBroker
from src.models import Bar, Candidate, CatalystType, Regime
from src.risk.circuit_breakers import CircuitBreakers

CFG = Config()
T0 = datetime(2026, 7, 6, 13, 45, tzinfo=timezone.utc)     # 09:45 ET


def _cand():
    return Candidate(symbol="ABCD", gap_pct=0.25, last=5.45, premkt_vol=2_000_000,
                     rvol=8.0, float_shares=8e6, catalyst_headline="FDA approval",
                     catalyst_type=CatalystType.FDA_CLINICAL, obviousness_rank=1,
                     premkt_high=5.50, premkt_low=5.10, a_grade=True)


def _bar(o, h, l, c, v, i):
    return Bar(symbol="ABCD", ts=T0 + timedelta(minutes=i), open=o, high=h, low=l,
               close=c, volume=v, feed="test")


def _run_session(store: Store) -> SessionEngine:
    eng = SessionEngine(CFG, SimBroker(CFG), store, CircuitBreakers(CFG.risk),
                        {"ABCD": _cand()}, regime=Regime.TRENDING)
    for b in [_bar(5.40, 5.48, 5.30, 5.45, 100_000, 0),
              _bar(5.45, 5.60, 5.44, 5.58, 200_000, 1),     # entry
              _bar(5.60, 6.70, 5.50, 6.65, 300_000, 2)]:    # target
        eng.on_bar(b)
    return eng


def test_full_checkpoint_loop(tmp_path):
    store = Store(":memory:")
    eng = _run_session(store)
    assert eng.trades, "fixture must produce a closed trade"
    day_start, day_end = T0 - timedelta(hours=2), T0 + timedelta(hours=7)

    # Regression (found BY the explore-data checkpoint): the persisted signal row
    # must carry the FINAL status — a filled trade may never sit as 'proposed'.
    rows = store.signals_between(day_start, day_end)
    assert rows and rows[0]["status"] == "filled"

    # 1. explore-data on the captured bars (source-onboarding checkpoint)
    p = explore_source.run(store, "bars_1m", day_end, tmp_path)
    import json
    profile = json.loads(p.read_text())
    assert profile["rows"] == 3
    assert profile["columns"]["close"]["stats"]["min"] > 0
    assert profile["columns"]["symbol"]["top_values"][0][0] == "ABCD"
    assert not any(f.startswith("ALERT") for f in profile["quality_flags"])

    # 2. analyze (EOD) — what drove the day
    p = analyze_eod.run(store, day_start, day_end, day_end, tmp_path)
    analysis = json.loads(p.read_text())
    assert analysis["n_trades"] == 1
    assert analysis["day_pnl"] == eng.trades[0].pnl_usd
    assert "gap_and_go" in analysis["by_setup"]

    # 3. validate-data on the report (pre-delivery checkpoint)
    res = validate_report.run(store, day_start, day_end, tmp_path)
    assert res.ok, res.failures

    # 4. statistical-analysis (weekly)
    p = stats_weekly.run(store, day_end, tmp_path)
    stats = json.loads(p.read_text())
    assert stats["overall"]["n"] == 1
    assert stats["overall"]["insufficient_sample"] is True     # n=1 -> do not conclude

    # every checkpoint left a timestamped artifact in reports/
    names = sorted(f.name for f in tmp_path.iterdir())
    assert any(n.startswith("explore_bars_1m") for n in names)
    assert any(n.startswith("analyze_eod") for n in names)
    assert any(n.startswith("validate_report") for n in names)
    assert any(n.startswith("stats_weekly") for n in names)


def test_explore_flags_dirty_source(tmp_path):
    store = Store(":memory:")
    # a corrupt source: zero price and a duplicate (symbol, ts) key
    b = _bar(0.0, 0.0, 0.0, 0.0, 100, 0)
    store.write_bar(b)
    store.write_bar(b)
    profile = explore_source.profile_table(store, "bars_1m")
    flags = " | ".join(profile["quality_flags"])
    assert "zero values" in flags or "ALERT" in flags
    assert "duplicate (symbol, ts)" in flags
