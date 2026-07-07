"""Bad-tick scrubbing (§4.2).

Erroneous prints skew candles and fire false breakouts, so every trade passes
through here before it can touch a bar, an HOD, or a signal. Three filters:

1. irregular SIP condition codes (out-of-sequence, cancelled, derivative prints),
2. zero/negative-size prints,
3. price more than N standard deviations from the 1-minute rolling mean.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import sqrt

from ..models import Tick

# SIP trade conditions that must never influence candles or HOD state.
# (C/G/H/I/M/N/P/Q/T/U/V/W/Z variants cover cancels, out-of-sequence, average
# price, prior-reference and derivative prints. Kept conservative and explicit.)
IRREGULAR_CONDITIONS: frozenset[str] = frozenset(
    {"B", "C", "G", "H", "I", "M", "N", "P", "Q", "T", "U", "V", "W", "Z", "4", "7", "9"}
)


@dataclass
class _Window:
    """Rolling ~1-minute window of accepted prices for one symbol."""
    seconds: float = 60.0
    points: deque = field(default_factory=deque)   # (epoch_seconds, price)
    sum_: float = 0.0
    sumsq: float = 0.0

    def add(self, ts: float, price: float) -> None:
        self.points.append((ts, price))
        self.sum_ += price
        self.sumsq += price * price
        self._evict(ts)

    def _evict(self, now: float) -> None:
        while self.points and now - self.points[0][0] > self.seconds:
            _, old = self.points.popleft()
            self.sum_ -= old
            self.sumsq -= old * old

    def stats(self) -> tuple[int, float, float]:
        n = len(self.points)
        if n == 0:
            return 0, 0.0, 0.0
        mean = self.sum_ / n
        var = max(0.0, self.sumsq / n - mean * mean)
        return n, mean, sqrt(var)


class TickScrubber:
    """Stateful per-symbol scrubber. ``accept()`` returns (ok, reason)."""

    # Below this many in-window samples a σ estimate is noise, so the σ filter
    # stays off and only condition/size checks apply.
    MIN_SAMPLES_FOR_SIGMA = 12

    def __init__(self, sigma: float = 10.0, min_size: int = 1):
        self.sigma = sigma
        self.min_size = min_size
        self._windows: dict[str, _Window] = {}
        self.dropped: int = 0

    def accept(self, tick: Tick) -> tuple[bool, str]:
        if any(c in IRREGULAR_CONDITIONS for c in tick.conditions):
            self.dropped += 1
            return False, "irregular_condition"
        if tick.size < self.min_size:
            self.dropped += 1
            return False, "zero_size"

        w = self._windows.setdefault(tick.symbol, _Window())
        n, mean, sd = w.stats()
        if n >= self.MIN_SAMPLES_FOR_SIGMA and sd > 0:
            if abs(tick.price - mean) > self.sigma * sd:
                self.dropped += 1
                return False, "price_outlier"

        w.add(tick.ts.timestamp(), tick.price)
        return True, ""
