"""Position management — the 3-tier exit logic (Sections 2.7 & 5).

Once filled, each position is monitored on its trading timeframe and we:

  1. Scale at the first target (~2R): sell half and move the stop to break-even —
     now the trade is "free".
  2. First red candle close: if we haven't scaled yet, the first red close is an
     exit. Once scaled, hold the rest as long as the break-even stop holds.
  3. Extension bar: a parabolic spike that instantly puts us up big — sell into it.

The protective stop is honoured at all times and is NEVER widened. ``decide`` is
pure (bar in, actions out) so the logic is fully testable; ``apply`` executes via
the broker and records the result in state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .config import Config
from .logging_setup import get_logger
from .models import Bar, ClosedTrade, ManageAction, Position
from .state import State

log = get_logger("pm")


class PositionManager:
    def __init__(self, cfg: Config, broker):
        self.cfg = cfg
        self.broker = broker

    def decide(self, pos: Position, bar: Bar, atr: Optional[float] = None) -> list[ManageAction]:
        r = self.cfg.risk
        entry = pos.avg_entry
        risk = pos.initial_risk if pos.initial_risk > 0 else max(entry - pos.stop, 0.01)
        scale_target = entry + r.first_target_r * risk
        ext_level = entry + r.extension_r * risk
        actions: list[ManageAction] = []

        # 1) Protective stop — honoured first, always. (Never widened.)
        if bar.low <= pos.stop:
            # Model gap risk: if the candle opened below the stop, a real stop
            # fills at the worse opening price, not the (un-reachable) stop level.
            gapped = bar.open < pos.stop
            fill = round(bar.open, 4) if gapped else pos.stop
            base = "break-even stop hit (trade was free)" if pos.breakeven_moved else "protective stop hit"
            return [ManageAction("exit_all", qty=pos.qty, price=fill,
                                 reason=base + (" — GAPPED through the stop" if gapped else ""))]

        # 2) Extension bar — parabolic spike, sell into it before the snap-back.
        parabolic = atr and (bar.close - bar.open) >= r.extension_atr_mult * atr
        if bar.high >= ext_level and parabolic:
            price = min(bar.high, ext_level)
            return [ManageAction("exit_all", qty=pos.qty, price=round(price, 4),
                                 reason=f"extension bar ~{r.extension_r:g}R — sold into the spike")]

        # 3) First target — scale half + move stop to break-even (only once).
        if not pos.scaled and bar.high >= scale_target:
            half = pos.qty // 2
            if half > 0:
                actions.append(ManageAction("scale_half", qty=half, price=round(scale_target, 4),
                                            reason=f"first target ~{r.first_target_r:g}R — sold half"))
                actions.append(ManageAction("move_stop_breakeven", price=round(entry, 4),
                                            reason="moved stop to break-even — trade is now free"))
            else:
                # too small to split — take the whole thing at target
                actions.append(ManageAction("exit_all", qty=pos.qty, price=round(scale_target, 4),
                                            reason="first target hit (position too small to scale)"))
            return actions

        # 4) First red candle close (only before scaling).
        if not pos.scaled and bar.is_red:
            return [ManageAction("exit_all", qty=pos.qty, price=round(bar.close, 4),
                                 reason="first red candle close (un-scaled) — momentum faded")]

        return [ManageAction("hold", reason="holding; stop intact")]

    def apply(self, pos: Position, actions: list[ManageAction], state: State,
              now: datetime) -> Optional[ClosedTrade]:
        """Execute the decided actions. Returns a ClosedTrade if fully closed."""
        closed: Optional[ClosedTrade] = None
        for a in actions:
            if a.kind == "hold":
                continue
            if a.kind == "move_stop_breakeven":
                pos.stop = a.price
                pos.breakeven_moved = True
                pos.events.append(f"{now.isoformat()} {a.reason}")
                continue
            if a.kind == "scale_half":
                fill = self.broker.sell(pos.symbol, a.qty, a.price, reason=a.reason)
                qty = fill.qty or a.qty
                realized = round(qty * (a.price - pos.avg_entry), 4)
                pos.qty -= qty
                pos.scaled = True
                pos.events.append(f"{now.isoformat()} scaled {qty}@{a.price} (+${realized}) — {a.reason}")
                state.open_positions[pos.symbol] = pos
                state.record_partial(pos.symbol, realized, now)
                continue
            if a.kind == "exit_all":
                qty = pos.qty
                fill = self.broker.sell(pos.symbol, qty, a.price, reason=a.reason)
                leg = round(qty * (a.price - pos.avg_entry), 4)
                total = round(pos.realized_pnl + leg, 4)
                is_loss = total < 0
                pos.events.append(f"{now.isoformat()} exit {qty}@{a.price} (leg ${leg}, "
                                  f"trade ${total}) — {a.reason}")
                risk_total = (pos.initial_qty * pos.initial_risk) if pos.initial_risk > 0 else 0
                closed = ClosedTrade(
                    symbol=pos.symbol, side=pos.side, entry=pos.avg_entry, exit=a.price,
                    qty=pos.initial_qty, gross_pnl=total,
                    r_multiple=round(total / risk_total, 3) if risk_total else 0.0,
                    opened_at=pos.opened_at, closed_at=now,
                    hold_seconds=(now - pos.opened_at).total_seconds() if pos.opened_at else 0.0,
                    exit_reason=a.reason,
                )
                state.record_close(pos.symbol, leg, is_loss, now)
                break
        return closed

    def flatten(self, pos: Position, price: float, state: State, now: datetime,
                reason: str) -> Optional[ClosedTrade]:
        """Force-close a position (EOD flatten / no overnight holds)."""
        return self.apply(pos, [ManageAction("exit_all", qty=pos.qty, price=round(price, 4),
                                             reason=reason)], state, now)
