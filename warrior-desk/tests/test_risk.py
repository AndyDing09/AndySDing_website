"""Acceptance: the risk engine rejects sub-2:1 R:R, oversize positions,
post-2-loss trading, and daily-loss-cap breaches — deterministically."""
from datetime import datetime, timedelta

import pytest

from warrior.config import Config
from warrior.models import Grade, SessionWindow, Side, TradeProposal
from warrior.risk import RiskContext, RiskEngine, count_day_trades_in_window

NOW = datetime(2026, 6, 16, 9, 45)  # a Tuesday, prime window


def good_proposal(**over) -> TradeProposal:
    p = TradeProposal(
        symbol="ABCD",
        side=Side.LONG,
        session_window=SessionWindow.PRIME,
        entry=5.00, stop=4.80, target=5.50,
        stop_distance=0.20, reward_risk=2.5,
        shares=500, risk_dollars=100.0,
        position_notional=2500.0, position_pct=0.10,
        grade=Grade.A,
    )
    for k, v in over.items():
        setattr(p, k, v)
    return p


def good_ctx(**over) -> RiskContext:
    ctx = RiskContext(
        now=NOW, in_allowed_session=True, session_window=SessionWindow.PRIME,
        day_pnl=0.0, consecutive_losses=0, open_positions=0, trades_today=0,
        account_equity=25_000, buying_power=25_000,
        spread=0.02, avg_dollar_volume=5_000_000,
        is_halted=False, session_halted=False,
        account_profile="cash_under_25k",
    )
    for k, v in over.items():
        setattr(ctx, k, v)
    return ctx


def engine(**cfg_over):
    cfg = Config(**{k: v for k, v in cfg_over.items() if k in ("account_profile", "shorting_enabled")})
    return RiskEngine(cfg)


def _fail_names(decision):
    return {g.name for g in decision.failed_gates}


def test_clean_setup_is_approved():
    d = engine().evaluate(good_proposal(), good_ctx())
    assert d.approved, d.reasons


def test_sub_2to1_rr_is_rejected():
    # reward 0.30 / risk 0.20 = 1.5
    d = engine().evaluate(good_proposal(target=5.30, reward_risk=1.5), good_ctx())
    assert not d.approved
    assert "reward_risk>=min" in _fail_names(d)


def test_exactly_2to1_passes():
    d = engine().evaluate(good_proposal(target=5.40, reward_risk=2.0), good_ctx())
    assert d.approved, d.reasons


def test_oversize_risk_rejected():
    d = engine().evaluate(good_proposal(risk_dollars=120.0), good_ctx())
    assert not d.approved
    assert "risk_per_trade<=max" in _fail_names(d)


def test_oversize_notional_rejected():
    d = engine().evaluate(good_proposal(position_notional=6000.0), good_ctx())
    assert "position_notional<=max" in _fail_names(d)


def test_oversize_pct_rejected():
    d = engine().evaluate(good_proposal(position_pct=0.50), good_ctx())
    assert "position_pct<=max" in _fail_names(d)


def test_daily_loss_cap_halts():
    d = engine().evaluate(good_proposal(), good_ctx(day_pnl=-300.0))
    assert not d.approved
    assert "day_pnl>-max_daily_loss" in _fail_names(d)


def test_two_consecutive_losses_halts():
    d = engine().evaluate(good_proposal(), good_ctx(consecutive_losses=2))
    assert not d.approved
    assert "consecutive_losses<halt" in _fail_names(d)


def test_max_concurrent_positions():
    d = engine().evaluate(good_proposal(), good_ctx(open_positions=1))
    assert "open_positions<max" in _fail_names(d)


def test_max_trades_per_day():
    d = engine().evaluate(good_proposal(), good_ctx(trades_today=5))
    assert "trades_today<max" in _fail_names(d)


def test_wide_spread_rejected():
    d = engine().evaluate(good_proposal(), good_ctx(spread=0.25))
    assert "spread<=max" in _fail_names(d)


def test_illiquid_rejected():
    d = engine().evaluate(good_proposal(), good_ctx(avg_dollar_volume=100_000))
    assert "avg_dollar_volume>=min" in _fail_names(d)


