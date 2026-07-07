"""Checkpoint: weekly statistics (§5) — the /data:statistical-analysis fallback.

Computes win rate with a 95% Wilson interval, average win/loss in R, profit
factor, expectancy per trade, and per-setup breakdowns. Provides a two-proportion
z-test so a proposed threshold change is judged on evidence instead of eyeballing
five trades. Any metric with n < min_sample is flagged "insufficient sample — do
not conclude" and CANNOT justify a parameter change (CLAUDE.md rule).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from math import erf, sqrt
from pathlib import Path

from ..data.store import Store
from ..journal.expectancy import compute, cut_by


@dataclass
class TwoProportionResult:
    p1: float
    p2: float
    n1: int
    n2: int
    z: float
    p_value: float
    significant_at_5pct: bool
    conclusion: str


def two_proportion_test(wins1: int, n1: int, wins2: int, n2: int) -> TwoProportionResult:
    """H0: the two win rates are equal. Two-sided z-test on proportions."""
    if n1 == 0 or n2 == 0:
        return TwoProportionResult(0, 0, n1, n2, 0.0, 1.0, False,
                                   "no data in one group — do not conclude")
    p1, p2 = wins1 / n1, wins2 / n2
    pooled = (wins1 + wins2) / (n1 + n2)
    se = sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return TwoProportionResult(p1, p2, n1, n2, 0.0, 1.0, False,
                                   "zero variance — do not conclude")
    z = (p1 - p2) / se
    p_value = 2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2))))
    sig = p_value < 0.05
    concl = ("difference is statistically significant at 5%"
             if sig else "difference is NOT significant — do not change the threshold on this")
    if min(n1, n2) < 30:
        concl += " (insufficient sample — do not conclude)"
        sig = False
    return TwoProportionResult(round(p1, 4), round(p2, 4), n1, n2, round(z, 3),
                               round(p_value, 4), sig, concl)


def weekly_stats(store: Store, min_sample_n: int = 30) -> dict:
    trades = store.last_trades(1000)
    overall = compute(trades, min_sample_n)
    per_setup = {k: asdict(v) for k, v in cut_by(trades, "setup", min_sample_n).items()}
    per_regime = {k: asdict(v) for k, v in cut_by(trades, "regime", min_sample_n).items()}
    per_float = {k: asdict(v) for k, v in cut_by(trades, "float_band", min_sample_n).items()}
    per_catalyst = {k: asdict(v) for k, v in cut_by(trades, "catalyst_type", min_sample_n).items()}
    return {
        "schema": 1,
        "overall": asdict(overall),
        "per_setup": per_setup,
        "per_regime": per_regime,
        "per_float_band": per_float,
        "per_catalyst": per_catalyst,
        "rule": ("Parameter changes require this report as justification, cited in the "
                 "commit message. Metrics flagged insufficient_sample cannot justify a change."),
    }


def run(store: Store, now: datetime, reports_dir: str | Path = "reports",
        min_sample_n: int = 30) -> Path:
    out = Path(reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"stats_weekly_{now.strftime('%Y%m%d_%H%M%S')}.json"
    dest.write_text(json.dumps(weekly_stats(store, min_sample_n), indent=2, default=str))
    return dest
