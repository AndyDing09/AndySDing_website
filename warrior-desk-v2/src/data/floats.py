"""Float cross-validation (§4.4).

Float is the least reliable number in this whole system — vendors disagree and
post-offering updates lag. So float is pulled from two independent sources; if
they disagree by more than the configured tolerance the value is flagged
``float_unverified`` and the MORE CONSERVATIVE (larger) figure is used, which
disqualifies borderline names from the A+ tag instead of flattering them.

Providers are pluggable and lazy: FMP and Finnhub need API keys (env), yfinance
needs the package. Anything unavailable simply returns None and the
cross-validator works with what it has.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from abc import ABC, abstractmethod
from typing import Optional

from ..models import FloatInfo

log = logging.getLogger("wd.floats")


class FloatProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    def get_float(self, symbol: str) -> Optional[float]:
        """Return share float, or None if this provider can't answer."""


class StaticFloatProvider(FloatProvider):
    """Deterministic provider for tests and replay fixtures."""

    def __init__(self, mapping: dict[str, float], name: str = "static"):
        self.mapping = {k.upper(): float(v) for k, v in mapping.items()}
        self.name = name

    def get_float(self, symbol: str) -> Optional[float]:
        return self.mapping.get(symbol.upper())


def _http_json(url: str, timeout: float = 8.0) -> dict | list | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "warrior-desk-v2"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as exc:
        log.debug("float http failed: %s", exc)
        return None


class FMPFloatProvider(FloatProvider):
    name = "fmp"

    def __init__(self, api_key: str | None = None):
        self.key = api_key or os.environ.get("FMP_API_KEY", "")

    def get_float(self, symbol: str) -> Optional[float]:
        if not self.key:
            return None
        data = _http_json(
            f"https://financialmodelingprep.com/api/v4/shares_float?symbol={symbol}&apikey={self.key}")
        try:
            return float(data[0]["floatShares"]) if data else None
        except (KeyError, IndexError, TypeError, ValueError):
            return None


class FinnhubFloatProvider(FloatProvider):
    name = "finnhub"

    def __init__(self, api_key: str | None = None):
        self.key = api_key or os.environ.get("FINNHUB_API_KEY", "")

    def get_float(self, symbol: str) -> Optional[float]:
        if not self.key:
            return None
        data = _http_json(
            f"https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={self.key}")
        try:
            # Finnhub reports shareOutstanding in millions; a shares-outstanding
            # proxy is the conservative upper bound when true float is absent.
            v = float(data.get("shareOutstanding", 0)) * 1e6
            return v or None
        except (AttributeError, TypeError, ValueError):
            return None


class YFinanceFloatProvider(FloatProvider):
    name = "yfinance"

    def get_float(self, symbol: str) -> Optional[float]:
        try:
            import yfinance  # lazy; optional dependency
        except ImportError:
            return None
        try:
            info = yfinance.Ticker(symbol).fast_info
            v = getattr(info, "shares_float", None) or getattr(info, "shares", None)
            return float(v) if v else None
        except Exception:
            return None


class CrossValidatedFloat:
    """Combine two+ providers per §4.4."""

    def __init__(self, providers: list[FloatProvider], disagreement_pct: float = 0.25):
        self.providers = providers
        self.disagreement_pct = disagreement_pct

    def get(self, symbol: str) -> FloatInfo:
        readings: dict[str, float] = {}
        for p in self.providers:
            v = p.get_float(symbol)
            if v and v > 0:
                readings[p.name] = v
        if not readings:
            return FloatInfo(shares=None, verified=False, sources={},
                             note="no float source answered — unknown")
        if len(readings) == 1:
            (name, v), = readings.items()
            return FloatInfo(shares=v, verified=False, sources=readings,
                             note=f"single source ({name}) — unverified")

        lo, hi = min(readings.values()), max(readings.values())
        disagreement = (hi - lo) / hi if hi > 0 else 0.0
        if disagreement > self.disagreement_pct:
            return FloatInfo(
                shares=hi, verified=False, sources=readings,
                note=f"sources disagree by {disagreement:.0%} (> "
                     f"{self.disagreement_pct:.0%}); using the conservative "
                     f"(larger) value — float_unverified")
        return FloatInfo(shares=hi, verified=True, sources=readings,
                         note=f"sources agree within {disagreement:.0%}")


def float_band(shares: Optional[float], aplus: float, fmax: float) -> str:
    if shares is None:
        return "unknown"
    if shares < aplus:
        return "<10M"
    if shares <= fmax:
        return "10-20M"
    return ">20M"


def available_float_sources() -> list[str]:
    """Which float providers can actually answer right now.

    FMP/Finnhub need their key in the environment (loaded from secrets.local.ps1
    or .env by ``src.data.secrets``); yfinance needs its package importable.
    Cross-validation (§4.4) — and therefore a *verified* float — needs at least
    two. With fewer, floats are flagged ``float_unverified`` and the quality
    score is penalized accordingly.
    """
    active: list[str] = []
    if os.environ.get("FMP_API_KEY"):
        active.append("fmp")
    if os.environ.get("FINNHUB_API_KEY"):
        active.append("finnhub")
    try:
        import yfinance  # noqa: F401  (lazy; optional dependency)
        active.append("yfinance")
    except Exception:
        pass
    return active


def float_sources_banner() -> str:
    """One operator-facing line tying float-source availability to the score.

    Missing float data is not cosmetic: it pins the 18%-weight float component
    near its floor, enough to drop otherwise-strong setups below the score gate
    (and out of chop days entirely).
    """
    active = available_float_sources()
    if len(active) >= 2:
        return f"float sources: {', '.join(active)} ({len(active)}) — cross-validation ON"
    if len(active) == 1:
        return (f"float sources: {active[0]} only — single-source, floats stay "
                "UNVERIFIED (0.6x credit); add a 2nd free key for the verified A+ tag")
    return ("float sources: NONE — every candidate scores float-unverified "
            "(~12-pt quality penalty; strong setups cap ~65 and are locked out in "
            "chop). Add free keys — see secrets.local.ps1.example")
