"""Replay harness (§7.3): re-run the full pipeline against stored data.

``replay --date 2026-07-06 --speed 10x`` loads that session's persisted bars
(parquet exported by the Store) and drives the SAME SessionEngine used live —
identical code paths, so any rule change can be tested on history before it
touches live paper. Deterministic: same input, same signals, same digest.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass
from pathlib import Path

import duckdb

from src.config import Config
from src.data.store import Store
from src.engine import SessionEngine
from src.execution.broker import SimBroker
from src.models import Bar, Candidate, Regime
from src.risk.circuit_breakers import CircuitBreakers


def load_bars_parquet(day_dir: str | Path) -> list[Bar]:
    p = Path(day_dir) / "bars_1m.parquet"
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found — capture a session first (run_session persists bars), "
            f"then Store.export_day_parquet() writes the replay files.")
    rows = duckdb.sql(f"SELECT * FROM '{p}' ORDER BY ts, symbol").fetchall()
    return [Bar(symbol=r[0], ts=r[1], open=r[2], high=r[3], low=r[4], close=r[5],
                volume=int(r[6]), feed="replay") for r in rows]


@dataclass
class ReplayResult:
    n_bars: int
    n_signals: int
    n_trades: int
    pnl_usd: float
    digest: str


def run_replay(cfg: Config, bars: list[Bar], candidates: dict[str, Candidate],
               regime: Regime = Regime.MIXED, speed: float = 0.0,
               store: Store | None = None, equity: float | None = None) -> ReplayResult:
    """``speed``: 0 = as fast as possible; N = simulate 1 minute per 60/N s.
    Same-engine guarantee: this constructs the identical SessionEngine that
    run_session uses live, fed from stored data instead of the stream."""
    store = store or Store(":memory:")
    broker = SimBroker(cfg, equity=equity)
    breakers = CircuitBreakers(cfg.risk)
    engine = SessionEngine(cfg, broker, store, breakers, candidates, regime=regime)

    bars_sorted = sorted(bars, key=lambda b: (b.ts, b.symbol))
    for bar in bars_sorted:
        engine.on_bar(bar)
        if speed > 0:
            _time.sleep(60.0 / speed / 1000.0)     # scaled-down pacing for demos

    pnl = sum(t.pnl_usd for t in engine.trades)
    return ReplayResult(n_bars=len(bars_sorted), n_signals=len(engine.signals),
                        n_trades=len(engine.trades), pnl_usd=round(pnl, 2),
                        digest=engine.signals_digest())
