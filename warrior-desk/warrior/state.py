"""Session state persistence.

Holds the live, restart-critical facts: open positions, day P&L, trade count,
consecutive losses, cooldown timestamps, the rolling day-trade history (for PDT),
and the session-halt flag. Persisted as JSON so a crash/restart can't lose track
and double-trade. Cumulative *closed-trade* history lives in the journal CSV
(see ``warrior.journal``); this file is the in-flight session ledger.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .logging_setup import get_logger
from .models import Position, Side

log = get_logger("state")


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _position_to_dict(p: Position) -> dict:
    d = asdict(p)
    d["side"] = p.side.value
    d["opened_at"] = _iso(p.opened_at)
    return d


def _position_from_dict(d: dict) -> Position:
    return Position(
        symbol=d["symbol"], qty=int(d["qty"]), avg_entry=float(d["avg_entry"]),
        stop=float(d["stop"]), target=float(d["target"]),
        side=Side(d.get("side", "long")),
        initial_qty=int(d.get("initial_qty", d["qty"])),
        initial_risk=float(d.get("initial_risk", 0.0)),
        scaled=bool(d.get("scaled", False)),
        breakeven_moved=bool(d.get("breakeven_moved", False)),
        opened_at=_parse_dt(d.get("opened_at")),
        realized_pnl=float(d.get("realized_pnl", 0.0)),
        order_ids=d.get("order_ids", {}) or {},
        events=d.get("events", []) or [],
    )


@dataclass
class State:
    path: str = "state/state.json"
    session_date: Optional[str] = None     # ISO date of the current session
    day_pnl: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    last_loss_ts: Optional[datetime] = None
    symbol_last_trade_ts: dict = field(default_factory=dict)   # symbol -> ISO ts
    day_trade_dates: list = field(default_factory=list)        # ISO dates (rolling)
    session_halted: bool = False
    halt_reason: str = ""
    open_positions: dict = field(default_factory=dict)         # symbol -> Position
    equity_high_water: float = 0.0

    # ── persistence ──
    @classmethod
    def load(cls, path: str = "state/state.json") -> "State":
        p = Path(path)
        if not p.exists():
            return cls(path=path)
        try:
            d = json.loads(p.read_text())
        except Exception as exc:
            log.error("Corrupt state file %s (%s); starting fresh but NOT overwriting.", path, exc)
            return cls(path=path)
        st = cls(path=path)
        st.session_date = d.get("session_date")
        st.day_pnl = float(d.get("day_pnl", 0.0))
        st.trades_today = int(d.get("trades_today", 0))
        st.consecutive_losses = int(d.get("consecutive_losses", 0))
        st.last_loss_ts = _parse_dt(d.get("last_loss_ts"))
        st.symbol_last_trade_ts = d.get("symbol_last_trade_ts", {}) or {}
        st.day_trade_dates = d.get("day_trade_dates", []) or []
        st.session_halted = bool(d.get("session_halted", False))
        st.halt_reason = d.get("halt_reason", "")
        st.equity_high_water = float(d.get("equity_high_water", 0.0))
        st.open_positions = {
            sym: _position_from_dict(pd) for sym, pd in (d.get("open_positions", {}) or {}).items()
        }
        return st

    def save(self) -> None:
        d = {
            "session_date": self.session_date,
            "day_pnl": round(self.day_pnl, 4),
            "trades_today": self.trades_today,
            "consecutive_losses": self.consecutive_losses,
            "last_loss_ts": _iso(self.last_loss_ts),
            "symbol_last_trade_ts": self.symbol_last_trade_ts,
            "day_trade_dates": self.day_trade_dates,
            "session_halted": self.session_halted,
            "halt_reason": self.halt_reason,
            "equity_high_water": round(self.equity_high_water, 4),
            "open_positions": {s: _position_to_dict(p) for s, p in self.open_positions.items()},
        }
        p = Path(self.path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            # atomic write: temp file + replace, so a crash mid-write can't corrupt state
            with tempfile.NamedTemporaryFile("w", dir=p.parent, delete=False) as tf:
                json.dump(d, tf, indent=2)
                tmp = tf.name
            Path(tmp).replace(p)
        except Exception as exc:
            log.error("Failed to persist state: %s", exc)

    # ── session lifecycle ──
    def start_session(self, today: date) -> None:
        """Roll daily counters if a new trading day has begun. The rolling
        day-trade history and the high-water mark persist across days."""
        iso = today.isoformat()
        if self.session_date != iso:
            log.info("New session %s (was %s): resetting daily counters.", iso, self.session_date)
            self.session_date = iso
            self.day_pnl = 0.0
            self.trades_today = 0
            self.consecutive_losses = 0
            self.last_loss_ts = None
            self.session_halted = False
            self.halt_reason = ""
            self._prune_day_trades(today)
            self.save()

    def _prune_day_trades(self, today: date, keep_business_days: int = 10) -> None:
        """Drop day-trade dates older than the PDT window can ever need."""
        from .risk import _business_days_back
        floor = _business_days_back(today, keep_business_days)
        self.day_trade_dates = [
            s for s in self.day_trade_dates
            if (date.fromisoformat(s[:10]) >= floor if s else False)
        ]

    # ── mutations ──
    def record_entry(self, position: Position, now: datetime) -> None:
        self.open_positions[position.symbol] = position
        self.trades_today += 1
        self.day_trade_dates.append(now.date().isoformat())   # day trading => every entry is a day trade
        self.symbol_last_trade_ts[position.symbol] = now.isoformat()
        self.save()

    def record_partial(self, symbol: str, realized: float, now: datetime) -> None:
        self.day_pnl += realized
        pos = self.open_positions.get(symbol)
        if pos:
            pos.realized_pnl += realized
            pos.scaled = True
        self.symbol_last_trade_ts[symbol] = now.isoformat()
        self.save()

    def record_close(self, symbol: str, realized_pnl: float, is_loss: bool, now: datetime) -> None:
        self.day_pnl += realized_pnl
        self.open_positions.pop(symbol, None)
        self.symbol_last_trade_ts[symbol] = now.isoformat()
        if is_loss:
            self.consecutive_losses += 1
            self.last_loss_ts = now
        else:
            self.consecutive_losses = 0
        self.save()

    def halt(self, reason: str) -> None:
        self.session_halted = True
        self.halt_reason = reason
        log.warning("SESSION HALTED: %s", reason)
        self.save()

    # ── derived ──
    def last_loss_dt(self) -> Optional[datetime]:
        return self.last_loss_ts

    def symbol_last_dt(self, symbol: str) -> Optional[datetime]:
        return _parse_dt(self.symbol_last_trade_ts.get(symbol))

    @property
    def open_count(self) -> int:
        return len(self.open_positions)
