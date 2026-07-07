"""Stale-data detection (§4.3). Never trade through a gap.

Two failure shapes, two responses:
- one symbol goes quiet (> N s without a tick) while SPY keeps ticking →
  that symbol is STALE and its signals are suppressed until it prints again;
- the whole stream goes quiet (> M s) → a data-gap incident is recorded and the
  connection owner is told to reconnect with exponential backoff.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..models import Incident


@dataclass
class StaleMonitor:
    symbol_timeout: float = 5.0
    stream_timeout: float = 10.0
    reference_symbol: str = "SPY"
    last_tick: dict[str, float] = field(default_factory=dict)   # symbol -> epoch s
    last_any: float = 0.0
    stale: set[str] = field(default_factory=set)
    incidents: list[Incident] = field(default_factory=list)
    _backoff: float = 1.0

    def on_tick(self, symbol: str, ts: datetime) -> None:
        epoch = ts.timestamp()
        self.last_tick[symbol] = epoch
        self.last_any = max(self.last_any, epoch)
        if symbol in self.stale:
            self.stale.discard(symbol)
        if symbol == self.reference_symbol:
            self._backoff = 1.0   # healthy reference stream resets the backoff ladder

    def is_stale(self, symbol: str) -> bool:
        return symbol in self.stale

    def sweep(self, now: datetime) -> tuple[set[str], bool]:
        """Periodic check. Returns (newly_stale_symbols, stream_gap_detected)."""
        epoch = now.timestamp()
        newly_stale: set[str] = set()

        ref_fresh = (epoch - self.last_tick.get(self.reference_symbol, 0.0)) <= self.symbol_timeout
        if ref_fresh:
            for sym, last in self.last_tick.items():
                if sym == self.reference_symbol:
                    continue
                if epoch - last > self.symbol_timeout and sym not in self.stale:
                    self.stale.add(sym)
                    newly_stale.add(sym)
                    self.incidents.append(Incident(
                        ts=now, kind="stale_symbol", symbol=sym,
                        detail=f"no tick for >{self.symbol_timeout:.0f}s while "
                               f"{self.reference_symbol} ticks normally"))

        stream_gap = self.last_any > 0 and (epoch - self.last_any) > self.stream_timeout
        if stream_gap:
            self.incidents.append(Incident(
                ts=now, kind="stream_gap",
                detail=f"no ticks on any symbol for >{self.stream_timeout:.0f}s; "
                       f"reconnect with backoff {self._backoff:.0f}s"))
        return newly_stale, stream_gap

    def next_backoff(self) -> float:
        """Exponential backoff for reconnects, capped at 60s."""
        current = self._backoff
        self._backoff = min(self._backoff * 2, 60.0)
        return current
