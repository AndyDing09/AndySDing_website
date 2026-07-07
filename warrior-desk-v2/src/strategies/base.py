"""Strategy base + shared candle math.

Each setup is a `Strategy` subclass exposing ``detect() -> Signal | None`` over a
`MarketView` (the read-only slice of state a strategy may see). Strategies emit
PROPOSED signals only; the risk layer decides what becomes an order.

LONG-ONLY (§1.4): the short side is deliberately not implemented.
# EXTENSION POINT (do not build): a short-side Strategy would mirror detect()
# with entry below support and stop above. Warrior methodology for beginners is
# long momentum; shorting low-float movers adds borrow, halt and squeeze risk.

REVERSALS (§2.2): deliberately not implemented.
# STUB (do not build): reversal/contrarian setups fight a news-driven trend and
# need elite timing — one mistimed entry erases many base hits.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Optional

from ..config import Config
from ..models import Bar, Candidate, Quote, Regime, Signal
from ..data.clock import in_window


def ema_series(values: list[float], period: int) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    out[period - 1] = e
    for i in range(period, len(values)):
        e = values[i] * k + e * (1 - k)
        out[i] = e
    return out


def ema_last(values: list[float], period: int) -> Optional[float]:
    s = ema_series(values, period)
    return s[-1] if s else None


def session_vwap(bars: list[Bar]) -> Optional[float]:
    pv = v = 0.0
    for b in bars:
        pv += ((b.high + b.low + b.close) / 3) * b.volume
        v += b.volume
    return (pv / v) if v > 0 else None


def atr(bars: list[Bar], period: int = 14) -> Optional[float]:
    if len(bars) < period + 1:
        return None
    trs = []
    for prev, cur in zip(bars, bars[1:]):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close),
                       abs(cur.low - prev.close)))
    window = trs[-period:]
    return sum(window) / len(window)


def avg_volume(bars: list[Bar]) -> float:
    return (sum(b.volume for b in bars) / len(bars)) if bars else 0.0


@dataclass
class MarketView:
    """Everything a strategy is allowed to see for one symbol at one moment."""
    now: datetime
    candidate: Candidate                 # the qualifying watchlist row (§2.1 passed)
    bars_1m: list[Bar]                   # session so far, scrubbed
    quote: Optional[Quote] = None
    hod: float = 0.0
    regime: Regime = Regime.MIXED
    premkt_high: Optional[float] = None
    premkt_low: Optional[float] = None
    feed: str = "iex"


class Strategy(ABC):
    name = "abstract"

    def __init__(self, cfg: Config):
        self.cfg = cfg

    @abstractmethod
    def window(self) -> tuple[time, time]: ...

    @abstractmethod
    def _detect(self, view: MarketView) -> Optional[Signal]: ...

    def detect(self, view: MarketView) -> Optional[Signal]:
        """Window-gated detection. A structurally valid Signal or None —
        the 2:1 gate and every risk rule run AFTER this, in the risk layer."""
        if not in_window(view.now, self.window()):
            return None
        sig = self._detect(view)
        if sig is None:
            return None
        # Structural sanity a long signal must always satisfy.
        if not (sig.stop < sig.entry < sig.target):
            return None
        sig.planned_rr = sig.rr
        return sig
