"""The DataProvider interface + shared data types.

Alpaca does NOT provide share float, and its scanner coverage for true low-float
momentum gappers is limited. This interface makes those gaps first-class: the
float lookup is a separate pluggable source, and when it can't answer we surface
"unverified" rather than inventing a number.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from ..models import Bar, Candidate, Catalyst, Quote


class MarketDataError(RuntimeError):
    """Raised when market data can't be obtained (network, auth, rate limit)."""


@dataclass
class FloatInfo:
    """Share float lookup result. ``verified`` is False when approximated/unknown."""
    shares: Optional[float] = None
    verified: bool = False
    source: str = "none"
    note: str = ""

    @property
    def known(self) -> bool:
        return self.shares is not None


@dataclass
class AccountInfo:
    equity: float = 0.0
    cash: float = 0.0
    buying_power: float = 0.0
    status: str = "UNKNOWN"
    pattern_day_trader: bool = False
    mode: str = "paper"


class DataProvider(ABC):
    """Read-only market data. Execution lives behind a separate Broker."""

    name: str = "abstract"

    @abstractmethod
    def get_bars(self, symbol: str, timeframe: str, limit: int = 200) -> list[Bar]:
        ...

    @abstractmethod
    def get_quote(self, symbol: str) -> Optional[Quote]:
        ...

    @abstractmethod
    def get_news(self, symbol: str, limit: int = 10) -> list[Catalyst]:
        ...

    @abstractmethod
    def get_movers(self, limit: int = 20) -> list[Candidate]:
        """Top gappers / most-active / highest-RVOL names to seed the watchlist."""
        ...

    # ── concrete defaults; providers may override ──
    def get_float(self, symbol: str) -> FloatInfo:
        """Default: unknown. Wire a real FloatSource to fill this honestly."""
        return FloatInfo(None, verified=False, source="none",
                         note="no float source configured — criterion unverified")

    def is_halted(self, symbol: str) -> bool:
        """Default: unknown -> treat as not halted, but providers that can detect
        LULD halts should override. The risk engine still blocks if a halt is known."""
        return False

    def baseline_volume(self, symbol: str, timeframe: str) -> float:
        """Average volume-for-this-time-of-day used for RVOL. 0.0 => unknown."""
        return 0.0
