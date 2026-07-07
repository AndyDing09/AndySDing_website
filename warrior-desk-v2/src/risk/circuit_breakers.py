"""Daily circuit breakers (§2.3) — all halt NEW ENTRIES for the rest of the session.

- realized day P&L ≤ −N·R (default 3R)
- N consecutive losing trades (default 3)
- clock past no_new_entries_after (default 11:30 ET) — best liquidity and
  follow-through live in the first two hours; forcing trades in the midday chop
  is how good mornings die
- manual/automatic freezes (kill switch, reconciliation mismatch) share the
  same mechanism so there is exactly one place that answers "may we enter?"

Open positions keep managing/exiting when breakers trip; only entries stop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..config import RiskCfg
from ..data.clock import ny_time
from ..models import Signal, SignalStatus, TradeRecord


@dataclass
class BreakerState:
    day_r: float = 0.0
    consecutive_losses: int = 0
    tripped: str = ""              # first breaker that tripped (sticky for the day)
    frozen_by: str = ""            # kill_switch / reconciliation — manual freezes


class CircuitBreakers:
    def __init__(self, cfg: RiskCfg):
        self.cfg = cfg
        self.state = BreakerState()

    # ── inputs ──
    def on_trade_closed(self, trade: TradeRecord) -> None:
        self.state.day_r += trade.realized_r
        if trade.pnl_usd < 0:
            self.state.consecutive_losses += 1
        elif trade.pnl_usd > 0:
            self.state.consecutive_losses = 0
        self._evaluate()

    def freeze(self, reason: str) -> None:
        self.state.frozen_by = reason

    def unfreeze(self) -> None:
        self.state.frozen_by = ""

    def new_session(self) -> None:
        self.state = BreakerState()

    # ── verdicts ──
    def _evaluate(self) -> None:
        if self.state.tripped:
            return
        if self.state.day_r <= -self.cfg.daily_max_loss_r:
            self.state.tripped = f"daily_max_loss:{self.state.day_r:.2f}R"
        elif self.state.consecutive_losses >= self.cfg.max_consecutive_losses:
            self.state.tripped = f"consecutive_losses:{self.state.consecutive_losses}"

    def entries_allowed(self, now: datetime) -> tuple[bool, str]:
        if self.state.frozen_by:
            return False, f"frozen:{self.state.frozen_by}"
        if self.state.tripped:
            return False, f"breaker:{self.state.tripped}"
        if ny_time(now) >= self.cfg.no_new_entries_after:
            return False, "breaker:past_entry_cutoff"
        return True, ""

    def gate(self, signal: Signal, now: datetime) -> bool:
        """Apply to a signal about to become an order. Mutates on rejection."""
        ok, reason = self.entries_allowed(now)
        if not ok:
            signal.status = SignalStatus.REJECTED
            signal.status_reason = reason
        return ok