def test_out_of_session_rejected():
    d = engine().evaluate(good_proposal(), good_ctx(in_allowed_session=False,
                                                    session_window=SessionWindow.CLOSED))
    assert "in_allowed_session" in _fail_names(d)


def test_halt_blocks_orders():
    d = engine().evaluate(good_proposal(), good_ctx(is_halted=True))
    assert "not_halted" in _fail_names(d)


def test_session_halt_blocks():
    d = engine().evaluate(good_proposal(), good_ctx(session_halted=True))
    assert "session_not_halted" in _fail_names(d)


def test_loss_cooldown_blocks_reentry():
    ctx = good_ctx(last_loss_ts=NOW - timedelta(minutes=3))  # cooldown default 10
    d = engine().evaluate(good_proposal(), ctx)
    assert "loss_cooldown_elapsed" in _fail_names(d)


def test_same_ticker_cooldown_blocks():
    ctx = good_ctx(last_loss_ts=NOW - timedelta(minutes=3),
                   symbol_last_trade_ts=NOW - timedelta(minutes=1))
    d = engine().evaluate(good_proposal(), ctx)
    assert "same_ticker_cooldown" in _fail_names(d)


def test_cooldown_elapsed_ok():
    ctx = good_ctx(last_loss_ts=NOW - timedelta(minutes=15),
                   symbol_last_trade_ts=NOW - timedelta(minutes=15))
    d = engine().evaluate(good_proposal(), ctx)
    assert d.approved, d.reasons


def test_grade_c_rejected():
    d = engine().evaluate(good_proposal(grade=Grade.C), good_ctx())
    assert "setup_grade_tradeable" in _fail_names(d)


def test_midday_allows_b_by_default():
    # Default: midday is NOT A-only (free data can't reach A), so a B setup trades.
    ctx = good_ctx(session_window=SessionWindow.MIDDAY)
    d = engine().evaluate(good_proposal(grade=Grade.B, session_window=SessionWindow.MIDDAY), ctx)
    assert d.approved, d.reasons


def test_midday_a_only_when_enabled():
    eng = engine()
    eng.r.midday_requires_a = True   # opt in (e.g. with a verified float feed)
    ctx = good_ctx(session_window=SessionWindow.MIDDAY)
    d = eng.evaluate(good_proposal(grade=Grade.B, session_window=SessionWindow.MIDDAY), ctx)
    assert "midday_A_only" in _fail_names(d)


def test_midday_grade_a_ok():
    ctx = good_ctx(session_window=SessionWindow.MIDDAY)
    d = engine().evaluate(good_proposal(grade=Grade.A, session_window=SessionWindow.MIDDAY), ctx)
    assert d.approved, d.reasons


def test_pdt_blocks_fourth_day_trade_on_margin_under_25k():
    eng = engine(account_profile="margin_under_25k")
    # three day trades already in the rolling window
    dts = [NOW.date().isoformat()] * 3
    d = eng.evaluate(good_proposal(), good_ctx(day_trade_dates=dts))
    assert "pdt_day_trades<3" in _fail_names(d)


def test_pdt_does_not_apply_to_cash_account():
    eng = engine(account_profile="cash_under_25k")
    dts = [NOW.date().isoformat()] * 5
    d = eng.evaluate(good_proposal(), good_ctx(day_trade_dates=dts))
    assert d.approved, d.reasons


def test_short_blocked_when_disabled():
    p = good_proposal(side=Side.SHORT)
    d = engine().evaluate(p, good_ctx(shorting_enabled=False))
    assert "shorting_enabled" in _fail_names(d)


def test_inconsistent_long_rejected():
    # stop above entry — nonsense
    d = engine().evaluate(good_proposal(stop=5.20), good_ctx())
    assert "proposal_consistent" in _fail_names(d)


def test_pdt_window_counts_business_days_only():
    today = datetime(2026, 6, 16).date()  # Tuesday
    # last Friday is 3 calendar days back but within 5 business days
    friday = "2026-06-12"
    assert count_day_trades_in_window([friday], today, business_days=5) == 1
    # three weeks ago is outside the window
    assert count_day_trades_in_window(["2026-05-20"], today, business_days=5) == 0
