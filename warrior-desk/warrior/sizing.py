"""Position sizing (Section 2.6).

    shares = floor( max_risk_per_trade / stop_distance )

then clamp by available buying power, max_position_notional, and
max_pct_account_per_trade, and apply the grade size factor (A = full, B = scaled
down, C/REJECT = 0). Always take the *smallest* share count the constraints
allow — never exceed risk-per-trade to "make the setup work".
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .models import Grade, floor_int


@dataclass
class SizingResult:
    shares: int
    risk_dollars: float
    position_notional: float
    position_pct: float
    binding_constraint: str        # which limit decided the final size
    grade_factor: float


def grade_factor(cfg: Config, grade: Grade) -> float:
    if grade == Grade.A:
        return 1.0
    if grade == Grade.B:
        return cfg.risk.b_grade_size_factor
    return 0.0  # C / REJECT — not tradeable


def size_position(
    cfg: Config,
    entry: float,
    stop_distance: float,
    account_equity: float,
    buying_power: float,
    grade: Grade,
) -> SizingResult:
    r = cfg.risk
    if stop_distance <= 0 or entry <= 0:
        return SizingResult(0, 0.0, 0.0, 0.0, "invalid_inputs", 0.0)

    gf = grade_factor(cfg, grade)
    if gf <= 0:
        return SizingResult(0, 0.0, 0.0, 0.0, "grade_not_tradeable", gf)

    # The risk-based share count is the starting point.
    by_risk = r.max_risk_per_trade / stop_distance
    candidates = {"risk_per_trade": by_risk}

    # Clamp by capital constraints.
    if entry > 0:
        candidates["max_position_notional"] = r.max_position_notional / entry
        if buying_power > 0:
            candidates["buying_power"] = buying_power / entry
        if account_equity > 0:
            candidates["max_pct_account"] = (r.max_pct_account_per_trade * account_equity) / entry

    # Grade scales the whole thing down (B-grade gets less size).
    raw_min = min(candidates.values())
    binding = min(candidates, key=candidates.get)
    shares = floor_int(raw_min * gf)

    risk_dollars = round(shares * stop_distance, 2)
    notional = round(shares * entry, 2)
    pct = round(notional / account_equity, 6) if account_equity > 0 else 0.0
    return SizingResult(shares, risk_dollars, notional, pct, binding, gf)
