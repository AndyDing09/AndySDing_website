"""Phase 3b (§9.3): PROPERTY-BASED proof that no order can violate the rules.

Hypothesis generates thousands of arbitrary signals, equities, scores, clock
times and breaker states; the invariant is that anything `run_gates` marks
tradeable satisfies every §2.3 rule. Garbage input must be rejected, never
resized into legality it doesn't have.
"""
from datetime import datetime, timedelta, timezone

from hypothesis import given, settings, strategies as st

from src.config import Config
from src.models import Regime, Signal, SignalStatus, SetupName, TradeRecord
from src.risk.circuit_breakers import CircuitBreakers
from src.risk.pipeline import run_gates
from src.risk.rr_gate import rr_gate
from src.risk.sizing import daily_risk_usd, size_signal

CFG = Config()
SESSION_OPEN = datetime(2026, 7, 6, 13, 30, tzinfo=timezone.utc)   # 09:30 ET

prices = st.floats(min_value=0.01, max_value=500, allow_nan=False, allow_infinity=False)


def make_signal(entry, stop, target, spread=0.001, score=90.0):
    s = Signal(ts=SESSION_OPEN, symbol="ABCD", setup=SetupName.BULL_FLAG,
               entry=entry, stop=stop, target=target,
               spread_pct_at_signal=spread, score=score)
    return s


def closed_trade(r: float) -> TradeRecord:
    return TradeRecord(
        signal_ts=SESSION_OPEN, closed_at=SESSION_OPEN + timedelta(minutes=5),
        symbol="ABCD", setup=SetupName.BULL_FLAG, entry_intended=5.0, entry_fill=5.0,
        exit_fill=5.0 + r * 0.2, stop=4.8, target=5.6, qty=100, realized_r=r,
        pnl_usd=r * 20.0, mae=0.0, mfe=0.0, hold_seconds=300.0, exit_reason="test")


# ── the 2:1 gate ──
@given(entry=prices, stop=prices, target=prices)
@settings(max_examples=500)
def test_rr_gate_never_passes_sub_2to1(entry, stop, target):
    sig = make_signal(entry, stop, target)
    passed = rr_gate(sig, CFG.risk.min_reward_risk)
    if passed:
        assert entry > stop
        assert (target - entry) >= CFG.risk.min_reward_risk * (entry - stop) - 1e-9
    else:
        assert sig.status == SignalStatus.SKIPPED
        assert sig.status_reason == "insufficient_rr"


# ── sizing ──
@given(entry=st.floats(2.0, 20.0), risk_ps=st.floats(0.001, 5.0),
       equity=st.floats(100, 100_000), spread=st.floats(0, 0.05))
@settings(max_examples=500)
def test_sizing_never_exceeds_budget_notional_or_spread(entry, risk_ps, equity, spread):
    stop = entry - risk_ps
    sig = make_signal(entry, stop, entry + 3 * risk_ps, spread=spread)
    d = size_signal(sig, CFG.risk, equity)
    if d.ok:
        assert d.shares >= 1
        assert spread <= CFG.risk.max_spread_pct
        assert d.risk_usd <= daily_risk_usd(CFG.risk, equity) + 1e-6
        assert d.notional <= CFG.risk.max_position_pct * equity + 1e-6
    else:
        assert sig.status == SignalStatus.REJECTED


# ── the full pipeline ──
@given(entry=st.floats(0.5, 50), stop=st.floats(0.01, 50), target=st.floats(0.5, 100),
       equity=st.floats(500, 50_000), score=st.floats(0, 100),
       minutes_after_open=st.integers(0, 390),
       prior_r=st.lists(st.floats(-1.5, 3.0), max_size=6),
       spread=st.floats(0, 0.03),
       regime=st.sampled_from(list(Regime)))
