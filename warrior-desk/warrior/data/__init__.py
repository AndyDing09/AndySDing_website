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
]
