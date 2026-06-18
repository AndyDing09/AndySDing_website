"""The deterministic risk engine — the authority (Sections 3.1, 3.2, 3.3).

This module is pure: facts in, verdict out, no I/O, no randomness, no clock of its
own. The LLM reasoning layer *proposes*; this code *disposes*. Any proposal that
violates a hard gate is rejected with a logged reason, and there is no parameter
anywhere that lets the model widen a stop, skip the 2:1 check, exceed a size cap,
or trade through a halt. If the code and the model disagree, the code wins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from .config import Config
from .logging_setup import get_logger
from .models import GateResult, Grade, RiskDecision, SessionWindow, Side, TradeProposal

log = get_logger("risk")


@dataclass
class RiskContext:
    """Runtime facts the engine needs. Everything here is a measured value."""
    now: datetime
    in_allowed_session: bool = False
    session_window: SessionWindow = SessionWindow.CLOSED

    day_pnl: float = 0.0
    consecutive_losses: int = 0
    open_positions: int = 0
    trades_today: int = 0

    account_equity: float = 0.0
    buying_power: float = 0.0

    spread: float = 0.0
    avg_dollar_volume: float = 0.0
    is_halted: bool = False

    # discipline / cooldown
    last_loss_ts: Optional[datetime] = None
    symbol_last_trade_ts: Optional[datetime] = None   # last time THIS symbol was traded
    session_halted: bool = False                       # kill switch / daily-loss halt fired

    # regulatory
    account_profile: str = "cash_under_25k"
    day_trade_dates: list[str] = field(default_factory=list)   # ISO dates of day trades
    shorting_enabled: bool = False
    ssr_active: bool = False
    ssr_uptick_ok: bool = False
    borrow_available: bool = True
    on_threshold_list: bool = False


def _business_days_back(today: date, n: int) -> date:
    """The date ``n`` business days before ``today`` (weekends skipped; holidays
    are not modelled — an honest approximation, flagged in the journal)."""
    d = today
    steps = 0
    while steps < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:  # Mon–Fri
            steps += 1
    return d


def count_day_trades_in_window(dates_iso: list[str], today: date, business_days: int = 5) -> int:
    """How many day trades fall inside the rolling N-business-day PDT window
    (inclusive of today and the prior N-1 business days)."""
    start = _business_days_back(today, business_days - 1)
    count = 0
    for s in dates_iso:
        try:
            d = date.fromisoformat(s[:10])
        except (ValueError, TypeError):
            continue
        if start <= d <= today:
            count += 1
    return count


class RiskEngine:
    """Evaluates a fully-priced :class:`TradeProposal` against a :class:`RiskContext`."""

    def __init__(self, config: Config):
        self.cfg = config
        self.r = config.risk

    def evaluate(self, p: TradeProposal, ctx: RiskContext) -> RiskDecision:
        gates: list[GateResult] = []

        def gate(name, passed, value=None, threshold=None, detail=""):
            gates.append(GateResult(name, bool(passed), value, threshold, detail))

        # ── Session-level halts (kill switch / daily-loss halt) come first ──
        gate(
            "session_not_halted",
            not ctx.session_halted,
            ctx.session_halted,
            False,
            "session is halted for the day (kill switch or daily-loss cap)"
            if ctx.session_halted else "session active",
        )

        # ── §3.3 reward:risk — the headline hard gate ──
        gate(
            "reward_risk>=min",
            p.reward_risk >= self.r.min_reward_risk - 1e-9,
            round(p.reward_risk, 3),
            self.r.min_reward_risk,
            f"R:R {p.reward_risk:.2f} < {self.r.min_reward_risk:.2f}"
            if p.reward_risk < self.r.min_reward_risk else "R:R clears 2:1 floor",
        )

        # ── §3.3 sizing caps ──
        gate(
            "risk_per_trade<=max",
            p.risk_dollars <= self.r.max_risk_per_trade + 1e-6,
            round(p.risk_dollars, 2),
            self.r.max_risk_per_trade,
            f"${p.risk_dollars:.2f} risked > ${self.r.max_risk_per_trade:.2f} cap"
            if p.risk_dollars > self.r.max_risk_per_trade else "within per-trade risk cap",
        )
        gate(
            "position_notional<=max",
            p.position_notional <= self.r.max_position_notional + 1e-6,
            round(p.position_notional, 2),
            self.r.max_position_notional,
        )
        gate(
            "position_pct<=max",
            p.position_pct <= self.r.max_pct_account_per_trade + 1e-9,
            round(p.position_pct, 4),
            self.r.max_pct_account_per_trade,
        )

        # ── §3.3 day-level discipline ──
        gate(
            "day_pnl>-max_daily_loss",
            ctx.day_pnl > -self.r.max_daily_loss,
            round(ctx.day_pnl, 2),
            -self.r.max_daily_loss,
            "daily loss cap hit — halt the day"
            if ctx.day_pnl <= -self.r.max_daily_loss else "daily loss budget remains",
        )
        gate(
            "consecutive_losses<halt",
            ctx.consecutive_losses < self.r.consecutive_loss_halt,
            ctx.consecutive_losses,
            self.r.consecutive_loss_halt,
            f"{ctx.consecutive_losses} consecutive losses — halt the day"
            if ctx.consecutive_losses >= self.r.consecutive_loss_halt else "loss streak ok",
        )
        gate(
            "open_positions<max",
            ctx.open_positions < self.r.max_concurrent_positions,
            ctx.open_positions,
            self.r.max_concurrent_positions,
        )
        gate(
            "trades_today<max",
            ctx.trades_today < self.r.max_trades_per_day,
            ctx.trades_today,
            self.r.max_trades_per_day,
        )

        # ── §3.3 liquidity / spread ──
        gate(
            "spread<=max",
            ctx.spread <= self.r.max_spread + 1e-9,
            round(ctx.spread, 4),
            self.r.max_spread,
            f"spread ${ctx.spread:.3f} > ${self.r.max_spread:.3f} — too expensive to exit"
            if ctx.spread > self.r.max_spread else "spread acceptable",
        )
        gate(
            "avg_dollar_volume>=min",
            ctx.avg_dollar_volume >= self.cfg.selection.min_avg_dollar_volume,
            round(ctx.avg_dollar_volume, 0),
            self.cfg.selection.min_avg_dollar_volume,
            "illiquid — could get stuck",
        )

        # ── §3.3 session + halt status ──
        gate("in_allowed_session", ctx.in_allowed_session, ctx.session_window.value, True)
        gate(
            "not_halted",
            not ctx.is_halted,
            ctx.is_halted,
            False,
            "symbol is in an LULD halt — never send orders into a halt" if ctx.is_halted else "",
        )

        # ── §3.1 discipline: cooldown after a loss + same-ticker block ──
        if ctx.last_loss_ts is not None:
            elapsed_min = (ctx.now - ctx.last_loss_ts).total_seconds() / 60.0
            gate(
                "loss_cooldown_elapsed",
                elapsed_min >= self.r.loss_cooldown_minutes,
                round(elapsed_min, 1),
                self.r.loss_cooldown_minutes,
                "cooling down after a loss (no revenge trading)"
                if elapsed_min < self.r.loss_cooldown_minutes else "",
            )
            if ctx.symbol_last_trade_ts is not None:
                sym_elapsed = (ctx.now - ctx.symbol_last_trade_ts).total_seconds() / 60.0
                gate(
                    "same_ticker_cooldown",
                    sym_elapsed >= self.r.loss_cooldown_minutes,
                    round(sym_elapsed, 1),
                    self.r.loss_cooldown_minutes,
                    "blocked from re-entering same ticker during cooldown"
                    if sym_elapsed < self.r.loss_cooldown_minutes else "",
                )

        # ── §3.1 grade: only A may use full size; C and below are rejected ──
        gate(
            "setup_grade_tradeable",
            p.grade in (Grade.A, Grade.B),
            p.grade.value,
            "A or B",
            f"grade {p.grade.value} is not tradeable" if p.grade not in (Grade.A, Grade.B) else "",
        )
        # midday window: optionally A+ only (§1). Off by default — without a verified
        # float feed grade A is unreachable, which would silently lock out ALL midday
        # trading. B setups are already auto-sized-down for midday caution.
        if ctx.session_window == SessionWindow.MIDDAY and self.r.midday_requires_a:
            gate(
                "midday_A_only",
                p.grade == Grade.A,
                p.grade.value,
                "A",
                "midday: only A+ setups, smaller size" if p.grade != Grade.A else "",
            )

        # ── §3.2 PDT awareness ──
        if self.cfg.account_profile == "margin_under_25k":
            rolling = count_day_trades_in_window(ctx.day_trade_dates, ctx.now.date())
            gate(
                "pdt_day_trades<3",
                rolling < 3,
                rolling,
                3,
                "would be a 4th day trade in 5 business days (PDT) on a <$25k margin account"
                if rolling >= 3 else "",
            )

        # ── §3.2 short-side logistics (dormant unless shorting enabled) ──
        if p.side == Side.SHORT:
            gate("shorting_enabled", ctx.shorting_enabled, ctx.shorting_enabled, True,
                 "shorting is disabled in config")
            gate("borrow_available", ctx.borrow_available, ctx.borrow_available, True,
                 "no shares to borrow (hard-to-borrow)")
            gate("not_threshold_list", not ctx.on_threshold_list, ctx.on_threshold_list, False,
                 "Reg SHO threshold-list name — skip entirely")
            if ctx.ssr_active:
                gate("ssr_uptick_ok", ctx.ssr_uptick_ok, ctx.ssr_active, True,
                     "SSR active (down >10%): shorts only on an uptick")

        # ── §3.3 order-type discipline (markets are forbidden in code) ──
        # Entry/stop/target must be real prices > 0 for a long; the executor uses
        # limit/stop orders only. We assert the proposal is internally consistent.
        if p.side == Side.LONG:
            consistent = (p.entry > 0 and 0 < p.stop < p.entry < p.target and p.shares > 0)
            gate("proposal_consistent", consistent, None, None,
                 "entry/stop/target/shares are not a consistent long setup"
                 if not consistent else "")

        approved = all(g.passed for g in gates)
        reasons = [f"{g.name}: {g.detail or 'failed'}" for g in gates if not g.passed]
        if not approved:
            log.info("RISK REJECT %s: %s", p.symbol, "; ".join(reasons))
        return RiskDecision(approved=approved, gates=gates, reasons=reasons)
