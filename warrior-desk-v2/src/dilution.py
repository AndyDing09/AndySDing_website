"""Dilution radar (§7.8).

Two independent detectors, either one caps the quality score at ``dilution_cap``
(auto half-size-or-skip):

1. the catalyst feed already classified an offering/dilution headline (§4.6);
2. a lightweight SEC EDGAR full-text query for recent S-3 / 424B filings or an
   active ATM. Network calls are best-effort with a short timeout and a
   per-session cache: EDGAR being down must never block the open — the radar
   degrades to news-only and says so.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import CatalystType, NewsItem

log = logging.getLogger("wd.dilution")

_DILUTION_FORMS = ("S-3", "S-3/A", "424B5", "424B3", "F-3")
_EDGAR_FTS = "https://efts.sec.gov/LATEST/search-index?q={q}&dateRange=custom&startdt={start}&enddt={end}&forms={forms}"
_EDGAR_FALLBACK = "https://efts.sec.gov/LATEST/search-index?q={q}"


@dataclass
class DilutionCheck:
    risky: bool
    source: str = ""       # news / edgar / none
    detail: str = ""


def check_news(items: list[NewsItem]) -> DilutionCheck:
    for i in items:
        if i.catalyst_type == CatalystType.OFFERING_DILUTION:
            return DilutionCheck(True, "news", i.headline[:120])
    return DilutionCheck(False, "none")


class EdgarRadar:
    """Best-effort EDGAR full-text search for recent shelf/ATM paper."""

    def __init__(self, lookback_days: int = 90, timeout: float = 6.0):
        self.lookback_days = lookback_days
        self.timeout = timeout
        self._cache: dict[str, DilutionCheck] = {}

    def check(self, symbol: str, now: datetime) -> DilutionCheck:
        if symbol in self._cache:
            return self._cache[symbol]
        start = (now - timedelta(days=self.lookback_days)).date().isoformat()
        url = ("https://efts.sec.gov/LATEST/search-index?q=" + urllib.parse.quote(f'"{symbol}"')
               + f"&forms={','.join(_DILUTION_FORMS)}&startdt={start}&enddt={now.date().isoformat()}")
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "warrior-desk-v2 educational research (contact: repo)"})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode())
            hits = int(data.get("hits", {}).get("total", {}).get("value", 0))
            res = DilutionCheck(hits > 0, "edgar",
                                f"{hits} recent {'/'.join(_DILUTION_FORMS)} filings" if hits
                                else "no recent shelf/ATM filings found")
        except Exception as exc:
            # EDGAR down ≠ safe; it means UNKNOWN. Degrade loudly to news-only.
            log.warning("EDGAR check failed for %s (%s) — dilution radar degraded to news-only",
                        symbol, exc)
            res = DilutionCheck(False, "edgar_unavailable", str(exc)[:80])
        self._cache[symbol] = res
        return res


def dilution_risk(symbol: str, news: list[NewsItem], now: datetime,
                  edgar: EdgarRadar | None = None) -> DilutionCheck:
    n = check_news(news)
    if n.risky:
        return n
    if edgar is not None:
        return edgar.check(symbol, now)
    return DilutionCheck(False, "news_only")
