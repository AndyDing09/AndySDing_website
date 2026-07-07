"""The one path a signal must walk to become an order (§2.3, §7.1).

    strategy Signal (proposed)
      → score gate      (< skip_below → skipped:score, 60–79 half size, ≥80 full)
      → 2:1 rr gate     (unconditional; skipped:insufficient_rr)
      → circuit breakers(rejected:breaker:<which>)
      → sizing + spread (rejected:<gate>, halved when the score says so)

Every outcome — pass or fail — is returned for journaling. There is no second
path; execution accepts only signals that exited this function tradeable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ..config import Config
from ..models import Regime, Signal, SignalStatus
from ..scanners.regime import required_score
from .circuit_breakers import CircuitBreakers
from .rr_gate import rr_gate
from .sizing import SizingDecision, size_signal


@dataclass
class GateOutcome:
    signal: Signal
    tradeable: bool
    sizing: Optional[SizingDecision] = None
    half_size: bool = False


def run_gates(signal: Signal, cfg: Config, breakers: CircuitBreakers,
              equity: float, now: datetime, regime: Regime | None = None,
              score: float | None = None) -> GateOutcome:
    if score is not None:
        signal.score = score
    reg = regime if regime is not None else signal.regime

    # 1. Quality-score gate (§7.1); in chop the bar rises (§3.3).
    need = required_score(cfg.score.skip_below, reg, cfg.regime.chop_score_bump)
    if signal.score < need:
        signal.status = SignalStatus.SKIPPED
        signal.status_reason = f"score:{signal.score:.0f}<{need}"
        return GateOutcome(signal, False)
    half = signal.score < cfg.score.full_size_at

    # 2. The unconditional 2:1 gate.
    if not rr_gate(signal, cfg.risk.min_reward_risk):
        return GateOutcome(signal, False)

    # 3. Circuit breakers / freezes / entry cutoff.
    if not breakers.gate(signal, now):
        return GateOutcome(signal, False)

    # 4. Sizing, notional cap, spread — half size for 60–79 scores.
    sizing = size_signal(signal, cfg.risk, equity)
    if not sizing.ok:
        return GateOutcome(signal, False, sizing)
    if half and sizing.shares > 1:
        sizing.shares //= 2
        sizing.notional = sizing.shares * signal.entry
        sizing.risk_usd = sizing.shares * (signal.entry - signal.stop)
        signal.shares = sizing.shares

    return GateOutcome(signal, True, sizing, half_size=half)
