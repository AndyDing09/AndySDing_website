"""Setup quality score 0–100 (§7.1).

Weighted sum of: rvol percentile, float tightness, catalyst strength, pullback
cleanliness, distance-to-9EMA, spread, obviousness rank. Weights live in config.
Scores gate sizing downstream: < skip_below → skip, < full_size_at → half size,
else full size. Dilution risk caps the score at ``dilution_cap`` (§7.8) which by
construction lands in the half-size-or-skip band.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import ScoreCfg
from .data.news import catalyst_strength
from .models import Candidate, Signal


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass
class ScoreInputs:
    rvol: float                       # today's relative volume
    float_shares: float | None
    float_unverified: bool
    catalyst: float                   # 0..1 from catalyst_strength()
    retrace_pct: float | None         # pullback depth, 0..1 (None = not a pullback setup)
    pullback_volume_declining: bool
    dist_to_9ema_pct: float | None    # |price − ema9| / price
    spread_pct: float
    obviousness_rank: int             # 1 = the obvious one


def subscores(i: ScoreInputs) -> dict[str, float]:
    """Each component normalized to 0..1; the shape comments say why."""
    s: dict[str, float] = {}
    # rvol: 5x is the floor (0.5 credit), 20x+ is elite.
    s["rvol_percentile"] = _clamp((i.rvol - 5.0) / 15.0 * 0.5 + 0.5) if i.rvol >= 5 else _clamp(i.rvol / 10.0)
    # float: <10M full credit, 20M = 0.4, unknown/unverified penalized.
    if i.float_shares is None:
        s["float_tightness"] = 0.2
    else:
        s["float_tightness"] = _clamp(1.0 - (i.float_shares - 5e6) / 25e6)
        if i.float_unverified:
            s["float_tightness"] *= 0.6
    s["catalyst_strength"] = _clamp(i.catalyst)
    # pullback cleanliness: shallow retrace on declining volume is the textbook flag.
    if i.retrace_pct is None:
        s["pullback_cleanliness"] = 0.5           # setup type without a pullback leg
    else:
        s["pullback_cleanliness"] = _clamp(1.0 - i.retrace_pct / 0.5)
        if i.pullback_volume_declining:
            s["pullback_cleanliness"] = _clamp(s["pullback_cleanliness"] + 0.2)
    # distance to 9-EMA: entries near the EMA risk less to structure.
    if i.dist_to_9ema_pct is None:
        s["dist_to_9ema"] = 0.5
    else:
        s["dist_to_9ema"] = _clamp(1.0 - i.dist_to_9ema_pct / 0.05)
    # spread: 0 → 1.0, at the 1% reject line → 0.
    s["spread"] = _clamp(1.0 - i.spread_pct / 0.01)
    # obviousness: rank 1 full credit, decaying — the crowd trades the obvious one.
    s["obviousness"] = _clamp(1.0 - (i.obviousness_rank - 1) * 0.2) if i.obviousness_rank else 0.5
    return s


def score(i: ScoreInputs, cfg: ScoreCfg, dilution_risk: bool = False) -> float:
    parts = subscores(i)
    w = cfg.weights
    total = 100.0 * (
        parts["rvol_percentile"] * w.rvol_percentile
        + parts["float_tightness"] * w.float_tightness
        + parts["catalyst_strength"] * w.catalyst_strength
        + parts["pullback_cleanliness"] * w.pullback_cleanliness
        + parts["dist_to_9ema"] * w.dist_to_9ema
        + parts["spread"] * w.spread
        + parts["obviousness"] * w.obviousness
    ) / (w.rvol_percentile + w.float_tightness + w.catalyst_strength
         + w.pullback_cleanliness + w.dist_to_9ema + w.spread + w.obviousness)
    if dilution_risk:
        total = min(total, float(cfg.dilution_cap))   # §7.8: auto half-size-or-skip
    return round(total, 1)


def score_signal(sig: Signal, cand: Candidate, cfg: ScoreCfg,
                 retrace_pct: float | None = None,
                 pullback_volume_declining: bool = False,
                 dist_to_9ema_pct: float | None = None,
                 dilution_risk: bool = False) -> float:
    inputs = ScoreInputs(
        rvol=cand.rvol, float_shares=cand.float_shares,
        float_unverified=cand.float_unverified,
        catalyst=catalyst_strength(cand.catalyst_type),
        retrace_pct=retrace_pct,
        pullback_volume_declining=pullback_volume_declining,
        dist_to_9ema_pct=dist_to_9ema_pct,
        spread_pct=sig.spread_pct_at_signal,
        obviousness_rank=cand.obviousness_rank,
    )
    return score(inputs, cfg, dilution_risk=dilution_risk or cand.dilution_flag)
