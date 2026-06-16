"""The hard kill switch (Section 0).

A single action that flattens all open positions (at market in paper / via the
safest available exit in live), cancels all open orders, and halts the agent for
the rest of the session. This is the one place a market-style liquidation is
allowed — it is an emergency stop, not a trading decision.

Every step is independently guarded: a failure cancelling orders must not stop us
from flattening positions, and vice-versa.
"""

from __future__ import annotations

from typing import Optional, Protocol

from .logging_setup import get_logger
from .state import State

log = get_logger("kill")


class Broker(Protocol):
    def cancel_all_orders(self) -> int: ...
    def close_all_positions(self) -> list: ...


def kill_switch(state: State, broker: Optional[Broker] = None,
                reason: str = "manual kill switch") -> dict:
    """Flatten + cancel + halt. Returns a report dict; never raises."""
    report = {"reason": reason, "orders_cancelled": None, "positions_closed": None, "errors": []}

    if broker is not None:
        try:
            report["orders_cancelled"] = broker.cancel_all_orders()
            log.warning("KILL: cancelled %s open orders.", report["orders_cancelled"])
        except Exception as exc:
            report["errors"].append(f"cancel_all_orders: {exc}")
            log.error("KILL: cancel_all_orders failed: %s", exc)

        try:
            closed = broker.close_all_positions()
            report["positions_closed"] = closed
            log.warning("KILL: submitted flatten for %s positions.", len(closed) if closed else 0)
        except Exception as exc:
            report["errors"].append(f"close_all_positions: {exc}")
            log.error("KILL: close_all_positions failed: %s", exc)
    else:
        report["errors"].append("no broker bound; halting state only (no live flatten possible)")
        log.warning("KILL: no broker bound — halting the session in state only.")

    # Always halt the session, even if the broker calls failed — we never want to
    # keep trading after a kill was requested.
    try:
        state.halt(f"KILL: {reason}")
    except Exception as exc:
        report["errors"].append(f"state.halt: {exc}")

    return report
