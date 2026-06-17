"""Pluggable share-float lookup.

Float is the #1 selection criterion (low float = explosive) but no free, reliable
API gives it. So it's a separate source the Operator can wire up (a paid feed, a
maintained CSV, etc.). The default is honest ignorance.
"""

from __future__ import annotations

import csv
from abc import ABC, abstractmethod
from pathlib import Path

from .provider import FloatInfo


class FloatSource(ABC):
    @abstractmethod
    def get_float(self, symbol: str) -> FloatInfo:
        ...


class UnknownFloatSource(FloatSource):
    """Always returns 'unknown'. The gauntlet downgrades setups it can't verify."""

    def get_float(self, symbol: str) -> FloatInfo:
        return FloatInfo(
            shares=None, verified=False, source="none",
            note="float unknown — no source configured; setup downgraded, not rejected",
        )


class StaticFloatSource(FloatSource):
    """Float from an Operator-maintained mapping or CSV (symbol,float_shares).

    This is *verified* in the sense that the Operator vouches for it — flagged as
    such so the journal is honest about provenance.
    """

    def __init__(self, mapping: dict[str, float] | None = None, source: str = "operator"):
        self._map = {k.upper(): float(v) for k, v in (mapping or {}).items()}
        self._source = source

    @classmethod
    def from_csv(cls, path: str) -> "StaticFloatSource":
        m: dict[str, float] = {}
        p = Path(path)
        if p.exists():
            with p.open(newline="") as fh:
                for row in csv.reader(fh):
                    if len(row) >= 2 and row[0] and row[0].lower() != "symbol":
                        try:
                            m[row[0].strip().upper()] = float(row[1])
                        except ValueError:
                            continue
        return cls(m, source=f"csv:{path}")

    def get_float(self, symbol: str) -> FloatInfo:
        v = self._map.get(symbol.upper())
        if v is None:
            return UnknownFloatSource().get_float(symbol)
        return FloatInfo(shares=v, verified=True, source=self._source,
                         note="operator-provided float")


class CachingFloatSource(FloatSource):
    """Memoize float lookups for the session — float doesn't change intraday, so a
    slow per-symbol fetch (e.g. Yahoo) should happen at most once per symbol."""

    def __init__(self, inner: FloatSource):
        self._inner = inner
        self._cache: dict[str, FloatInfo] = {}

    def get_float(self, symbol: str) -> FloatInfo:
        s = symbol.upper()
        if s not in self._cache:
            self._cache[s] = self._inner.get_float(symbol)
        return self._cache[s]
