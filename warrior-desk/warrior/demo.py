"""A built-in, offline demo scenario so ``warrior propose --demo SYM`` and the
backtest can exercise the full pipeline with zero API keys or network.

The demo stock "WARR" is a clean low-float bull flag with a material catalyst —
the kind of A-grade setup the agent is built to find. Everything here is clearly
synthetic and labelled as such.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .catalysts import classify_catalyst
from .data.provider import FloatInfo
from .data.synthetic import SyntheticProvider
from .models import Bar, Candidate, Quote

_DEMO_DAY = datetime(2026, 6, 16, 9, 30)


def _b(i, o, h, l, c, v):
    return Bar(ts=_DEMO_DAY + timedelta(minutes=i), open=o, high=h, low=l, close=c, volume=v)


def _intraday():
    """~40 candles: a quiet base, a sharp pole on rising volume, then a shallow,
    low-volume two-candle pullback — enough history for MACD/RSI/ATR to populate."""
    bars: list[Bar] = []
    i = 0
    base = 2.85
    for k in range(30):                      # quiet consolidation base
        o = base + (0.01 if k % 2 else -0.01)
        c = base + (-0.01 if k % 2 else 0.01)
        bars.append(_b(i, o, max(o, c) + 0.02, min(o, c) - 0.02, c, 30_000)); i += 1
    pole = [
        (2.90, 3.02, 2.88, 3.00, 50_000), (3.00, 3.15, 2.98, 3.12, 60_000),
        (3.12, 3.30, 3.10, 3.27, 70_000), (3.27, 3.45, 3.25, 3.42, 80_000),
        (3.42, 3.60, 3.40, 3.57, 90_000), (3.57, 3.72, 3.55, 3.69, 100_000),
        (3.69, 3.80, 3.66, 3.78, 110_000),
    ]
    for (o, h, l, c, v) in pole:
        bars.append(_b(i, o, h, l, c, v)); i += 1
    bars.append(_b(i, 3.78, 3.78, 3.69, 3.70, 30_000)); i += 1   # low-volume pullback
    bars.append(_b(i, 3.70, 3.74, 3.65, 3.67, 25_000)); i += 1
    return bars


def _daily(n=210):
    out = []
    for i in range(n):
        c = 1.5 + i * 0.011
        out.append(Bar(ts=_DEMO_DAY - timedelta(days=n - i), open=c - 0.02,
                       high=c + 0.05, low=c - 0.05, close=c, volume=2_000_000))
    return out


class DemoProvider(SyntheticProvider):
    name = "demo"

    def __init__(self, symbol: str = "WARR"):
        sym = symbol.upper()
        super().__init__(
            bars={sym: _intraday()},
            quotes={sym: Quote(bid=3.66, ask=3.68, bid_size=500, ask_size=500)},
            news={sym: [classify_catalyst(
                f"{sym} announces positive topline Phase 3 results", "GlobeNewswire", _DEMO_DAY)]},
            movers=[Candidate(sym, price=3.67, gap_pct=0.46, rvol=5.9)],
            floats={sym: FloatInfo(8_000_000, verified=True, source="demo")},
            baselines={sym: 100_000},
        )
        self._daily = _daily()
        self._sym = sym

    def get_bars(self, symbol, timeframe, limit=200):
        if timeframe == "1Day":
            return self._daily[-limit:]
        return super().get_bars(symbol, timeframe, limit)


DEMO_NOW = datetime(2026, 6, 16, 9, 45)
