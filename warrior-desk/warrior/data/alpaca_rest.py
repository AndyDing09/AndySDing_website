"""A tiny, dependency-free Alpaca REST client (standard library ``urllib``).

The spec names ``alpaca-py``; we deliberately speak the documented REST API
directly (the same approach the site's PHP broker uses) so the safety-critical
core has zero heavy dependencies and the single network seam (``_request``) is
trivial to mock in tests. Swap in ``alpaca-py`` later behind the same interface
if desired.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from ..logging_setup import get_logger

log = get_logger("alpaca")

PAPER_TRADING_BASE = "https://paper-api.alpaca.markets"
LIVE_TRADING_BASE = "https://api.alpaca.markets"
DATA_BASE = "https://data.alpaca.markets"


class AlpacaREST:
    def __init__(self, key: str, secret: str, mode: str = "paper", timeout: float = 15.0):
        self.key = key
        self.secret = secret
        self.mode = "live" if mode == "live" else "paper"
        self.timeout = timeout

    @property
    def trading_base(self) -> str:
        return LIVE_TRADING_BASE if self.mode == "live" else PAPER_TRADING_BASE

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.key,
            "APCA-API-SECRET-KEY": self.secret,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, url: str, body: Optional[dict] = None) -> tuple[int, Any]:
        """The single network seam. Returns (status_code, parsed_json | text)."""
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read().decode() if e.fp else ""
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {"message": raw}
            return e.code, parsed
        except urllib.error.URLError as e:
            log.error("Network error calling Alpaca: %s", e)
            return 0, {"message": str(e)}

    # ── convenience ──
    def get(self, path: str, params: Optional[dict] = None, data_api: bool = False) -> tuple[int, Any]:
        base = DATA_BASE if data_api else self.trading_base
        url = base + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        return self._request("GET", url)

    def post(self, path: str, body: dict, data_api: bool = False) -> tuple[int, Any]:
        base = DATA_BASE if data_api else self.trading_base
        return self._request("POST", base + path, body=body)

    def delete(self, path: str, data_api: bool = False) -> tuple[int, Any]:
        base = DATA_BASE if data_api else self.trading_base
        return self._request("DELETE", base + path)
