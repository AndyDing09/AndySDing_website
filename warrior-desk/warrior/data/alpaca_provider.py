"""Alpaca-backed DataProvider.

Parsing is split into free functions so they can be unit-tested against canned
JSON without any network. Honest about gaps: float is delegated to a FloatSource,
RVOL needs a baseline the data layer may not have, and halt detection is
best-effort.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ..catalysts import classify_catalyst
from ..logging_setup import get_logger
from ..models import Bar, Candidate, Catalyst, Quote
from .alpaca_rest import AlpacaREST
from .float_source import FloatSource, UnknownFloatSource
from .provider import AccountInfo, DataProvider, FloatInfo, MarketDataError

log = get_logger("alpaca")


def parse_ts(s: Optional[str]) -> Optional[datetime]:
    """Parse an Alpaca RFC-3339 timestamp, tolerating 'Z' and nanoseconds."""
    if not s:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Truncate over-long fractional seconds (Python wants <= 6 digits).
    if "." in s:
        head, _, tail = s.partition(".")
        digits = ""
        rest = ""
        for i, ch in enumerate(tail):
            if ch.isdigit():
                digits += ch
            else:
                rest = tail[i:]
                break
        s = f"{head}.{digits[:6]}{rest}"
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_bars(payload: dict) -> list[Bar]:
    out: list[Bar] = []
    for b in (payload or {}).get("bars", []) or []:
        ts = parse_ts(b.get("t"))
        try:
            out.append(Bar(ts=ts, open=float(b["o"]), high=float(b["h"]),
                           low=float(b["l"]), close=float(b["c"]), volume=float(b.get("v", 0))))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def parse_quote(payload: dict) -> Optional[Quote]:
    q = (payload or {}).get("quote")
    if not q:
        return None
    try:
        return Quote(bid=float(q.get("bp", 0)), ask=float(q.get("ap", 0)),
                     bid_size=float(q.get("bs", 0)), ask_size=float(q.get("as", 0)),
                     ts=parse_ts(q.get("t")))
    except (TypeError, ValueError):
        return None


def parse_news(payload: dict) -> list[Catalyst]:
    out: list[Catalyst] = []
    for n in (payload or {}).get("news", []) or []:
        headline = n.get("headline", "")
        if not headline:
            continue
        out.append(classify_catalyst(headline, source=n.get("source", "alpaca"),
                                     ts=parse_ts(n.get("created_at"))))
    return out


def parse_movers(payload: dict) -> list[Candidate]:
    """Use the gainers from Alpaca's screener as watchlist seeds."""
    out: list[Candidate] = []
    for g in (payload or {}).get("gainers", []) or []:
        try:
            out.append(Candidate(symbol=str(g["symbol"]).upper(),
                                  price=float(g.get("price", 0)),
                                  gap_pct=float(g.get("percent_change", 0)) / 100.0))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def parse_account(payload: dict, mode: str) -> AccountInfo:
    def f(key):
        try:
            return float(payload.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0
    return AccountInfo(
        equity=f("equity"), cash=f("cash"), buying_power=f("buying_power"),
        status=str(payload.get("status", "UNKNOWN")),
        pattern_day_trader=bool(payload.get("pattern_day_trader", False)),
        mode=mode,
    )


class AlpacaProvider(DataProvider):
    name = "alpaca"

    def __init__(self, key: str, secret: str, mode: str = "paper",
                 float_source: Optional[FloatSource] = None, feed: str = "iex"):
        self.rest = AlpacaREST(key, secret, mode=mode)
        self.float_source = float_source or UnknownFloatSource()
        self.feed = feed   # 'iex' (free) or 'sip' (paid)

    def get_bars(self, symbol: str, timeframe: str, limit: int = 200) -> list[Bar]:
        status, body = self.rest.get(
            f"/v2/stocks/{symbol}/bars",
            {"timeframe": timeframe, "limit": limit, "feed": self.feed, "adjustment": "raw"},
            data_api=True,
        )
        if status != 200:
            raise MarketDataError(f"bars {symbol}: HTTP {status} {body}")
        return parse_bars(body)

    def get_quote(self, symbol: str) -> Optional[Quote]:
        status, body = self.rest.get(
            f"/v2/stocks/{symbol}/quotes/latest", {"feed": self.feed}, data_api=True)
        if status != 200:
            raise MarketDataError(f"quote {symbol}: HTTP {status}")
        return parse_quote(body)

    def get_news(self, symbol: str, limit: int = 10) -> list[Catalyst]:
        status, body = self.rest.get(
            "/v1beta1/news", {"symbols": symbol, "limit": limit}, data_api=True)
        if status != 200:
            return []
        return parse_news(body)

    def get_movers(self, limit: int = 20) -> list[Candidate]:
        status, body = self.rest.get(
            "/v1beta1/screener/stocks/movers", {"top": limit}, data_api=True)
        if status != 200:
            log.warning("movers screener unavailable (HTTP %s); watchlist will be thin.", status)
            return []
        return parse_movers(body)[:limit]

    def get_float(self, symbol: str) -> FloatInfo:
        return self.float_source.get_float(symbol)

    def get_account(self) -> AccountInfo:
        status, body = self.rest.get("/v2/account")
        if status != 200:
            raise MarketDataError(f"account: HTTP {status} {body}")
        return parse_account(body, self.rest.mode)
