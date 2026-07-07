"""Persistent storage (§4, §6): DuckDB, every market-data row stamped with its feed.

One store owns all tables: raw ticks/quotes/bars (kept for replay), signals
(taken or not), closed trades, news, and data-quality incidents. Raw market data
can be exported to parquet under ``replay/data/`` for the deterministic replay
harness (§7.3).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

import duckdb

from ..models import Bar, Incident, NewsItem, Signal, Tick, TradeRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticks (
  symbol TEXT, ts TIMESTAMPTZ, price DOUBLE, size BIGINT,
  conditions TEXT, feed TEXT);
CREATE TABLE IF NOT EXISTS quotes (
  symbol TEXT, ts TIMESTAMPTZ, bid DOUBLE, ask DOUBLE,
  bid_size BIGINT, ask_size BIGINT, feed TEXT);
CREATE TABLE IF NOT EXISTS bars_1m (
  symbol TEXT, ts TIMESTAMPTZ, open DOUBLE, high DOUBLE, low DOUBLE,
  close DOUBLE, volume BIGINT, feed TEXT);
CREATE TABLE IF NOT EXISTS news (
  symbol TEXT, ts TIMESTAMPTZ, headline TEXT, source TEXT, catalyst_type TEXT);
CREATE TABLE IF NOT EXISTS signals (
  ts TIMESTAMPTZ, symbol TEXT, setup TEXT, entry DOUBLE, stop DOUBLE,
  target DOUBLE, planned_rr DOUBLE, score DOUBLE, regime TEXT, feed TEXT,
  spread_pct DOUBLE, catalyst_type TEXT, float_band TEXT,
  obviousness_rank INTEGER, shares INTEGER, status TEXT, status_reason TEXT);
CREATE TABLE IF NOT EXISTS trades (
  signal_ts TIMESTAMPTZ, closed_at TIMESTAMPTZ, symbol TEXT, setup TEXT,
  entry_intended DOUBLE, entry_fill DOUBLE, exit_fill DOUBLE, stop DOUBLE,
  target DOUBLE, qty INTEGER, realized_r DOUBLE, pnl_usd DOUBLE,
  mae DOUBLE, mfe DOUBLE, hold_seconds DOUBLE, exit_reason TEXT,
  slippage_usd DOUBLE, regime TEXT, catalyst_type TEXT, float_band TEXT, feed TEXT);
CREATE TABLE IF NOT EXISTS incidents (
  ts TIMESTAMPTZ, kind TEXT, symbol TEXT, detail TEXT);
"""


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        p = str(path)
        if p != ":memory:":
            Path(p).parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(p)
        for stmt in _SCHEMA.strip().split(";"):
            if stmt.strip():
                self.conn.execute(stmt)

    # ── writers ──
    def write_tick(self, t: Tick) -> None:
        self.conn.execute(
            "INSERT INTO ticks VALUES (?,?,?,?,?,?)",
            [t.symbol, t.ts, t.price, t.size, json.dumps(t.conditions), t.feed])

    def write_bar(self, b: Bar) -> None:
        self.conn.execute(
            "INSERT INTO bars_1m VALUES (?,?,?,?,?,?,?,?)",
            [b.symbol, b.ts, b.open, b.high, b.low, b.close, b.volume, b.feed])

    def write_news(self, n: NewsItem) -> None:
        self.conn.execute(
            "INSERT INTO news VALUES (?,?,?,?,?)",
            [n.symbol, n.ts, n.headline, n.source, n.catalyst_type.value])

    def write_signal(self, s: Signal) -> None:
        self.conn.execute(
            "INSERT INTO signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [s.ts, s.symbol, s.setup.value, s.entry, s.stop, s.target, s.planned_rr,
             s.score, s.regime.value, s.feed, s.spread_pct_at_signal,
             s.catalyst_type.value, s.float_band, s.obviousness_rank, s.shares,
             s.status.value, s.status_reason])

    def write_trade(self, t: TradeRecord) -> None:
        self.conn.execute(
            "INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [t.signal_ts, t.closed_at, t.symbol, t.setup.value, t.entry_intended,
             t.entry_fill, t.exit_fill, t.stop, t.target, t.qty, t.realized_r,
             t.pnl_usd, t.mae, t.mfe, t.hold_seconds, t.exit_reason, t.slippage_usd,
             t.regime.value, t.catalyst_type.value, t.float_band, t.feed])

    def write_incident(self, i: Incident) -> None:
        self.conn.execute("INSERT INTO incidents VALUES (?,?,?,?)",
                          [i.ts, i.kind, i.symbol, i.detail])

    # ── readers ──
    def bars(self, symbol: str, since: datetime | None = None) -> list[tuple]:
        q = "SELECT symbol, ts, open, high, low, close, volume, feed FROM bars_1m WHERE symbol = ?"
        args: list = [symbol]
        if since is not None:
            q += " AND ts >= ?"
            args.append(since)
        return self.conn.execute(q + " ORDER BY ts", args).fetchall()

    def trades_between(self, start: datetime, end: datetime) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM trades WHERE closed_at >= ? AND closed_at < ? ORDER BY closed_at",
            [start, end]).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    def last_trades(self, n: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM trades ORDER BY closed_at DESC LIMIT ?", [n]).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in reversed(rows)]

    def signals_between(self, start: datetime, end: datetime) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM signals WHERE ts >= ? AND ts < ? ORDER BY ts",
            [start, end]).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    # ── replay export (§7.3) ──
    def export_day_parquet(self, day: str, out_dir: str | Path) -> list[Path]:
        """Export one session's raw ticks/quotes/bars to parquet for replay."""
        out = Path(out_dir) / day
        out.mkdir(parents=True, exist_ok=True)
        written = []
        for table in ("ticks", "quotes", "bars_1m", "news"):
            dest = out / f"{table}.parquet"
            self.conn.execute(
                f"COPY (SELECT * FROM {table} WHERE CAST(ts AS DATE) = DATE '{day}' "
                f"ORDER BY ts) TO '{dest}' (FORMAT PARQUET)")
            written.append(dest)
        return written

    def close(self) -> None:
        self.conn.close()
