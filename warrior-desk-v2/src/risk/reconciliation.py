"""Reconciliation (§4.8): every 5 minutes, local state vs the account endpoint.

A mismatch (position the broker has that we don't, or vice versa; quantity
drift; equity drift beyond tolerance) freezes new entries, logs an incident,
and alerts. Trading through a state mismatch is how a paper bug becomes an
untrusted journal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..models import Incident, Position


@dataclass
class ReconcileResult:
    ok: bool
    mismatches: list[str] = field(default_factory=list)


def reconcile(local: list[Position], broker_positions: list[Position],
              local_equity: float, broker_equity: float,
              equity_tolerance_pct: float = 0.02) -> ReconcileResult:
    res = ReconcileResult(ok=True)
    lmap = {p.symbol: p for p in local}
    bmap = {p.symbol: p for p in broker_positions}

    for sym in bmap.keys() - lmap.keys():
        res.mismatches.append(f"broker holds {sym} but local state does not")
    for sym in lmap.keys() - bmap.keys():
        res.mismatches.append(f"local state holds {sym} but broker does not")
    for sym in lmap.keys() & bmap.keys():
        if lmap[sym].qty != bmap[sym].qty:
            res.mismatches.append(
                f"{sym} qty drift: local {lmap[sym].qty} vs broker {bmap[sym].qty}")

    if broker_equity > 0:
        drift = abs(local_equity - broker_equity) / broker_equity
        if drift > equity_tolerance_pct:
            res.mismatches.append(
                f"equity drift {drift:.1%}: local {local_equity:.2f} vs broker {broker_equity:.2f}")

    res.ok = not res.mismatches
    return res


class Reconciler:
    def __init__(self, breakers, store=None, alert=None):
        self.breakers = breakers
        self.store = store
        self.alert = alert

    def run(self, local: list[Position], broker_positions: list[Position],
            local_equity: float, broker_equity: float, now: datetime) -> ReconcileResult:
        res = reconcile(local, broker_positions, local_equity, broker_equity)
        if not res.ok:
            self.breakers.freeze("reconciliation")
            detail = "; ".join(res.mismatches)
            if self.store is not None:
                self.store.write_incident(Incident(ts=now, kind="reconcile_mismatch",
                                                   detail=detail))
            if self.alert is not None:
                self.alert("RECONCILE", f"state mismatch — entries frozen: {detail}")
        return res
