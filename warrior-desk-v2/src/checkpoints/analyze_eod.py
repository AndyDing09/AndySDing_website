"""Checkpoint: end-of-day analysis (§5) — the /data:analyze fallback.

Answers, from the journal DB: what drove today's P&L? Which setup, time bucket
and float band performed? Which skipped signals would have won (missed-R)?
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from ..data.store import Store
from ..journal.expectancy import compute, cut_by, time_bucket
from ..journal.journal import audit_skipped


def analyze(store: Store, day_start: datetime, day_end: datetime,
            min_sample_n: int = 30) -> dict:
    trades = store.trades_between(day_start, day_end)
    for t in trades:
        t["time_bucket"] = time_bucket(t["closed_at"])

    skipped = audit_skipped(store, day_start, day_end)
    missed_winners = [asdict(s) for s in skipped if s.would_have == "target"]
    sub2_skips = [s for s in skipped
                  if s.reason == "insufficient_rr" and s.would_have == "target"]

    return {
        "schema": 1,
        "day": day_start.date().isoformat(),
        "day_pnl": round(sum(float(t["pnl_usd"]) for t in trades), 2),
        "n_trades": len(trades),
        "by_setup": {k: asdict(v) for k, v in cut_by(trades, "setup", min_sample_n).items()},
        "by_time_bucket": {k: asdict(v) for k, v in cut_by(trades, "time_bucket", min_sample_n).items()},
        "by_float_band": {k: asdict(v) for k, v in cut_by(trades, "float_band", min_sample_n).items()},
        "day_stats": asdict(compute(trades, min_sample_n)),
        "skipped_audit": {
            "total_skipped": len(skipped),
            "missed_winners": missed_winners,
            "insufficient_rr_that_won": [asdict(s) for s in sub2_skips],
            "reading": ("insufficient_rr skips that 'won' did so at sub-2R payoffs by "
                        "construction — the gate filtering low-quality trades is working "
                        "if their would_r is < 2; investigate any that are not."),
        },
    }


def run(store: Store, day_start: datetime, day_end: datetime, now: datetime,
        reports_dir: str | Path = "reports", min_sample_n: int = 30) -> Path:
    out = Path(reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"analyze_eod_{day_start.date().isoformat()}.json"
    dest.write_text(json.dumps(analyze(store, day_start, day_end, min_sample_n),
                               indent=2, default=str), encoding="utf-8")
    return dest
