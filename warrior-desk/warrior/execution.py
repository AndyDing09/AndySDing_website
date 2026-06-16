"""Execution — the human-in-the-loop approval gate + bracket submission (§4 step 12).

Before ANY order is submitted, the full proposal is printed (so it's always on the
record) and explicit Operator approval is required: 'y' approves, anything else
rejects. In live mode the gate is mandatory and cannot be disabled. In paper mode
it may be auto-approved for unattended sims — but every proposal is still logged.

Entries are bracket orders (entry limit + protective stop + take-profit). Markets
are never used.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from .broker import Broker
from .config import Config
from .locks import auto_approve_allowed
from .logging_setup import get_logger
from .models import Position, Side, TradeProposal
from .render import render_proposal

log = get_logger("execution")

ApprovalFn = Callable[[TradeProposal], bool]


def _interactive_approval(proposal: TradeProposal) -> bool:
    ans = input("Approve this trade? (y to approve, anything else rejects) ").strip().lower()
    return ans == "y"


class ExecutionEngine:
    def __init__(self, cfg: Config, broker: Broker, journal=None, alerter=None):
        self.cfg = cfg
        self.broker = broker
        self.journal = journal
        self.alerter = alerter

    def execute(self, proposal: TradeProposal, state, now: datetime,
                approval_fn: Optional[ApprovalFn] = None, show: bool = True) -> Optional[Position]:
        """Run the approval gate and, if approved, submit the bracket order.

        Returns the opened Position, or None if rejected/skipped. The proposal's
        ``approval`` field is set to approved | approved-skipped | rejected.
        """
        if not (proposal.decision and proposal.decision.approved):
            proposal.approval = "rejected"
            log.info("Not executing %s — rejected by the gauntlet.", proposal.symbol)
            self._journal(proposal)
            return None

        if show:
            print(render_proposal(proposal))

        if auto_approve_allowed(self.cfg):
            proposal.approval = "approved"
            log.info("Paper auto-approve ON — %s approved without prompt (logged).", proposal.symbol)
        else:
            fn = approval_fn or _interactive_approval
            ok = bool(fn(proposal))
            proposal.approval = "approved" if ok else "approved-skipped"
            if not ok:
                log.info("Operator SKIPPED %s (passed the gauntlet, not taken).", proposal.symbol)
                self._journal(proposal)
                return None

        # Place the bracket: entry limit at/just above the trigger (capped by max_chase).
        entry_limit = round(proposal.entry, 2)
        try:
            result = self.broker.submit_bracket(
                proposal.symbol, proposal.shares, entry_limit, proposal.stop, proposal.target)
        except Exception as exc:
            log.error("Order submission failed for %s: %s", proposal.symbol, exc)
            proposal.approval = "rejected"
            self._journal(proposal)
            return None

        fill_price = result.filled_avg_price if result.filled_avg_price else entry_limit
        # Honour partial fills: track the qty the broker actually reports.
        filled_qty = result.qty if result.qty and result.qty > 0 else proposal.shares
        if filled_qty < proposal.shares:
            log.warning("Partial fill on %s: %d of %d shares.", proposal.symbol,
                        filled_qty, proposal.shares)
        pos = Position(
            symbol=proposal.symbol, qty=filled_qty, avg_entry=fill_price,
            stop=proposal.stop, target=proposal.target, side=Side.LONG,
            initial_qty=filled_qty, initial_risk=round(fill_price - proposal.stop, 4),
            opened_at=now, order_ids={"entry": result.id},
        )
        pos.events.append(f"{now.isoformat()} entered {filled_qty}@{fill_price} "
                          f"stop {proposal.stop} target {proposal.target} ({result.status})")
        state.record_entry(pos, now)
        log.info("ENTERED %s %s@%.2f (stop %.2f, target %.2f)",
                 proposal.symbol, filled_qty, fill_price, proposal.stop, proposal.target)
        if self.alerter is not None:
            try:
                self.alerter.entry(proposal, pos)
            except Exception as exc:
                log.warning("entry alert failed: %s", exc)
        self._journal(proposal)
        return pos

    def _journal(self, proposal: TradeProposal) -> None:
        if self.journal is not None:
            try:
                self.journal.record_proposal(proposal)
            except Exception as exc:
                log.warning("journal write failed: %s", exc)
