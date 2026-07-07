"""Checkpoint: report validation (§5) — before any performance report is shown
to a human. Verifies the aggregation logic against raw rows:

- trades sum to the daily P&L the report claims,
- every R-multiple recomputes from raw entry/stop/exit within tolerance,
- no double-counted fills (one close per signal_ts+symbol).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..data.store import Store


@dataclass
class ReportValidation:
    ok: bool
    checks: int = 0
    failures: list[str] = field(default_factory=list)


def validate_trades(trades: list[dict], claimed_day_pnl: float | None = None,
                    r_tolerance: float = 0.02) -> ReportValidation:
    v = ReportValidation(ok=True)

    # 1. Sum check.
    v.checks += 1
    total = round(sum(float(t["pnl_usd"]) for t in trades), 2)
    if claimed_day_pnl is not None and abs(total - round(claimed_day_pnl, 2)) > 0.01:
        v.failures.append(f"day P&L mismatch: rows sum to {total} vs claimed {claimed_day_pnl}")

    # 2. R recomputes from raw entry/stop/exit.
    for t in trades:
        v.checks += 1
        planned_risk = float(t["entry_intended"]) - float(t["stop"])
        if planned_risk <= 0:
            v.failures.append(f"{t['symbol']}: non-positive planned risk in raw row")
            continue
        r = (float(t["exit_fill"]) - float(t["entry_fill"])) / planned_risk
        if abs(r - float(t["realized_r"])) > r_tolerance:
            v.failures.append(
                f"{t['symbol']}: realized_r {float(t['realized_r']):.3f} does not recompute "
                f"({r:.3f}) from raw entry/stop/exit")
        # pnl consistency with qty
        v.checks += 1
        pnl = (float(t["exit_fill"]) - float(t["entry_fill"])) * int(t["qty"])
        if abs(pnl - float(t["pnl_usd"])) > 0.05:
            v.failures.append(f"{t['symbol']}: pnl {t['pnl_usd']} != (exit-entry)*qty {pnl:.2f}")

    # 3. Double-counting.
    v.checks += 1
    keys = [(str(t["signal_ts"]), t["symbol"]) for t in trades]
    if len(keys) != len(set(keys)):
        v.failures.append("duplicate close rows detected (same signal_ts+symbol)")

    v.ok = not v.failures
    return v


def run(store: Store, day_start: datetime, day_end: datetime,
        reports_dir: str | Path = "reports") -> ReportValidation:
    trades = store.trades_between(day_start, day_end)
    res = validate_trades(trades)
    out = Path(reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"validate_report_{day_start.date().isoformat()}.json").write_text(
        json.dumps({"schema": 1, "ok": res.ok, "checks": res.checks,
                    "failures": res.failures}, indent=2))
    if not res.ok:
        print(f"WARNING: report validation failed — {len(res.failures)} issue(s).")
    return res
