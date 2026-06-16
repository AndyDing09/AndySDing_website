"""Free, no-key market scanner via Yahoo Finance's public screeners.

Pulls the day's gainers / small-cap gainers / most-actives across the whole
market so the agent can find the "stock in play" itself, then the gauntlet
qualifies each. Yahoo is an UNOFFICIAL endpoint (it can rate-limit or change),
so every call degrades gracefully to an empty list rather than crashing. Float
comes from Yahoo too — a real ``floatShares`` reads as verified; a fallback to
shares-outstanding is flagged approximate.

Parsing is split into free functions so it's unit-tested against canned JSON
without any network.
"""

from __future__ import annotations

import http.cookiejar
import json
import urllib.parse
import urllib.request
from typing import Optional

from ..config import Config
from ..logging_setup import get_logger
from ..models import Candidate
from .float_source import FloatSource
from .provider import FloatInfo

log = get_logger("yahoo")

_UA = "Mozilla/5.0 (compatible; WarriorDesk/1.0)"
_BASES = ["https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"]
DEFAULT_SCREENERS = ["day_gainers", "small_cap_gainers", "most_actives"]


def _num(v):
    """Yahoo returns numbers as plain values OR {'raw': n, 'fmt': '...'} — handle both."""
    if isinstance(v, dict):
        v = v.get("raw")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def parse_screener(payload: dict) -> list[Candidate]:
    out: list[Candidate] = []
    for res in (payload or {}).get("finance", {}).get("result", []) or []:
        for q in res.get("quotes", []) or []:
            sym = q.get("symbol")
            price = _num(q.get("regularMarketPrice"))
            if not sym or price is None:
                continue
            vol = _num(q.get("regularMarketVolume")) or 0.0
            avg = _num(q.get("averageDailyVolume3Month")) or _num(q.get("averageDailyVolume10Day")) or 0.0
            rvol = round(vol / avg, 2) if avg > 0 else 0.0
            gap = _num(q.get("regularMarketChangePercent"))
            shares = _num(q.get("sharesOutstanding"))
            c = Candidate(
                symbol=str(sym).upper(), price=price,
                gap_pct=(gap / 100.0) if gap is not None else 0.0,
                rvol=rvol, avg_dollar_volume=round(price * avg, 0) if avg else 0.0,
                day_volume=vol, exchange=str(q.get("exchange") or "").upper(),
                float_shares=shares, float_verified=False,
            )
            out.append(c)
    return out


# Pink-sheet / OTC venue codes — where penny-stock junk lives.
_OTC_EXCHANGES = {"PNK", "OTC", "OQB", "OQX", "PINK", "OTCBB", "OBB", "OTCMKTS"}


def parse_float_quote_summary(payload: dict) -> FloatInfo:
    try:
        ks = payload["quoteSummary"]["result"][0].get("defaultKeyStatistics", {})
        fl = _num(ks.get("floatShares"))
        if fl:
            return FloatInfo(shares=fl, verified=True, source="yahoo",
                             note="float from Yahoo defaultKeyStatistics")
        so = _num(ks.get("sharesOutstanding"))
        if so:
            return FloatInfo(shares=so, verified=False, source="yahoo",
                             note="shares-outstanding proxy (float unavailable) — approximate")
    except (KeyError, IndexError, TypeError):
        pass
    return FloatInfo(None, verified=False, source="yahoo", note="float unavailable from Yahoo")


class _YahooHttp:
    """Manages Yahoo's cookie + crumb handshake and JSON GETs."""

    def __init__(self, timeout: float = 12.0):
        self.timeout = timeout
        self._crumb: Optional[str] = None
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def _get(self, url: str) -> tuple[int, str]:
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
        try:
            with self._opener.open(req, timeout=self.timeout) as r:
                return r.status, r.read().decode()
        except Exception as exc:
            log.debug("Yahoo GET failed (%s): %s", url, exc)
            return 0, ""

    def _ensure_crumb(self) -> None:
        if self._crumb is not None:
            return
        # prime cookies, then fetch a crumb (Yahoo requires this for many endpoints)
        self._get("https://fc.yahoo.com/")
        _, body = self._get(_BASES[0] + "/v1/test/getcrumb")
        self._crumb = body.strip() if body and "<" not in body else ""

    def get_json(self, path: str, params: dict) -> dict:
        self._ensure_crumb()
        if self._crumb:
            params = {**params, "crumb": self._crumb}
        qs = urllib.parse.urlencode(params)
        for base in _BASES:
            status, body = self._get(f"{base}{path}?{qs}")
            if status == 200 and body:
                try:
                    return json.loads(body)
                except json.JSONDecodeError:
                    continue
        return {}


class YahooScanner:
    def __init__(self, cfg: Config, screeners: Optional[list[str]] = None):
        self.cfg = cfg
        self.screeners = screeners or DEFAULT_SCREENERS
        self.http = _YahooHttp()

    def _prefilter(self, c: Candidate) -> bool:
        sel = self.cfg.selection
        # No penny stocks: enforce a price floor and drop OTC / pink-sheet venues.
        if not (sel.min_price <= c.price <= sel.max_price):
            return False
        if getattr(sel, "major_exchanges_only", True) and c.exchange in _OTC_EXCHANGES:
            return False
        if c.gap_pct <= 0:                       # momentum = up on the day
            return False
        # No illiquid names: require real average dollar-volume AND real volume today.
        if c.avg_dollar_volume and c.avg_dollar_volume < sel.min_avg_dollar_volume:
            return False
        if c.day_volume and c.day_volume < sel.min_share_volume:
            return False
        return True

    def get_candidates(self, limit: int = 20) -> list[Candidate]:
        merged: dict[str, Candidate] = {}
        for scr in self.screeners:
            payload = self.http.get_json(
                "/v1/finance/screener/predefined/saved", {"count": 50, "scrIds": scr})
            for c in parse_screener(payload):
                if self._prefilter(c) and c.symbol not in merged:
                    merged[c.symbol] = c
        if not merged:
            log.info("Yahoo scanner returned no candidates (rate-limit or off-hours).")
        ranked = sorted(merged.values(), key=lambda c: c.gap_pct * 2 + (c.rvol or 0), reverse=True)
        return ranked[:limit]


class YahooFloatSource(FloatSource):
    def __init__(self):
        self.http = _YahooHttp()

    def get_float(self, symbol: str) -> FloatInfo:
        payload = self.http.get_json(
            f"/v10/finance/quoteSummary/{urllib.parse.quote(symbol)}",
            {"modules": "defaultKeyStatistics"})
        return parse_float_quote_summary(payload)
