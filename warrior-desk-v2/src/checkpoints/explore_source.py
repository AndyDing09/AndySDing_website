"""Checkpoint: data-source onboarding profile (§5).

The automation/fallback for the installed `/explore-data` skill, following its
profile spec: table shape, per-column null rate + cardinality + top values,
numeric percentiles (p1..p99, zero/negative counts), timestamp range/gaps, and
the skill's quality flags (nulls >5% warn / >20% alert, placeholder values,
duplicate (symbol, ts) keys). A source is not trusted in production until this
has run and the flags were reviewed.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..data.store import Store

_NUMERIC_SUSPECTS = ("price", "open", "high", "low", "close", "bid", "ask")
_PLACEHOLDERS = {"N/A", "TBD", "test", "xxx", "999999", "-1"}
# Closed enums we stamp ourselves (feed=iex/sip/replay/test, setup names, ...):
# the placeholder heuristic is for VENDOR data, not our own tags.
_ENUM_COLS = {"feed", "setup", "regime", "status", "exchange", "catalyst_type",
              "exit_reason", "float_band", "kind"}


def _percentiles(store: Store, table: str, col: str) -> dict:
    row = store.conn.execute(
        f"SELECT min({col}), max({col}), avg({col}), median({col}), stddev({col}), "
        f"quantile_cont({col}, 0.01), quantile_cont({col}, 0.05), "
        f"quantile_cont({col}, 0.25), quantile_cont({col}, 0.75), "
        f"quantile_cont({col}, 0.95), quantile_cont({col}, 0.99), "
        f"count(*) FILTER (WHERE {col} = 0), count(*) FILTER (WHERE {col} < 0) FROM {table}"
    ).fetchone()
    keys = ("min", "max", "mean", "median", "stddev", "p1", "p5", "p25", "p75",
            "p95", "p99", "zero_count", "negative_count")
    return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in zip(keys, row)}


def profile_table(store: Store, table: str) -> dict:
    meta = store.conn.execute(
        f"SELECT column_name, data_type FROM information_schema.columns "
        f"WHERE table_name = '{table}' ORDER BY ordinal_position").fetchall()
    n = store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    report: dict = {"schema": 2, "table": table, "rows": n,
                    "columns": {}, "quality_flags": []}
    if n == 0:
        report["quality_flags"].append("ALERT: table is empty")
        return report

    for col, dtype in meta:
        nulls = store.conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL").fetchone()[0]
        distinct = store.conn.execute(
            f"SELECT COUNT(DISTINCT {col}) FROM {table}").fetchone()[0]
        info: dict = {"type": dtype,
                      "null_rate": round(nulls / n, 4),
                      "distinct": distinct,
                      "cardinality_ratio": round(distinct / n, 4)}
        # quality flags per the explore-data skill thresholds
        if info["null_rate"] > 0.20:
            report["quality_flags"].append(f"ALERT: {col} null rate {info['null_rate']:.0%}")
        elif info["null_rate"] > 0.05:
            report["quality_flags"].append(f"WARN: {col} null rate {info['null_rate']:.0%}")

        lower = dtype.lower()
        if any(t in lower for t in ("int", "double", "decimal", "float", "bigint")):
            info["stats"] = _percentiles(store, table, col)
            if col in _NUMERIC_SUSPECTS and info["stats"]["zero_count"]:
                report["quality_flags"].append(
                    f"WARN: {col} has {info['stats']['zero_count']} zero values")
            if col in _NUMERIC_SUSPECTS and info["stats"]["negative_count"]:
                report["quality_flags"].append(
                    f"ALERT: {col} has {info['stats']['negative_count']} negative values")
        elif "timestamp" in lower or "date" in lower:
            lo, hi = store.conn.execute(
                f"SELECT min({col}), max({col}) FROM {table}").fetchone()
            info["range"] = {"min": str(lo), "max": str(hi)}
        else:
            top = store.conn.execute(
                f"SELECT {col}, COUNT(*) c FROM {table} WHERE {col} IS NOT NULL "
                f"GROUP BY {col} ORDER BY c DESC LIMIT 5").fetchall()
            info["top_values"] = [[str(v), c] for v, c in top]
            if col not in _ENUM_COLS:
                bad = [str(v) for v, _ in top if str(v).strip() in _PLACEHOLDERS]
                if bad:
                    report["quality_flags"].append(
                        f"ALERT: {col} contains placeholder values {bad}")

        report["columns"][col] = info

    cols = [c for c, _ in meta]
    if "symbol" in cols and "ts" in cols:
        dupes = store.conn.execute(
            f"SELECT COUNT(*) FROM (SELECT symbol, ts, COUNT(*) c FROM {table} "
            f"GROUP BY symbol, ts HAVING c > 1)").fetchone()[0]
        if dupes:
            report["quality_flags"].append(f"ALERT: {dupes} duplicate (symbol, ts) pairs")
    return report


def run(store: Store, table: str, now: datetime,
        reports_dir: str | Path = "reports") -> Path:
    out = Path(reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"explore_{table}_{now.strftime('%Y%m%d_%H%M%S')}.json"
    dest.write_text(json.dumps(profile_table(store, table), indent=2, default=str),
                    encoding="utf-8")
    return dest
