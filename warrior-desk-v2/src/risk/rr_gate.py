"""The 2:1 gate (§1.3) — unconditional, no override flag, none will be added.

If (target − entry) < min_rr × (entry − stop) the signal is marked
``skipped:insufficient_rr`` and can never become an order. The config floor is
itself validated ≥ 2.0, so no configuration can weaken this below the spec.
"""

from __future__ import annotations

from ..models import Signal, SignalStatus

SKIP_REASON = "insufficient_rr"


# Float tolerance only: a target deliberately placed at exactly 2R must not be
# rejected over 1e-13 of representation error. This is NOT a softening of the
# gate — anything measurably below min_rr still dies here.
_EPS = 1e-9


def rr_gate(signal: Signal, min_rr: float) -> bool:
    """True = passes. False = signal mutated to skipped:insufficient_rr."""
    risk = signal.entry - signal.stop
    reward = signal.target - signal.entry
    if risk <= 0 or reward + _EPS < min_rr * risk:
        signal.status = SignalStatus.SKIPPED
        signal.status_reason = SKIP_REASON
        return False
    return True
