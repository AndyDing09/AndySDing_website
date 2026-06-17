"""Market-data layer.

A small :class:`DataProvider` interface so the float/scanner gaps Alpaca can't
fill are explicit and pluggable. Never fabricate a metric: when float is unknown
we mark it unverified and downgrade the setup rather than pretending.
"""

from .provider import (
    AccountInfo, DataProvider, FloatInfo, MarketDataError,
)
from .float_source import FloatSource, StaticFloatSource, UnknownFloatSource
from .synthetic import SyntheticProvider

__all__ = [
    "AccountInfo", "DataProvider", "FloatInfo", "MarketDataError",
    "FloatSource", "StaticFloatSource", "UnknownFloatSource", "SyntheticProvider",
    "build_scan_sources",
]


def build_scan_sources(cfg):
    """Return (scanner, float_source) per cfg.scanner (yahoo | alpaca | none)."""
    if getattr(cfg, "scanner", "yahoo") == "yahoo":
        from .float_source import CachingFloatSource
        from .yahoo import YahooFloatSource, YahooScanner
        return YahooScanner(cfg), CachingFloatSource(YahooFloatSource())
    return None, UnknownFloatSource()
