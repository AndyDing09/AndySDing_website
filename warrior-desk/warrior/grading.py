"""Setup grading A / B / C (Section 4 + the §3.1 size discipline).

Grading runs only on a setup that already cleared the hard criteria and has a
valid pattern and ≥2:1 R:R. It decides *quality*, which drives size:

  A  full size      — the once-a-year clean setup: verified low float, a material
                      catalyst, a tight pullback holding VWAP, fat R:R.
  B  sized down     — solid but with a soft spot (unverified float, no news, or a
                      40–50% retrace). Auto-sized down by ``b_grade_size_factor``.
  C  rejected       — marginal; not worth the risk.

Two hard caps encode the spec: a setup with an UNVERIFIED float or with NO
material catalyst can never be graded A (max B). That's how "downgrade what you
can't verify" and "a no-news breakout is scored lower" become mechanical.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Catalyst, Grade, PatternResult
from .data.provider import FloatInfo

A_MIN = 6.0
B_MIN = 3.0


@dataclass
class GradeResult:
    grade: Grade
    score: float
    notes: list[str]


def grade_setup(
    fi: FloatInfo,
    rvol: float,
    catalyst: Catalyst | None,
    pattern: PatternResult,
    reward_risk: float,
    daily_score: float = 0.0,
) -> GradeResult:
    score = 0.0
    notes: list[str] = []

    # Float
    if fi.known and fi.verified:
        if fi.shares <= 20_000_000:
            score += 2.0; notes.append("ideal sub-20M float (+2)")
        elif fi.shares <= 100_000_000:
            score += 1.0; notes.append("low float <100M (+1)")
    float_ok_for_A = fi.known and fi.verified

    # RVOL
    if rvol >= 5:
        score += 2.0; notes.append("RVOL >=5x (+2)")
    elif rvol >= 3:
        score += 1.0; notes.append("RVOL >=3x (+1)")
    elif rvol >= 2:
        score += 0.5; notes.append("RVOL >=2x (+0.5)")

    # Catalyst
    material = bool(catalyst and catalyst.material)
    if material:
        score += 2.0; notes.append("material catalyst (+2)")
    elif catalyst and catalyst.present:
        score += 1.0; notes.append("soft catalyst (+1)")
    else:
        notes.append("no catalyst — technical only (caps at B)")

    # Pattern quality
    if pattern.retrace_pct is not None:
        if pattern.retrace_pct <= 0.30:
            score += 1.5; notes.append("shallow <=30% pullback (+1.5)")
        elif pattern.retrace_pct <= 0.50:
            score += 0.5; notes.append("40-50% pullback (+0.5)")
    if pattern.holds_9ema and pattern.holds_vwap:
        score += 1.0; notes.append("held 9-EMA and VWAP (+1)")
    if pattern.low_volume_pullback:
        score += 1.0; notes.append("low-volume pullback (+1)")

    # Daily chart
    if daily_score >= 1.0:
        score += 1.0; notes.append("strong daily chart (+1)")

    # Reward:risk
    if reward_risk >= 3.0:
        score += 1.0; notes.append("R:R >=3 (+1)")
    elif reward_risk >= 2.0:
        score += 0.5; notes.append("R:R >=2 (+0.5)")

    score = round(score, 2)

    # Map to a grade, applying the A-caps.
    holds_vwap_ok = pattern.holds_vwap is not False  # None (unknown) doesn't block
    can_be_A = float_ok_for_A and material and holds_vwap_ok and score >= A_MIN
    if can_be_A:
        grade = Grade.A
    elif score >= B_MIN:
        grade = Grade.B
        if not float_ok_for_A:
            notes.append("capped at B: float unverified")
        elif not material:
            notes.append("capped at B: no material catalyst")
    else:
        grade = Grade.C
        notes.append(f"score {score} below B threshold {B_MIN} — rejected")

    return GradeResult(grade=grade, score=score, notes=notes)
