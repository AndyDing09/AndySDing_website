"""Morning briefing (§7.5), generated at 9:20 ET.

The frozen watchlist with each name's PLAN — trigger level (pre-market high),
stop zone (pre-market low / consolidation), target (measured move), R:R at the
current quote, and score — plus the regime call. One screen, readable in 60
seconds before the bell.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..models import Candidate
from ..scanners.regime import RegimeCall


def plan_for(c: Candidate) -> dict:
    trigger = c.premkt_high
    stop = c.premkt_low
    plan: dict = {"symbol": c.symbol, "score": c.score, "gap_pct": c.gap_pct,
                  "rvol": c.rvol, "catalyst": c.catalyst_type.value,
                  "headline": c.catalyst_headline[:100],
                  "a_grade": c.a_grade, "obviousness_rank": c.obviousness_rank}
    if trigger and stop and trigger > stop:
        risk = trigger - stop
        prior = c.last / (1 + c.gap_pct) if c.gap_pct > -1 else 0.0
        target = trigger + max(0.0, c.last - prior)      # measured move
        plan.update({
            "trigger": round(trigger, 2), "stop_zone": round(stop, 2),
            "target": round(target, 2),
            "rr_at_quote": round((target - trigger) / risk, 2) if risk > 0 else 0.0,
        })
    else:
        plan["note"] = "no clean pre-market levels — wait for structure after the open"
    return plan


def build_brief(watchlist: list[Candidate], regime: RegimeCall, now: datetime) -> str:
    lines = [f"WARRIOR DESK — MORNING BRIEF  {now.date().isoformat()}  "
             f"(regime: {regime.regime.value})", "=" * 72]
    for c in watchlist:
        p = plan_for(c)
        head = (f"#{p['obviousness_rank']} {c.symbol:<6} gap {c.gap_pct:+.0%}  "
                f"rvol {c.rvol:.1f}x  score {c.score:.0f}"
                f"{'  A+' if c.a_grade else ''}")
        lines.append(head)
        if "trigger" in p:
            lines.append(f"   plan: over {p['trigger']:.2f} → target {p['target']:.2f}, "
                         f"stop zone {p['stop_zone']:.2f}  (R:R {p['rr_at_quote']:.1f})")
        else:
            lines.append(f"   plan: {p['note']}")
        lines.append(f"   why:  {c.catalyst_type.value} — {c.catalyst_headline[:80]}")
    lines.append("=" * 72)
    lines.append("Rules today: 2:1 minimum, risk fixed per trade, no entries after 11:30 ET,"
                 " -3R or 3 straight losses = done. Paper only; educational.")
    return "\n".join(lines)


def write_brief(watchlist: list[Candidate], regime: RegimeCall, now: datetime,
                reports_dir: str | Path) -> Path:
    out = Path(reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"brief_{now.date().isoformat()}.txt"
    dest.write_text(build_brief(watchlist, regime, now), encoding="utf-8")
    (out / f"brief_{now.date().isoformat()}.json").write_text(json.dumps(
        {"schema": 1, "generated_at": now.isoformat(),
         "regime": regime.regime.value,
         "plans": [plan_for(c) for c in watchlist]}, indent=2), encoding="utf-8")
    return dest
