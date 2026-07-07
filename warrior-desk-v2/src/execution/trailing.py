"""Exit management (§2.3 exits): bracket + trailing + time stop.

Rules, in priority order on every bar close for an open position:
1. stop hit (bar.low ≤ stop)                        → exit "stop"
2. target hit (bar.high ≥ target)                   → exit "target"
3. time ≥ 15:55 ET                                  → exit "time_stop" (no overnight holds, ever)
4. +1R reached → move stop to breakeven (once)
5. +2R reached → trail the 9-EMA on 1-min (stop ratchets up only, never widens)

MAE/MFE are tracked per bar for the journal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ..config import ExitsCfg
from ..data.clock import ny_time
from ..models import Bar, Position
from ..strategies.base import ema_last


@dataclass
class ExitDecision:
    action: str                    # hold / exit
    reason: str = ""               # stop / target / time_stop
    stop_moved_to: Optional[float] = None


class PositionManager:
    def __init__(self, cfg: ExitsCfg):
        self.cfg = cfg

    def on_bar(self, pos: Position, bar: Bar, session_closes: list[float],
               now: datetime) -> ExitDecision:
        # MAE / MFE bookkeeping (worst drawdown / best excursion, $ per share).
        pos.mae = min(pos.mae, bar.low - pos.entry)
        pos.mfe = max(pos.mfe, bar.high - pos.entry)

        # 1-2. protective legs. Stop checked first: same-bar both-touch resolves
        # pessimistically (the honest assumption for momentum names).
        if bar.low <= pos.stop:
            return ExitDecision("exit", "stop")
        if bar.high >= pos.target:
            return ExitDecision("exit", "target")

        # 3. time stop — flatten everything still open at 15:55 ET.
        if ny_time(now) >= self.cfg.time_stop:
            return ExitDecision("exit", "time_stop")

        moved: Optional[float] = None
        r = pos.r_at(bar.close)

        # 4. breakeven at +1R (once).
        if not pos.breakeven_moved and r >= self.cfg.breakeven_at_r:
            if pos.entry > pos.stop:
                pos.stop = pos.entry
                moved = pos.stop
            pos.breakeven_moved = True

        # 5. trail the 9-EMA after +2R; ratchet only (never widen a stop).
        if r >= self.cfg.trail_ema_at_r:
            pos.trailing = True
        if pos.trailing:
            e9 = ema_last(session_closes, self.cfg.ema_period)
            if e9 is not None and e9 > pos.stop:
                pos.stop = round(e9, 4)
                moved = pos.stop

        return ExitDecision("hold", stop_moved_to=moved)
