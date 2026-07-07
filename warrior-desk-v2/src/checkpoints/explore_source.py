"""Checkpoint: data-source onboarding profile (§5) — the /data:explore-data
fallback. Profile a store table before the source is trusted in production:
row count, null rates, duplicate symbols, suspicious values (float = 0,
price = 0, negative sizes).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..data.store import Store

_NUMERIC_SUSPECTS = ("price", "open", "high", "low", "close", "bid", "ask")


def profile_table(store: Store, table: str) -> dict:
    cols = [r[0] for r in store.conn.execute(
        f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'"
    ).fetchall()]
    n = store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    report: dict = {"schema": 1, "table": table, "rows": n, "columns": {}, "suspicious": []}
    if n == 0:
        report["suspicious"].append("table is empty")
        return report

    for col in cols:
        nulls = store.conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL").fetchone()[0]
        report["columns"][col] = {"null_rate": round(nulls / n, 4)}
        if col in _NUMERIC_SUSPECTS:
            zeros = store.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} <= 0").fetchone()[0]
            if zeros:
                report["suspicious"].append(f"{col} <= 0 in {zeros} rows")
        if col == "size":
            neg = store.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE size < 0").fetchone()[0]
            if neg:
                report["suspicious"].append(f"negative size in {neg} rows")

    if "symbol" in cols and "ts" in cols:
        dupes = store.conn.execute(
            f"SELECT COUNT(*) FROM (SELECT symbol, ts, COUNT(*) c FROM {table} "
            f"GROUP BY symbol, ts HAVING c > 1)").fetchone()[0]
        if dupes:
            report["suspicious"].append(f"{dupes} duplicate (symbol, ts) pairs")
    return report


def run(store: Store, table: str, now: datetime,
        reports_dir: str | Path = "reports") -> Path:
    out = Path(reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"explore_{table}_{now.strftime('%Y%m%d_%H%M%S')}.json"
    dest.write_text(json.dumps(profile_table(store, table), indent=2))
    return dest
