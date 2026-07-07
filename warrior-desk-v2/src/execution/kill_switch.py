"""Kill switch (§7.7).

``warrior-desk halt`` flattens all positions, cancels all orders, and locks new
entries until ``warrior-desk resume``. The lock is a file so it survives process
restarts, and the same mechanism is triggered automatically by a reconciliation
mismatch (§4.8). Each step is independently guarded: a cancel failure must never
prevent the flatten, and nothing prevents the lock.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("wd.kill")

LOCK_FILE = Path("data/HALTED")


class KillSwitch:
    def __init__(self, broker, breakers, lock_path: Path = LOCK_FILE):
        self.broker = broker
        self.breakers = breakers
        self.lock_path = lock_path

    def is_halted(self) -> bool:
        return self.lock_path.exists()

    def halt(self, reason: str = "manual halt") -> dict:
        report: dict = {"reason": reason, "cancelled": None, "flattened": None, "errors": []}
        try:
            report["cancelled"] = self.broker.cancel_all_orders()
        except Exception as exc:
            report["errors"].append(f"cancel_all_orders: {exc}")
            log.error("halt: cancel failed: %s", exc)
        try:
            report["flattened"] = self.broker.close_all_positions()
        except Exception as exc:
            report["errors"].append(f"close_all_positions: {exc}")
            log.error("halt: flatten failed: %s", exc)
        # The lock always engages, even if the broker misbehaved above.
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text(
            f"{datetime.now(timezone.utc).isoformat()} {reason}\n", encoding="utf-8")
        self.breakers.freeze(f"kill_switch:{reason}")
        log.warning("KILL SWITCH: %s — entries locked until resume", reason)
        return report

    def resume(self) -> None:
        self.lock_path.unlink(missing_ok=True)
        self.breakers.unfreeze()
        log.warning("kill switch released — entries unlocked")
