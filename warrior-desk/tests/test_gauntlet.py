"""M3 validation: a clean bull flag clears the gauntlet; junk is rejected."""
from datetime import datetime

from warrior.catalysts import classify_catalyst
from warrior.config import Config
from warrior.data import AccountInfo, StaticFloatSource, SyntheticProvider, UnknownFloatSource
from warrior.data.provider import FloatInfo
from warrior.gauntlet import Gauntlet
from warrior.models import Bar, Candidate, Grade, Quote, StepStatus
from warrior.state import State

NOW = datetime(2026, 6, 16, 9, 45)   # Tuesday, prime window


def _bar(o, h, l, c, v):
    return Bar(ts=NOW, open=o, high=h, low=l, close=c, volume=v)


def bull_flag_bars():
    return [
        _bar(2.90, 2.95, 2.88, 2.92, 40_000),
        _bar(2.92, 3.00, 2.90, 2.98, 45_000),
        _bar(3.00, 3.12, 2.98, 3.10, 50_000),
        _bar(3.10, 3.25, 3.08, 3.22, 60_000),
        _bar(3.22, 3.40, 3.20, 3.38, 70_000),
        _bar(3.38, 3.55, 3.36, 3.52, 80_000),
        _bar(3.52, 3.70, 3.50, 3.66, 90_000),
        _bar(3.66, 3.80, 3.64, 3.78, 100_000),   # pole top ~3.80
        _bar(3.78, 3.78, 3.69, 3.70, 30_000),     # pullback (red, low vol)
        _bar(3.70, 3.74, 3.65, 3.67, 25_000),     # pullback (red, low vol)
    ]


def daily_bars(n=200):
    out = []
    for i in range(n):
        c = 1.5 + i * 0.011
        out.append(_bar(c - 0.02, c + 0.05, c - 0.05, c, 2_000_000))
    return out


class DailyProvider(SyntheticProvider):
    """SyntheticProvider that returns daily bars for the 1Day timeframe."""
    def get_bars(self, symbol, timeframe, limit=200):
        if timeframe == "1Day":
            return daily_bars()[-limit:]
        return super().get_bars(symbol, timeframe, limit)


def make_provider(float_shares=8_000_000, verified=True, rvol_baseline=100_000,
                  material_news=True, halted=False):
    floats = {}
    if float_shares is not None:
        floats["ABCD"] = FloatInfo(float_shares, verified=verified, source="test")
    news = []
    if material_news:
        news = [classify_catalyst("ABCD announces positive Phase 3 trial results", "pr", NOW)]
    return DailyProvider(
        bars={"ABCD": bull_flag_bars()},
        quotes={"ABCD": Quote(bid=3.66, ask=3.68)},
        news={"ABCD": news},
        movers=[Candidate("ABCD", price=3.67, gap_pct=0.45, rvol=5.9)],
        floats=floats,
        halted={"ABCD"} if halted else set(),
        baselines={"ABCD": rvol_baseline},
    )


def account():
    return AccountInfo(equity=30_000, cash=30_000, buying_power=30_000, status="ACTIVE")


def run(provider, cfg=None):
    cfg = cfg or Config()
    g = Gauntlet(cfg, provider)
    st = State(path="/tmp/warrior_test_state.json")
    return g.evaluate_symbol("ABCD", account(), st, NOW, short_circuit=False)


def step(p, n):
    return next(s for s in p.steps if s.number == n)


def test_clean_bull_flag_is_approved_grade_a():
    p = run(make_provider())
    assert step(p, 6).status == StepStatus.PASS          # pattern
    assert step(p, 9).status == StepStatus.PASS          # R:R
    assert p.reward_risk >= 2.0
    assert p.shares > 0
    assert p.decision.approved, p.decision.reasons
    assert p.grade == Grade.A                              # verified float + material catalyst


def test_pattern_metrics_populated():
    p = run(make_provider())
    assert p.entry > p.stop
    assert p.target > p.entry
    assert p.metrics["pattern"] in ("bull_flag", "flat_top")
    assert p.metrics["rvol"] >= 2.0


def test_unverified_float_caps_grade_at_b():
    p = run(make_provider(float_shares=None))   # no float source entry -> unknown
    assert p.decision.approved                  # still tradeable
    assert p.grade == Grade.B                    # but capped at B


def test_low_rvol_is_rejected():
    # baseline so high that today's volume gives RVOL < 2
    p = run(make_provider(rvol_baseline=5_000_000))
    assert step(p, 3).status == StepStatus.FAIL
    assert not p.decision.approved


def test_huge_float_is_rejected():
    p = run(make_provider(float_shares=500_000_000))
    assert step(p, 3).status == StepStatus.FAIL
    assert not p.decision.approved


def test_halted_symbol_is_rejected():
    p = run(make_provider(halted=True))
    # pattern still reads, but the risk sweep blocks on the halt
    assert not p.decision.approved
    assert any("halt" in r.lower() for r in p.decision.reasons)


def test_flat_choppy_series_has_no_pattern():
    flat = [_bar(3.0, 3.02, 2.98, 3.0, 10_000) for _ in range(12)]
    p = DailyProvider(bars={"ABCD": flat}, quotes={"ABCD": Quote(3.0, 3.01)},
                      floats={"ABCD": FloatInfo(8_000_000, True, "test")},
                      baselines={"ABCD": 1000})
    res = run(p)
    assert step(res, 6).status == StepStatus.FAIL
    assert not res.decision.approved


def test_no_news_technical_only_caps_at_b():
    p = run(make_provider(material_news=False))
    if p.decision.approved:
        assert p.grade == Grade.B
