"""Broker seam: one interface, two implementations.

- ``SimBroker``: deterministic slippage-honest fills for replay and tests.
- ``AlpacaPaperBroker``: real bracket orders on the PAPER endpoint via alpaca-py.
  ``paper=True`` is hard-wired and the config layer already refused any
  non-paper URL; there is no code path to a live endpoint (§1.1, tested).

LONG-ONLY: ``submit_bracket`` asserts side == buy structurally — there is no
sell-short method on the interface at all.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from ..config import Config
from ..models import Fill, Position, Quote, SetupName, Signal
from .slippage import entry_fill_price, stop_fill_price, target_fill_price

log = logging.getLogger("wd.broker")


class Broker(ABC):
    @abstractmethod
    def submit_bracket(self, signal: Signal, now: datetime,
                       quote: Optional[Quote]) -> Optional[Position]: ...

    @abstractmethod
    def exit_position(self, pos: Position, reason: str, now: datetime,
                      quote: Optional[Quote]) -> Fill: ...

    @abstractmethod
    def replace_stop(self, pos: Position, new_stop: float) -> None: ...

    @abstractmethod
    def cancel_all_orders(self) -> int: ...

    @abstractmethod
    def close_all_positions(self) -> list[str]: ...

    @abstractmethod
    def account_equity(self) -> float: ...

    @abstractmethod
    def open_positions(self) -> list[Position]: ...

    def remote_positions(self) -> list[Position]:
        """The BROKER's independent view, for reconciliation (§4.8). Defaults to
        the local view for sims; the Alpaca broker queries the API."""
        return self.open_positions()


class SimBroker(Broker):
    """Deterministic fills with the §7.2 slippage model applied on both sides."""

    def __init__(self, cfg: Config, equity: float | None = None):
        self.cfg = cfg
        self.equity = equity if equity is not None else cfg.risk.account_equity_fallback
        self.positions: dict[str, Position] = {}
        self.fills: list[Fill] = []
        self.cancelled = 0

    def submit_bracket(self, signal: Signal, now: datetime,
                       quote: Optional[Quote]) -> Optional[Position]:
        assert signal.stop < signal.entry < signal.target, "long bracket structure"
        ask = quote.ask if quote else signal.entry
        spread_pct = quote.spread_pct if quote else signal.spread_pct_at_signal
        fill_px = entry_fill_price(ask, spread_pct, self.cfg.slippage,
                                   self.cfg.risk.max_spread_pct)
        pos = Position(symbol=signal.symbol, qty=signal.shares, entry=fill_px,
                       stop=signal.stop, target=signal.target, opened_at=now,
                       signal_ts=signal.ts, setup=signal.setup)
        self.positions[signal.symbol] = pos
        self.fills.append(Fill(ts=now, symbol=signal.symbol, side="buy",
                               qty=signal.shares, price=fill_px,
                               intended_price=signal.entry))
        return pos

    def exit_position(self, pos: Position, reason: str, now: datetime,
                      quote: Optional[Quote]) -> Fill:
        bid = quote.bid if quote else pos.stop
        spread_pct = quote.spread_pct if quote else 0.0
        if reason == "target":
            px = target_fill_price(pos.target)
        else:                                   # stop / trail / time_stop / kill
            px = stop_fill_price(bid, spread_pct, self.cfg.slippage,
                                 self.cfg.risk.max_spread_pct)
        self.positions.pop(pos.symbol, None)
        fill = Fill(ts=now, symbol=pos.symbol, side="sell", qty=pos.qty, price=px,
                    intended_price=pos.target if reason == "target" else pos.stop)
        self.fills.append(fill)
        return fill

    def replace_stop(self, pos: Position, new_stop: float) -> None:
        # NEVER widen: a stop may only ratchet toward price.
        if new_stop > pos.stop:
            pos.stop = new_stop

    def cancel_all_orders(self) -> int:
        self.cancelled += 1
        return 0

    def close_all_positions(self) -> list[str]:
        syms = list(self.positions)
        self.positions.clear()
        return syms

    def account_equity(self) -> float:
        return self.equity

    def open_positions(self) -> list[Position]:
        return list(self.positions.values())


class AlpacaPaperBroker(Broker):
    """Real paper execution. Lazy client; constructed only by run_session."""

    def __init__(self, cfg: Config, clients):
        self.cfg = cfg
        self.clients = clients
        self._local: dict[str, Position] = {}

    def submit_bracket(self, signal: Signal, now: datetime,
                       quote: Optional[Quote]) -> Optional[Position]:
        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import (LimitOrderRequest, StopLossRequest,
                                             TakeProfitRequest)
        assert signal.stop < signal.entry < signal.target, "long bracket structure"
        req = LimitOrderRequest(
            symbol=signal.symbol, qty=signal.shares, side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY, limit_price=round(signal.entry, 2),
            # order_class must be EXPLICIT: alpaca-py does not infer BRACKET from
            # the legs, and an entry without its protective stop attached is the
            # single worst failure mode this system can have.
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round(signal.target, 2)),
            stop_loss=StopLossRequest(stop_price=round(signal.stop, 2)),
        )
        order = self.clients.trading.submit_order(req)
        pos = Position(symbol=signal.symbol, qty=signal.shares, entry=signal.entry,
                       stop=signal.stop, target=signal.target, opened_at=now,
                       signal_ts=signal.ts, setup=signal.setup)
        self._local[signal.symbol] = pos
        log.info("bracket submitted %s x%d entry=%.2f stop=%.2f target=%.2f (%s)",
                 signal.symbol, signal.shares, signal.entry, signal.stop,
                 signal.target, getattr(order, "id", "?"))
        return pos

    def _cancel_symbol_orders(self, symbol: str) -> None:
        """Cancel the symbol's open orders (bracket legs) — Alpaca rejects a
        close while a child order reserves the shares."""
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest
        try:
            orders = self.clients.trading.get_orders(
                GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])) or []
            for o in orders:
                try:
                    self.clients.trading.cancel_order_by_id(o.id)
                except Exception as exc:
                    log.warning("cancel leg %s/%s failed: %s", symbol, o.id, exc)
        except Exception as exc:
            log.warning("could not list open orders for %s: %s", symbol, exc)

    def exit_position(self, pos: Position, reason: str, now: datetime,
                      quote: Optional[Quote]) -> Fill:
        self._cancel_symbol_orders(pos.symbol)
        px = (quote.bid if quote else pos.stop)
        try:
            self.clients.trading.close_position(pos.symbol)
        except Exception as exc:
            # Common benign case: a bracket leg already filled server-side and
            # the position is gone. Verify against the broker before treating
            # the exit as done; re-raise anything else.
            held = {p.symbol for p in (self.clients.trading.get_all_positions() or [])}
            if pos.symbol in held:
                raise
            log.info("%s already closed server-side (bracket leg filled): %s",
                     pos.symbol, exc)
        self._local.pop(pos.symbol, None)
        return Fill(ts=now, symbol=pos.symbol, side="sell", qty=pos.qty, price=px,
                    intended_price=pos.target if reason == "target" else pos.stop)

    def drop_local(self, symbol: str) -> None:
        """Forget a position our books hold but the broker no longer does."""
        self._local.pop(symbol, None)

    def replace_stop(self, pos: Position, new_stop: float) -> None:
        if new_stop > pos.stop:
            pos.stop = new_stop   # local ratchet; the bracket's stop leg is replaced
            try:
                from alpaca.trading.enums import OrderType, QueryOrderStatus
                from alpaca.trading.requests import GetOrdersRequest, ReplaceOrderRequest
                orders = self.clients.trading.get_orders(
                    GetOrdersRequest(status=QueryOrderStatus.OPEN,
                                     symbols=[pos.symbol], nested=True)) or []
                # Compare ENUMS: str(OrderType.STOP) is 'OrderType.STOP' on 3.11,
                # so any endswith('stop') string check silently never matches.
                stop_legs = [o for o in self._flatten_orders(orders)
                             if getattr(o, "type", None) in (OrderType.STOP, OrderType.STOP_LIMIT)]
                if not stop_legs:
                    log.warning("no open stop leg found for %s — broker-side stop NOT moved",
                                pos.symbol)
                for o in stop_legs:
                    self.clients.trading.replace_order_by_id(
                        o.id, ReplaceOrderRequest(stop_price=round(new_stop, 2)))
                    log.info("stop leg %s moved to %.2f", pos.symbol, new_stop)
            except Exception as exc:
                log.error("stop replace failed for %s: %s", pos.symbol, exc)

    @staticmethod
    def _flatten_orders(orders) -> list:
        """Bracket children arrive nested under the parent's .legs."""
        flat = []
        for o in orders:
            flat.append(o)
            flat.extend(getattr(o, "legs", None) or [])
        return flat

    def cancel_all_orders(self) -> int:
        cancelled = self.clients.trading.cancel_orders()
        return len(cancelled) if cancelled else 0

    def close_all_positions(self) -> list[str]:
        res = self.clients.trading.close_all_positions(cancel_orders=True)
        return [getattr(r, "symbol", "?") for r in (res or [])]

    def account_equity(self) -> float:
        acct = self.clients.trading.get_account()
        return float(acct.equity)

    def open_positions(self) -> list[Position]:
        return list(self._local.values())

    def remote_positions(self) -> list[Position]:
        """Query Alpaca for its actual open positions — reconciliation must
        compare our books against the BROKER's, not our books against themselves."""
        from datetime import timezone as _tz
        out: list[Position] = []
        for p in (self.clients.trading.get_all_positions() or []):
            local = self._local.get(p.symbol)
            out.append(Position(
                symbol=p.symbol, qty=int(float(p.qty)),
                entry=float(p.avg_entry_price),
                stop=local.stop if local else 0.0,
                target=local.target if local else 0.0,
                opened_at=local.opened_at if local else datetime.now(_tz.utc),
                signal_ts=local.signal_ts if local else datetime.now(_tz.utc),
                setup=local.setup if local else SetupName.GAP_AND_GO))
        return out
