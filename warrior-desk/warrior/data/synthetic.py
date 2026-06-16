"""A deterministic, in-memory DataProvider for tests and backtests.

No network, no randomness. Pre-load bars/quotes/news/movers/floats; an optional
per-symbol cursor lets a backtest replay bars one candle at a time.
"""

from __future__ import annotations

from typing import Optional

from ..models import Bar, Candidate, Catalyst, Quote
from .provider import DataProvider, FloatInfo


class SyntheticProvider(DataProvider):
    name = "synthetic"

    def __init__(
        self,
        bars: Optional[dict[str, list[Bar]]] = None,
        quotes: Optional[dict[str, Quote]] = None,
        news: Optional[dict[str, list[Catalyst]]] = None,
        movers: Optional[list[Candidate]] = None,
        floats: Optional[dict[str, FloatInfo]] = None,
        halted: Optional[set[str]] = None,
        baselines: Optional[dict[str, float]] = None,
    ):
        self._bars = {k.upper(): v for k, v in (bars or {}).items()}
        self._quotes = {k.upper(): v for k, v in (quotes or {}).items()}
        self._news = {k.upper(): v for k, v in (news or {}).items()}
        self._movers = movers or []
        self._floats = {k.upper(): v for k, v in (floats or {}).items()}
        self._halted = {s.upper() for s in (halted or set())}
        self._baselines = {k.upper(): v for k, v in (baselines or {}).items()}
        self.cursor: dict[str, int] = {}   # symbol -> last visible bar index (inclusive)

    # ── replay control ──
    def set_cursor(self, symbol: str, idx: int) -> None:
        self.cursor[symbol.upper()] = idx

    def visible_bars(self, symbol: str) -> list[Bar]:
        all_bars = self._bars.get(symbol.upper(), [])
        c = self.cursor.get(symbol.upper())
        return all_bars if c is None else all_bars[: c + 1]

    # ── DataProvider ──
    def get_bars(self, symbol: str, timeframe: str, limit: int = 200) -> list[Bar]:
        return self.visible_bars(symbol)[-limit:]

    def get_quote(self, symbol: str) -> Optional[Quote]:
        q = self._quotes.get(symbol.upper())
        if q is not None:
            return q
        # Derive a tight synthetic quote from the last visible close if none set.
        bars = self.visible_bars(symbol)
        if bars:
            c = bars[-1].close
            return Quote(bid=round(c - 0.01, 4), ask=round(c + 0.01, 4))
        return None

    def get_news(self, symbol: str, limit: int = 10) -> list[Catalyst]:
        return self._news.get(symbol.upper(), [])[:limit]

    def get_movers(self, limit: int = 20) -> list[Candidate]:
        return list(self._movers)[:limit]

    def get_float(self, symbol: str) -> FloatInfo:
        return self._floats.get(symbol.upper(), super().get_float(symbol))

    def is_halted(self, symbol: str) -> bool:
        return symbol.upper() in self._halted

    def baseline_volume(self, symbol: str, timeframe: str) -> float:
        return self._baselines.get(symbol.upper(), 0.0)
