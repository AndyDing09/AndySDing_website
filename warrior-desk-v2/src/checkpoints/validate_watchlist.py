"""Checkpoint: watchlist QA after the 9:15 freeze (§5).

Preferred implementation is the `/data:validate-data` skill when the session has
it; this module is the always-available equivalent with the same contract:
recompute gap % from the raw prior-close and last-trade inputs, spot-check the
rvol math, verify the float sources agree, and confirm every name has a
parseable catalyst. A watchlist that fails validation ships with a WARNING
banner — it is not silently trusted.

Output: reports/validate_watchlist_<timestamp>.json plus a returned summary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..models import Candidate, CatalystType
from ..scanners.gapper import Snapshot, rvol_time_of_day


@dataclass
class ValidationResult:
    ok: bool
    checks: int = 0
    failures: list[str] = field(default_factory=list)
    banner: str = ""

    def to_json(self) -> dict:
        return {"schema": 1, "ok": self.ok, "checks": self.checks,
                "failures": self.failures, "banner": self.banner}


def validate_watchlist(
    cands: list[Candidate],
    raw: dict[str, Snapshot],
    rvol_tolerance: float = 0.05,
    gap_tolerance: float = 0.005,
) -> ValidationResult:
    """``raw`` maps symbol -> the Snapshot the row was computed from."""
    res = ValidationResult(ok=True)

    for c in cands:
        snap = raw.get(c.symbol)
        if snap is None:
            res.failures.append(f"{c.symbol}: no raw snapshot retained — cannot audit")
            continue

        # 1. Recompute gap % from raw inputs.
        res.checks += 1
        if snap.prior_close > 0:
            gap = (snap.last - snap.prior_close) / snap.prior_close
            if abs(gap - c.gap_pct) > gap_tolerance:
                res.failures.append(
                    f"{c.symbol}: gap% mismatch — row {c.gap_pct:.2%} vs recomputed {gap:.2%}")
        else:
            res.failures.append(f"{c.symbol}: prior_close <= 0 in raw snapshot")

        # 2. Spot-check rvol math.
        res.checks += 1
        rv = rvol_time_of_day(snap.premkt_vol, snap.cum_vol_baseline)
        if abs(rv - c.rvol) > max(rvol_tolerance * max(rv, 1.0), 0.05):
            res.failures.append(
                f"{c.symbol}: rvol mismatch — row {c.rvol:.2f} vs recomputed {rv:.2f}")

        # 3. Float agreement.
        res.checks += 1
        if c.float_shares is None:
            res.failures.append(f"{c.symbol}: float unknown — A+ tag impossible, verify vendor")
        elif c.float_unverified:
            res.failures.append(f"{c.symbol}: float_unverified (vendor disagreement)")

        # 4. Catalyst parseable.
        res.checks += 1
        if not c.catalyst_headline or c.catalyst_type == CatalystType.OTHER:
            res.failures.append(
                f"{c.symbol}: catalyst missing or unclassified ({c.catalyst_type.value})")

        # 5. Sanity: values in plausible ranges.
        res.checks += 1
        if not (0 < c.last < 1000) or c.premkt_vol < 0:
            res.failures.append(f"{c.symbol}: implausible price/volume ({c.last}, {c.premkt_vol})")

    res.ok = not res.failures
    if not res.ok:
        res.banner = ("WARNING: watchlist failed validation — "
                      f"{len(res.failures)} issue(s). Review before trusting levels.")
    return res


def run(cands: list[Candidate], raw: dict[str, Snapshot], now: datetime,
        reports_dir: str | Path = "reports") -> ValidationResult:
    res = validate_watchlist(cands, raw)
    out = Path(reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    (out / f"validate_watchlist_{stamp}.json").write_text(json.dumps(res.to_json(), indent=2))
    if res.banner:
        print(res.banner)
    return res