@settings(max_examples=400, deadline=None)
def test_no_tradeable_signal_ever_violates_any_rule(entry, stop, target, equity, score,
                                                    minutes_after_open, prior_r,
                                                    spread, regime):
    breakers = CircuitBreakers(CFG.risk)
    for r in prior_r:
        breakers.on_trade_closed(closed_trade(r))
    now = SESSION_OPEN + timedelta(minutes=minutes_after_open)
    sig = make_signal(entry, stop, target, spread=spread, score=score)
    out = run_gates(sig, CFG, breakers, equity, now, regime=regime)

    if not out.tradeable:
        assert sig.shares == 0 or sig.status in (SignalStatus.SKIPPED, SignalStatus.REJECTED)
        return

    # Tradeable ⇒ every rule holds simultaneously:
    assert entry > stop, "long structure"
    assert (target - entry) >= CFG.risk.min_reward_risk * (entry - stop) - 1e-9, "2:1 gate"
    assert spread <= CFG.risk.max_spread_pct, "spread gate"
    assert out.sizing.shares >= 1
    assert out.sizing.risk_usd <= daily_risk_usd(CFG.risk, equity) + 1e-6, "risk budget"
    assert out.sizing.notional <= CFG.risk.max_position_pct * equity + 1e-6, "notional cap"
    allowed, _ = breakers.entries_allowed(now)
    assert allowed, "breakers"
    # 11:30 ET cutoff == 120 minutes after the open
    assert minutes_after_open < 120, "entry-cutoff clock"
    # score gate incl. chop bump
    need = CFG.score.skip_below + (CFG.regime.chop_score_bump if regime == Regime.CHOP else 0)
    assert score >= need, "score gate"
    if score < CFG.score.full_size_at:
        assert out.half_size, "60-79 scores must be half size"


# ── breakers, exhaustively on the edges ──
def test_daily_loss_breaker_trips_at_minus_3r():
    b = CircuitBreakers(CFG.risk)
    for _ in range(3):
        b.on_trade_closed(closed_trade(-1.0))
    ok, reason = b.entries_allowed(SESSION_OPEN + timedelta(minutes=5))
    assert not ok and "breaker" in reason


def test_three_consecutive_losses_trip():
    b = CircuitBreakers(CFG.risk)
    for r in (-0.4, -0.4, -0.4):                 # only -1.2R total: the streak trips it
        b.on_trade_closed(closed_trade(r))
    ok, reason = b.entries_allowed(SESSION_OPEN + timedelta(minutes=5))
    assert not ok and "consecutive_losses" in reason


def test_winner_resets_the_streak():
    b = CircuitBreakers(CFG.risk)
    b.on_trade_closed(closed_trade(-0.5))
    b.on_trade_closed(closed_trade(-0.5))
    b.on_trade_closed(closed_trade(2.0))
    b.on_trade_closed(closed_trade(-0.5))
    ok, _ = b.entries_allowed(SESSION_OPEN + timedelta(minutes=5))
    assert ok


def test_entry_cutoff_at_1130():
    b = CircuitBreakers(CFG.risk)
    ok, _ = b.entries_allowed(SESSION_OPEN + timedelta(minutes=119))
    assert ok
    ok, reason = b.entries_allowed(SESSION_OPEN + timedelta(minutes=120))
    assert not ok and "past_entry_cutoff" in reason


def test_breaker_is_sticky_for_the_day_and_resets_next_session():
    b = CircuitBreakers(CFG.risk)
    for _ in range(3):
        b.on_trade_closed(closed_trade(-1.2))
    b.on_trade_closed(closed_trade(5.0))          # a big winner later must NOT re-arm
    ok, _ = b.entries_allowed(SESSION_OPEN + timedelta(minutes=5))
    assert not ok
    b.new_session()
    ok, _ = b.entries_allowed(SESSION_OPEN + timedelta(minutes=5))
    assert ok


def test_freeze_blocks_and_unfreeze_restores():
    b = CircuitBreakers(CFG.risk)
    b.freeze("reconciliation")
    ok, reason = b.entries_allowed(SESSION_OPEN)
    assert not ok and "frozen:reconciliation" in reason
    b.unfreeze()
    assert b.entries_allowed(SESSION_OPEN)[0]
