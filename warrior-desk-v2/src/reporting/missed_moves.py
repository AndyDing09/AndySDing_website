"""Missed-move postmortem (§7.9), run nightly.

Lists the day's top gainers that never made the watchlist, with the SPECIFIC
filter that excluded each (straight from ``gapper.qualify``). This is how the
filter set improves with evidence instead of FOMO: if the same justified filter
keeps excluding real winners, that's a data point for the weekly stats review —
never a reason to hand-loosen a threshold mid-week.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from ..config import Config
from ..data.corp_actions import CorpActionsGuard
from ..data.floats import CrossValidatedFloat
from ..scanners.gapper import Snapshot, qualify


@dataclass
class MissedMove:
    symbol: str
    day_gain_pct: float
    excluded_by: str


def postmortem(top_gainers: list[tuple[Snapshot, float]], watchlist: set[str],
               cfg: Config, floats: CrossValidatedFloat, guard: CorpActionsGuard,
               now: datetime, top_n: int = 10) -> list[MissedMove]:
    """``top_gainers``: (snapshot, day_gain_pct), biggest movers first."""
    out: list[MissedMove] = []
    for snap, gain in top_gainers[:top_n]:
        if snap.symbol in watchlist:
            continue
        cand, reason = qualify(snap, cfg, floats, guard, now)
        out.append(MissedMove(symbol=snap.symbol, day_gain_pct=round(gain, 4),
                              excluded_by=reason or "qualified late (intraday) — timing, not filters"))
    return out


def run(top_gainers: list[tuple[Snapshot, float]], watchlist: set[str], cfg: Config,
        floats: CrossValidatedFloat, guard: CorpActionsGuard, now: datetime,
        reports_dir: str | Path = "reports") -> Path:
    rows = postmortem(top_gainers, watchlist, cfg, floats, guard, now)
    out = Path(reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"missed_moves_{now.date().isoformat()}.json"
    dest.write_text(json.dumps(
        {"schema": 1, "day": now.date().isoformat(),
         "rows": [asdict(m) for m in rows],
         "note": "Evidence for the weekly stats review — not a licence to loosen filters."},
        indent=2))
    return dest
