"""The journal (§6): log every signal, taken or not; every fill; every close.

The float band, catalyst, regime, spread, feed and score ride along on each row
because those are the cuts that later say WHEN and WHAT this strategy trades
best. The skipped-signal audit simulates outcomes of signals the gates refused,
so the gates themselves are measured — data over vibes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ..data.store import Store
from ..models import (Bar, Fill, Position, Signal, SignalStatus, TradeRecord)


class Journal:
    def __init__(self, store: Store):
        self.store = store

    # ── writers ──
    def record_signal(self, signal: Signal) -> None:
        """Every signal is recorded, whatever its status (§6: taken or not)."""
        self.store.write_signal(signal)

    def record_close(self, pos: Position, entry_fill: Fill, exit_fill: Fill,
                     signal: Signal, exit_reason: str, now: datetime) -> TradeRecord:
        risk_ps = max(1e-9, entry_fill.price - pos.stop if not pos.breakeven_moved
                      else entry_fill.price - signal.stop)
        # realized R is measured against the ORIGINAL planned risk (entry−stop at
        # signal time) — moving the stop later changes outcomes, not the unit.
        planned_risk = max(1e-9, signal.entry - signal.stop)
        pnl = (exit_fill.price - entry_fill.price) * pos.qty
        realized_r = (exit_fill.price - entry_fill.price) / planned_risk
        slippage = (entry_fill.slippage + exit_fill.slippage) * pos.qty
        tr = TradeRecord(
            signal_ts=signal.ts, closed_at=now, symbol=pos.symbol, setup=pos.setup,
            entry_intended=signal.entry, entry_fill=entry_fill.price,
            exit_fill=exit_fill.price, stop=signal.stop, target=signal.target,
            qty=pos.qty, realized_r=round(realized_r, 4), pnl_usd=round(pnl, 2),
            mae=round(pos.mae, 4), mfe=round(pos.mfe, 4),
            hold_seconds=(now - pos.opened_at).total_seconds(),
            exit_reason=exit_reason, slippage_usd=round(slippage, 2),
            regime=signal.regime, catalyst_type=signal.catalyst_type,
            float_band=signal.float_band, feed=signal.feed)
        self.store.write_trade(tr)
        return tr


# ── skipped-signal audit (§6) ──
@dataclass
class SkippedOutcome:
    symbol: str
    setup: str
    reason: str
    would_have: str          # "target" | "stop" | "open"
    would_r: float


def simulate_skipped(signal_row: dict, later_bars: list[Bar]) -> SkippedOutcome:
    """Walk the bars after a skipped signal: which side would have hit first?
    Same pessimistic same-bar rule as live management."""
    entry, stop, target = (float(signal_row["entry"]), float(signal_row["stop"]),
                           float(signal_row["target"]))
    risk = max(1e-9, entry - stop)
    filled = False
    for b in later_bars:
        if not filled:
            if b.high >= entry:
                filled = True
            else:
                continue
        if b.low <= stop:
            return SkippedOutcome(signal_row["symbol"], signal_row["setup"],
                                  signal_row["status_reason"], "stop", -1.0)
        if b.high >= target:
            return SkippedOutcome(signal_row["symbol"], signal_row["setup"],
                                  signal_row["status_reason"], "target",
                                  round((target - entry) / risk, 2))
    return SkippedOutcome(signal_row["symbol"], signal_row["setup"],
                          signal_row["status_reason"], "open", 0.0)


def audit_skipped(store: Store, day_start: datetime, day_end: datetime) -> list[SkippedOutcome]:
    """Nightly (§6): simulate every skipped/rejected signal against stored bars.
    If insufficient_rr skips keep 'winning', report whether their R would have
    been sub-2 — that's the gate filtering low-quality trades correctly — or
    not. Report it either way."""
    out: list[SkippedOutcome] = []
    for row in store.signals_between(day_start, day_end):
        if not (str(row["status"]).startswith("skipped")
                or str(row["status"]) == SignalStatus.SKIPPED.value
                or str(row["status"]) == SignalStatus.REJECTED.value):
            continue
        bars = [Bar(symbol=r[0], ts=r[1], open=r[2], high=r[3], low=r[4], close=r[5],
                    volume=r[6], feed=r[7])
                for r in store.bars(row["symbol"], since=row["ts"])]
        out.append(simulate_skipped(row, bars))
    return out
