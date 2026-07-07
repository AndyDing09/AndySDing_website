"""Live JSON contract (§8): everything a web dashboard needs, in reports/live/.

Schemas are versioned with an integer ``schema`` field and documented in
CLAUDE.md. The current consumer is the ⚡ Warrior tab on the operator's site;
the contract is front-end-agnostic and must stay stable.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..journal.expectancy import ExpectancyStats
from ..models import Candidate, Position, Signal


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)                    # atomic-ish: pollers never see half a file
    return path


def export_watchlist(cands: list[Candidate], now: datetime, live_dir: str | Path) -> Path:
    return _write(Path(live_dir) / "watchlist.json",
                  {"schema": 1, "generated_at": now.isoformat(),
                   "rows": [c.model_dump() for c in cands]})


def export_positions(positions: list[Position], marks: dict[str, float],
                     now: datetime, live_dir: str | Path) -> Path:
    rows = []
    for p in positions:
        mark = marks.get(p.symbol, p.entry)
        rows.append({**p.model_dump(),
                     "mark": mark, "unrealized_r": round(p.r_at(mark), 2)})
    return _write(Path(live_dir) / "positions.json",
                  {"schema": 1, "generated_at": now.isoformat(), "rows": rows})


def export_signals(signals: list[Signal], now: datetime, live_dir: str | Path,
                   limit: int = 50) -> Path:
    rows = [s.model_dump() for s in signals[-limit:]]
    return _write(Path(live_dir) / "signals.json",
                  {"schema": 1, "generated_at": now.isoformat(), "rows": rows})


def export_expectancy(stats: ExpectancyStats, breaker_state: str, red: bool,
                      now: datetime, live_dir: str | Path) -> Path:
    return _write(Path(live_dir) / "expectancy.json",
                  {"schema": 1, "generated_at": now.isoformat(),
                   "rolling": {
                       "n": stats.n, "win_rate": stats.win_rate,
                       "win_rate_ci": list(stats.win_rate_ci),
                       "expectancy_usd": stats.expectancy_usd,
                       "expectancy_r": stats.expectancy_r,
                       "profit_factor": stats.profit_factor,
                       "insufficient_sample": stats.insufficient_sample,
                       "unprofitable": red,
                   },
                   "breakers": breaker_state})
