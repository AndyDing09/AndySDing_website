#!/usr/bin/env python3
"""Live session (§8, §9.4): start at 9:25 ET, runs hands-off to the close.

Wires the Alpaca PAPER stream into the same SessionEngine replay uses:
1-min bars for the frozen watchlist + SPY → scrub-adjacent bar handling, halt
awareness, strategies, gates, bracket execution, trailing, reconciliation every
5 minutes, kill-switch lock respected, live JSON exports each bar, EOD flatten
via the 15:55 time stop, then the 16:05 EOD report + checkpoint jobs + parquet
export for replay.

CLI: python scripts/run_session.py            # trade the frozen watchlist
     python scripts/run_session.py halt       # kill switch: flatten + lock
     python scripts/run_session.py resume     # release the lock
"""
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alerts import AlertRouter                                    # noqa: E402
from src.checkpoints import analyze_eod, stats_weekly, validate_report  # noqa: E402
from src.config import load_or_exit                                   # noqa: E402
from src.data.alpaca_client import AlpacaClients, make_stream          # noqa: E402
from src.data.clock import check_skew, ny_time, utc_now                # noqa: E402
from src.data.store import Store                                       # noqa: E402
from src.engine import SessionEngine                                   # noqa: E402
from src.execution.broker import AlpacaPaperBroker                     # noqa: E402
from src.execution.kill_switch import KillSwitch                       # noqa: E402
from src.journal.expectancy import RollingMonitor                      # noqa: E402
from src.journal.journal import audit_skipped                          # noqa: E402
from src.models import Bar, Candidate, Regime                          # noqa: E402
from src.reporting.eod_report import write_eod_report                  # noqa: E402
from src.reporting.live_export import (export_expectancy, export_positions,  # noqa: E402
                                       export_signals, export_watchlist)
from src.risk.circuit_breakers import CircuitBreakers                  # noqa: E402
from src.risk.reconciliation import Reconciler                         # noqa: E402
from src.scanners.regime import classify_regime                        # noqa: E402

GUARDRAIL = ("Simulated (paper) trading for education and strategy validation. "
             "Not financial advice. Most day traders lose money.")


def load_frozen_watchlist(cfg) -> dict[str, Candidate]:
    day = utc_now().date().isoformat()
    path = Path(cfg.reports.dir) / f"watchlist_{day}.json"
    if not path.exists():
        raise SystemExit(f"no {path} — run scripts/run_premarket.py first.")
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    return {r["symbol"]: Candidate.model_validate(r) for r in rows}


async def session(cfg) -> int:
    print(GUARDRAIL)
    clients = AlpacaClients(cfg)
    clients.startup_banner()
    check_skew(clients.server_utc, cfg.data.clock_max_skew_seconds)

    candidates = load_frozen_watchlist(cfg)
    store = Store(cfg.data.db_path)
    alerts = AlertRouter.from_config(cfg.alerts)
    breakers = CircuitBreakers(cfg.risk)
    broker = AlpacaPaperBroker(cfg, clients)
    ks = KillSwitch(broker, breakers)
    if ks.is_halted():
        print("HALTED lock present — run `run_session.py resume` first.")
        return 2
    reconciler = Reconciler(breakers, store, alerts.send)
    monitor = RollingMonitor(cfg.journal.rolling_expectancy_trades, cfg.journal.min_sample_n)
    monitor.update(store.last_trades(cfg.journal.rolling_expectancy_trades))
    banner = monitor.banner()
    if banner:
        print(banner)                       # never buried (§6)

    spy_bars: list[Bar] = []
    regime = Regime.MIXED
    engine = SessionEngine(cfg, broker, store, breakers, candidates,
                           regime=regime, alert=alerts.send)

    async def on_bar(b) -> None:
        nonlocal regime
        bar = Bar(symbol=b.symbol, ts=b.timestamp, open=float(b.open), high=float(b.high),
                  low=float(b.low), close=float(b.close), volume=int(b.volume),
                  feed=cfg.data.feed)
        if bar.symbol == cfg.regime.symbol:
            spy_bars.append(bar)
            regime = classify_regime(spy_bars[-60:], cfg.regime.ema_period).regime
            engine.regime = regime
            return
        engine.on_bar(bar)
        export_positions(broker.open_positions(),
                         {bar.symbol: bar.close}, utc_now(), cfg.reports.live_dir)
        export_signals(engine.signals, utc_now(), cfg.reports.live_dir)

    async def housekeeping() -> None:
        while ny_time(utc_now()).hour < 16:
            await asyncio.sleep(cfg.data.reconcile_interval_seconds)
            reconciler.run(engine_positions := broker.open_positions(),
                           broker.open_positions(), broker.account_equity(),
                           broker.account_equity(), utc_now())
            monitor.update(store.last_trades(cfg.journal.rolling_expectancy_trades))
            ok, state = breakers.entries_allowed(utc_now())
            export_expectancy(monitor.stats, state if not ok else "clear",
                              monitor.red, utc_now(), cfg.reports.live_dir)

    stream = make_stream(cfg)
    symbols = list(candidates) + [cfg.regime.symbol]
    stream.subscribe_bars(on_bar, *symbols)
    export_watchlist(list(candidates.values()), utc_now(), cfg.reports.live_dir)
    alerts.send("INFO", f"session live on {', '.join(candidates)} ({cfg.data.feed})")

    task = asyncio.create_task(housekeeping())
    try:
        await stream._run_forever()
    finally:
        task.cancel()
        await eod(cfg, store, engine, monitor)
    return 0


async def eod(cfg, store: Store, engine: SessionEngine, monitor: RollingMonitor) -> None:
    now = utc_now()
    day_start = now.replace(hour=8, minute=0, second=0, microsecond=0)
    skipped = audit_skipped(store, day_start, now)
    carry = [s for s, st in engine.state.items()
             if st.hod and st.bars and st.bars[-1].close >= st.hod * 0.95]
    write_eod_report(store, day_start, now, monitor, skipped, carry,
                     cfg.reports.dir, auto_open=True,
                     min_sample_n=cfg.journal.min_sample_n)
    analyze_eod.run(store, day_start, now, now, cfg.reports.dir, cfg.journal.min_sample_n)
    validate_report.run(store, day_start, now, cfg.reports.dir)
    if now.weekday() == 4:                                  # Friday: weekly stats (§5)
        stats_weekly.run(store, now, cfg.reports.dir, cfg.journal.min_sample_n)
    store.export_day_parquet(now.date().isoformat(),
                             Path(cfg.data.replay_dir))


def main() -> int:
    cfg = load_or_exit()
    if len(sys.argv) > 1 and sys.argv[1] in ("halt", "resume"):
        clients = AlpacaClients(cfg)
        ks = KillSwitch(AlpacaPaperBroker(cfg, clients), CircuitBreakers(cfg.risk))
        if sys.argv[1] == "halt":
            report = ks.halt("operator halt")
            print(json.dumps(report, indent=2, default=str))
        else:
            ks.resume()
            print("resumed — entries unlocked")
        return 0
    return asyncio.run(session(cfg))


if __name__ == "__main__":
    raise SystemExit(main())
