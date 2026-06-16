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


def _flag_bars():
    """A quiet base, a sharp pole on rising volume, then a shallow, low-volume
    two-candle pullback — the flag, before any breakout. Enough history for
    MACD/RSI/ATR to populate."""
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


def _intraday():
    """The flag plus a confirmed breakout candle — a 'ready, just triggered'
    setup so `propose` and `run` show an actionable entry."""
    bars = _flag_bars()
    bars.append(_b(len(bars), 3.68, 3.88, 3.67, 3.85, 140_000))   # breakout over 3.78
    return bars


def _daily(n=210):
    out = []
    for i in range(n):
        c = 1.5 + i * 0.011
        out.append(Bar(ts=_DEMO_DAY - timedelta(days=n - i), open=c - 0.02,
                       high=c + 0.05, low=c - 0.05, close=c, volume=2_000_000))
    return out


def _backtest_intraday():
    """A full intraday arc for backtests: flag -> confirmed breakout (entry) ->
    run to the first target (scale + break-even) -> a parabolic extension spike
    (exit the rest). Produces one clean, closeable round-trip."""
    bars = _flag_bars()
    i = len(bars)
    arc = [
        (3.68, 3.88, 3.67, 3.85, 140_000),   # breakout over the 3.78 trigger (entry)
        (3.85, 3.98, 3.84, 3.96, 110_000),   # continuation
        (3.96, 4.08, 3.95, 4.06, 130_000),   # >= first target (~4.04) -> scale + BE
        (4.06, 4.22, 4.05, 4.20, 120_000),   # continuation
        (4.18, 4.62, 4.17, 4.56, 250_000),   # parabolic extension spike -> exit rest
        (4.56, 4.60, 4.30, 4.35, 90_000),    # fade (already out)
        (4.35, 4.40, 4.20, 4.25, 60_000),
    ]
    for (o, h, l, c, v) in arc:
        bars.append(_b(i, o, h, l, c, v)); i += 1
    return bars


class DemoProvider(SyntheticProvider):
    name = "demo"

    def __init__(self, symbol: str = "WARR", intraday=None):
        sym = symbol.upper()
        super().__init__(
            bars={sym: intraday if intraday is not None else _intraday()},
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

    def get_quote(self, symbol):
        # During a replay, derive the quote from the last visible bar so exits
        # price off the current candle rather than a fixed snapshot.
        bars = self.visible_bars(symbol)
        if bars:
            c = bars[-1].close
            return Quote(bid=round(c - 0.01, 4), ask=round(c + 0.01, 4))
        return super().get_quote(symbol)


def demo_backtest_provider(symbol: str = "WARR") -> DemoProvider:
    return DemoProvider(symbol, intraday=_backtest_intraday())


DEMO_NOW = datetime(2026, 6, 16, 9, 45)
