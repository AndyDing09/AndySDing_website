"""Execution brokers.

A small Broker interface with two implementations:

  - SimBroker: deterministic in-memory fills for paper sims, backtests, and tests.
    Entries fill at the limit; exits fill at the price the position manager asks
    for. No randomness.
  - AlpacaBroker: real Alpaca orders (paper by default). LIMIT orders only for
    entries/exits — market orders are forbidden in code. The kill switch is the
    only path that uses Alpaca's liquidation endpoints (an emergency stop).

Order types are limit / marketable-limit / stop only. There is no market-order
method anywhere.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from .data.alpaca_rest import AlpacaREST
from .data.provider import AccountInfo
from .logging_setup import get_logger
from .models import OrderResult, Position, Side

log = get_logger("broker")


class Broker(ABC):
    @abstractmethod
    def get_account(self) -> AccountInfo: ...

    @abstractmethod
    def submit_bracket(self, symbol: str, qty: int, entry_limit: float,
                       stop: float, target: float) -> OrderResult: ...

    @abstractmethod
    def sell(self, symbol: str, qty: int, limit_price: float, reason: str = "") -> OrderResult:
        """Marketable-limit sell to exit (or scale) a long."""

    @abstractmethod
    def close_position(self, symbol: str, ref_price: Optional[float] = None) -> OrderResult: ...

    @abstractmethod
    def close_all_positions(self) -> list: ...

    @abstractmethod
    def cancel_all_orders(self) -> int: ...

    @abstractmethod
    def get_position(self, symbol: str) -> Optional[Position]: ...


# ──────────────────────────────────────────────────────────────────────────
# SimBroker
# ──────────────────────────────────────────────────────────────────────────
class SimBroker(Broker):
    def __init__(self, account: AccountInfo):
        self.account = account
        self.positions: dict[str, Position] = {}
        self.fills: list[OrderResult] = []
        self.cancelled = 0
        self._seq = 0

    def _id(self) -> str:
        self._seq += 1
        return f"sim-{self._seq}"

    def get_account(self) -> AccountInfo:
        return self.account

    def submit_bracket(self, symbol, qty, entry_limit, stop, target) -> OrderResult:
        # Deterministic immediate fill at the entry limit.
        pos = Position(symbol=symbol, qty=qty, avg_entry=entry_limit, stop=stop,
                       target=target, side=Side.LONG, initial_qty=qty)
        self.positions[symbol] = pos
        self.account.buying_power -= qty * entry_limit
        res = OrderResult(id=self._id(), symbol=symbol, qty=qty, side="buy",
                          status="filled", filled_avg_price=entry_limit, order_class="bracket")
        self.fills.append(res)
        return res

    def sell(self, symbol, qty, limit_price, reason="") -> OrderResult:
        pos = self.positions.get(symbol)
        if not pos:
            return OrderResult(symbol=symbol, qty=qty, side="sell", status="rejected")
        qty = min(qty, pos.qty)
        pos.qty -= qty
        self.account.buying_power += qty * limit_price
        if pos.qty <= 0:
            self.positions.pop(symbol, None)
        res = OrderResult(id=self._id(), symbol=symbol, qty=qty, side="sell",
                          status="filled", filled_avg_price=limit_price)
        res.raw = {"reason": reason}
        self.fills.append(res)
        return res

    def close_position(self, symbol, ref_price=None) -> OrderResult:
        pos = self.positions.get(symbol)
        if not pos:
            return OrderResult(symbol=symbol, status="no_position")
        price = ref_price if ref_price is not None else pos.avg_entry
        return self.sell(symbol, pos.qty, price, reason="close")

    def close_all_positions(self) -> list:
        out = []
        for sym in list(self.positions):
            out.append(self.close_position(sym))
        return out

    def cancel_all_orders(self) -> int:
        self.cancelled += 1
        return 0  # sim has no resting orders

    def get_position(self, symbol) -> Optional[Position]:
        return self.positions.get(symbol)


# ──────────────────────────────────────────────────────────────────────────
# AlpacaBroker
# ──────────────────────────────────────────────────────────────────────────
class AlpacaBroker(Broker):
    def __init__(self, key: str, secret: str, mode: str = "paper"):
        self.rest = AlpacaREST(key, secret, mode=mode)
        self.mode = self.rest.mode

    def get_account(self) -> AccountInfo:
        from .data.alpaca_provider import parse_account
        status, body = self.rest.get("/v2/account")
        if status != 200:
            raise RuntimeError(f"account: HTTP {status} {body}")
        return parse_account(body, self.mode)

    def submit_bracket(self, symbol, qty, entry_limit, stop, target) -> OrderResult:
        body = {
            "symbol": symbol, "qty": str(int(qty)), "side": "buy", "type": "limit",
            "time_in_force": "day", "limit_price": f"{entry_limit:.2f}",
            "order_class": "bracket",
            "take_profit": {"limit_price": f"{target:.2f}"},
            "stop_loss": {"stop_price": f"{stop:.2f}"},
        }
        return self._order(body)

    def sell(self, symbol, qty, limit_price, reason="") -> OrderResult:
        body = {"symbol": symbol, "qty": str(int(qty)), "side": "sell", "type": "limit",
                "time_in_force": "day", "limit_price": f"{limit_price:.2f}"}
        return self._order(body)

    def _order(self, body: dict) -> OrderResult:
        status, resp = self.rest.post("/v2/orders", body)
        if status not in (200, 201):
            msg = resp.get("message", resp) if isinstance(resp, dict) else resp
            raise RuntimeError(f"order rejected (HTTP {status}): {msg}")
        return OrderResult(id=resp.get("id"), symbol=resp.get("symbol", body["symbol"]),
                           qty=int(float(resp.get("qty", body["qty"]))), side=body["side"],
                           status=resp.get("status", "new"),
                           filled_avg_price=float(resp["filled_avg_price"]) if resp.get("filled_avg_price") else None,
                           order_class=body.get("order_class", "simple"), raw=resp)

    def close_position(self, symbol, ref_price=None) -> OrderResult:
        status, resp = self.rest.delete(f"/v2/positions/{symbol}")
        return OrderResult(id=resp.get("id") if isinstance(resp, dict) else None,
                           symbol=symbol, side="sell",
                           status="closing" if status in (200, 207) else f"err_{status}",
                           raw=resp if isinstance(resp, dict) else {})

    def close_all_positions(self) -> list:
        # Emergency liquidation (kill switch). cancel_orders=true also pulls resting orders.
        status, resp = self.rest.delete("/v2/positions?cancel_orders=true")
        return resp if isinstance(resp, list) else [resp]

    def cancel_all_orders(self) -> int:
        status, resp = self.rest.delete("/v2/orders")
        return len(resp) if isinstance(resp, list) else 0

    def get_position(self, symbol) -> Optional[Position]:
        status, body = self.rest.get(f"/v2/positions/{symbol}")
        if status != 200 or not isinstance(body, dict):
            return None
        try:
            qty = int(float(body["qty"]))
            entry = float(body["avg_entry_price"])
            return Position(symbol=symbol, qty=qty, avg_entry=entry, stop=0.0, target=0.0)
        except (KeyError, ValueError):
            return None
