"""Stock selection — the four criteria (Section 2.1) and watchlist ranking.

A candidate must meet ALL FOUR: low float (<100M, ideal <20M), a strong daily
chart, high relative volume (≥2×), and a real catalyst. Float we often can't
verify for free — when unknown we mark it *unverified* and downgrade rather than
pretend. A clean technical breakout with no news is allowed but scored lower.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from .config import Config
from .data.provider import FloatInfo
from .indicators import ema_last
from .models import Bar, Candidate, Catalyst


@dataclass
class CriterionEval:
    name: str
    passed: bool
    hard_fail: bool          # a True here ends the gauntlet
    score: float
    detail: str
    metrics: dict = field(default_factory=dict)


def float_criterion(fi: FloatInfo, cfg: Config) -> CriterionEval:
    sel = cfg.selection
    if not fi.known:
        return CriterionEval(
            "low_float", passed=True, hard_fail=False, score=0.0,
            detail="float UNVERIFIED (no source) — setup downgraded, not rejected",
            metrics={"float": None, "float_verified": False})
    shares = fi.shares
    if shares > sel.max_float:
        return CriterionEval(
            "low_float", passed=False, hard_fail=True, score=0.0,
            detail=f"float {shares/1e6:.1f}M > {sel.max_float/1e6:.0f}M cap",
            metrics={"float": shares, "float_verified": fi.verified})
    score = 2.0 if shares <= sel.ideal_float else 1.0
    return CriterionEval(
        "low_float", passed=True, hard_fail=False, score=score,
        detail=f"float {shares/1e6:.1f}M ({'ideal <20M' if score == 2 else 'ok <100M'})",
        metrics={"float": shares, "float_verified": fi.verified})


def rvol_criterion(rvol: float, cfg: Config) -> CriterionEval:
    minr = cfg.selection.min_rvol
    if rvol < minr:
        return CriterionEval(
            "rvol", passed=False, hard_fail=True, score=0.0,
            detail=f"RVOL {rvol:.1f}x < {minr:.1f}x — not enough unusual interest",
            metrics={"rvol": rvol})
    score = 2.0 if rvol >= 5 else (1.0 if rvol >= 3 else 0.5)
    return CriterionEval(
        "rvol", passed=True, hard_fail=False, score=score,
        detail=f"RVOL {rvol:.1f}x (heavy volume = more eyes)",
        metrics={"rvol": rvol})


def daily_strength(daily_bars: Sequence[Bar], price: float) -> CriterionEval:
    """Price above its key moving averages on the daily, no obvious overhead wall."""
    closes = [b.close for b in daily_bars]
    if len(closes) < 20:
        return CriterionEval(
            "daily_strength", passed=True, hard_fail=False, score=0.0,
            detail="insufficient daily history — strength unverified",
            metrics={})
    e9 = ema_last(closes, 9)
    e20 = ema_last(closes, 20)
    e200 = ema_last(closes, 200) if len(closes) >= 200 else None
    above = sum(1 for e in (e9, e20, e200) if e is not None and price >= e)
    have = sum(1 for e in (e9, e20, e200) if e is not None)
    # overhead resistance: a recent swing high well above price would cap the move
    recent_high = max(b.high for b in daily_bars[-20:])
    headroom = (recent_high - price) / price if price else 0
    metrics = {"daily_ema9": e9, "daily_ema20": e20, "daily_ema200": e200,
               "daily_recent_high": round(recent_high, 4), "headroom_pct": round(headroom, 4)}
    if have and above == have:
        score = 1.0 + (0.5 if headroom > 0.05 else 0.0)
        return CriterionEval("daily_strength", True, False, score,
                             "above all key daily EMAs with room to run", metrics)
    if above >= 1:
        return CriterionEval("daily_strength", True, False, 0.5,
                             f"above {above}/{have} key daily EMAs", metrics)
    return CriterionEval("daily_strength", passed=False, hard_fail=True, score=0.0,
                         detail="below its key daily EMAs — weak daily chart", metrics=metrics)


def catalyst_criterion(cat: Optional[Catalyst]) -> CriterionEval:
    if cat is None or not cat.present:
        return CriterionEval(
            "catalyst", passed=True, hard_fail=False, score=0.0,
            detail="no news catalyst — clean technical only (allowed, scored lower)",
            metrics={"catalyst": None})
    score = 2.0 if cat.material else 1.0
    return CriterionEval(
        "catalyst", passed=True, hard_fail=False, score=score,
        detail=f"catalyst: {cat.classification} — \"{cat.headline[:80]}\" ({cat.source})",
        metrics={"catalyst": cat.classification, "catalyst_material": cat.material,
                 "catalyst_headline": cat.headline, "catalyst_source": cat.source})


def rank_candidates(cands: list[Candidate]) -> list[Candidate]:
    """Rank watchlist seeds: biggest, most-active gappers first — the agent
    prefers the single most obvious stock in play over marginal names."""
    def score(c: Candidate) -> float:
        return c.gap_pct * 2 + (c.rvol or 0) + (c.score or 0)
    for c in cands:
        c.score = round(score(c), 3)
    return sorted(cands, key=score, reverse=True)
