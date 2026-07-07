"""Alpaca wrappers (§4.1, §4.7): paper trading + market data + news stream.

Design rules:
- The trading client is constructed with ``paper=True`` and the config layer has
  already rejected any non-paper URL — belt and suspenders.
- Every stored record is stamped with the configured feed. On IEX a startup
  banner warns that rvol and HOD detection are approximations of the full tape.
- Works unchanged if the account is upgraded to SIP: feed comes from config.
- All network objects are lazily constructed so the whole codebase imports and
  tests without credentials or connectivity.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from ..config import Config
from ..models import Feed

log = logging.getLogger("wd.alpaca")

IEX_BANNER = (
    "=" * 78 + "\n"
    "DATA FEED: IEX (free plan). IEX carries a small slice of consolidated volume:\n"
    "on low-float small caps, HODs can print late, volume reads low, and spreads\n"
    "can look fake. RVOL and HOD detection are APPROXIMATIONS until the account\n"
    "is upgraded to SIP (set data.feed: sip — zero code changes needed).\n"
    + "=" * 78
)


def feed_banner(feed: Feed) -> str | None:
    return IEX_BANNER if feed == "iex" else None


class AlpacaClients:
    """Lazy holder for the alpaca-py clients used across the app."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.key = os.environ.get("ALPACA_API_KEY", "")
        self.secret = os.environ.get("ALPACA_SECRET_KEY", "")
        self._trading = None
        self._market = None

    @property
    def trading(self):
        if self._trading is None:
            from alpaca.trading.client import TradingClient
            # paper=True is hard-wired; cfg.data.trading_base_url was already
            # validated to be the paper host at startup.
            self._trading = TradingClient(self.key, self.secret, paper=True)
        return self._trading

    @property
    def market(self):
        if self._market is None:
            from alpaca.data.historical import StockHistoricalDataClient
            self._market = StockHistoricalDataClient(self.key, self.secret)
        return self._market

    # ── clock (§4.7) ──
    def server_utc(self) -> datetime:
        clk = self.trading.get_clock()
        ts = clk.timestamp
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)

    def startup_banner(self) -> None:
        banner = feed_banner(self.cfg.data.feed)
        if banner:
            print(banner)
            log.warning("running on IEX feed — rvol/HOD are approximations")


def make_stream(cfg: Config):
    """Construct the alpaca-py live stream for the configured feed.

    Kept in one factory so run_session wires it and replay swaps it for the
    stored-data player with identical downstream code paths.
    """
    from alpaca.data.live import StockDataStream
    from alpaca.data.enums import DataFeed
    feed = DataFeed.SIP if cfg.data.feed == "sip" else DataFeed.IEX
    return StockDataStream(
        os.environ.get("ALPACA_API_KEY", ""),
        os.environ.get("ALPACA_SECRET_KEY", ""),
        feed=feed,
    )
