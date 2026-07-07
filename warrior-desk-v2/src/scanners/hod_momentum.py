"""High-of-Day momentum scanner (§3.2) — event-driven off the trade stream.

Maintains the running HOD for every watchlist symbol (plus any stock that newly
qualifies intraday). A new HOD print on a QUALIFYING stock emits an alert and
hands the symbol to the strategy layer. Repeated alerts within the re-alert
window mark a fast mover. Never alerts on non-qualifying stocks — signal-to-noise
is the whole point.

Halt awareness (§3.3): a halted symbol is flagged and suppressed until 2 full
minutes after resumption; resumption candles are violent and untradeable by rule.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

from ..models import Tick

log = logging.getLogger("wd.hod")


@dataclass
class HodAlert:
    symbol: str
    ts: datetime
    price: float
    prev_hod: float
    repeats_in_window: int      # >1 = fast mover
    fast_mover: bool


@dataclass
class HaltState:
    halted: bool = False
    resumed_at: Optional[datetime] = None


class HodScanner:
    def __init__(self, realert_window_seconds: int = 180,
                 halt_quiet_minutes: int = 2,
                 on_alert: Optional[Callable[[HodAlert], None]] = None):
        self.realert_window = timedelta(seconds=realert_window_seconds)
        self.halt_quiet = timedelta(minutes=halt_quiet_minutes)
        self.on_alert = on_alert
        self.hod: dict[str, float] = {}
        self.qualifying: set[str] = set()
        self.halts: dict[str, HaltState] = {}
        self._recent_alerts: dict[str, list[datetime]] = {}

    # ── membership ──
    def set_qualifying(self, symbols: set[str]) -> None:
        self.qualifying = {s.upper() for s in symbols}

    def add_qualifying(self, symbol: str) -> None:
        self.qualifying.add(symbol.upper())

    # ── halt stream (§3.3) ──
    def on_halt(self, symbol: str, ts: datetime) -> None:
        self.halts[symbol.upper()] = HaltState(halted=True)
        log.warning("%s HALTED at %s — signals suppressed", symbol, ts.isoformat())

    def on_resume(self, symbol: str, ts: datetime) -> None:
        st = self.halts.setdefault(symbol.upper(), HaltState())
        st.halted = False
        st.resumed_at = ts

    def suppressed(self, symbol: str, now: datetime) -> bool:
        st = self.halts.get(symbol.upper())
        if st is None:
            return False
        if st.halted:
            return True
        if st.resumed_at is not None and (now - st.resumed_at) < self.halt_quiet:
            return True
        return False

    # ── trade stream ──
    def on_tick(self, tick: Tick) -> Optional[HodAlert]:
        """Feed every SCRUBBED tick here. Returns an alert when a qualifying,
        unsuppressed symbol prints a new HOD."""
        sym = tick.symbol.upper()
        prev = self.hod.get(sym)
        if prev is None or tick.price > prev:
            self.hod[sym] = tick.price
            if prev is None:
                return None                       # first print seeds the HOD, no alert
            if sym not in self.qualifying:
                return None                       # never alert on non-qualifying stocks
            if self.suppressed(sym, tick.ts):
                return None
            recent = [t for t in self._recent_alerts.get(sym, [])
                      if tick.ts - t <= self.realert_window]
            recent.append(tick.ts)
            self._recent_alerts[sym] = recent
            alert = HodAlert(symbol=sym, ts=tick.ts, price=tick.price, prev_hod=prev,
                             repeats_in_window=len(recent),
                             fast_mover=len(recent) >= 3)
            if self.on_alert:
                self.on_alert(alert)
            return alert
        return None
