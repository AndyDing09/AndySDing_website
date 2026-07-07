"""Corporate-actions guard (§4.5).

A reverse split makes yesterday-based gap % garbage: a 1-for-10 on a $0.50 stock
prints as a +900% "gap" and tops every scanner. Before the open, symbols with an
effective split today are either price-adjusted (when the ratio is known) or
excluded for the day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class SplitEvent:
    symbol: str
    effective: date
    ratio: float          # new_shares / old_shares; reverse split => ratio < 1 (e.g. 0.1)


@dataclass
class CorpActionsGuard:
    events: list[SplitEvent] = field(default_factory=list)

    def splits_today(self, today: date) -> dict[str, SplitEvent]:
        return {e.symbol: e for e in self.events if e.effective == today}

    def adjusted_prior_close(self, symbol: str, prior_close: float, today: date) -> float | None:
        """Return the prior close adjusted for today's split, or None to EXCLUDE.

        With a known ratio the prior close is divided by it (1-for-10 reverse:
        ratio 0.1 -> prior close x10). Ratio <= 0 or unknown => exclude the
        symbol rather than trade on a fictional gap.
        """
        ev = self.splits_today(today).get(symbol)
        if ev is None:
            return prior_close
        if ev.ratio and ev.ratio > 0:
            return prior_close / ev.ratio
        return None

    def excluded(self, symbol: str, today: date) -> bool:
        ev = self.splits_today(today).get(symbol)
        return ev is not None and not (ev.ratio and ev.ratio > 0)
