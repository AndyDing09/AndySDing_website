#!/usr/bin/env python3
"""Live session (§8, §9.4): start at 9:25 ET, runs hands-off to the close.

Wires the Alpaca PAPER stream into the same SessionEngine replay uses:
1-min bars for the frozen watchlist + SPY, halt awareness, strategies, gates,
bracket execution, trailing, reconciliation every 5 minutes (our books vs the
BROKER's books), kill-switch lock respected, live JSON exports each bar, the
15:55 time stop, an explicit 16:01 shutdown (bars stop after the close — the
stream would otherwise hang until Task Scheduler hard-kills it and the EOD
report would never run), then the EOD report + checkpoint jobs + parquet export.

CLI: python scripts/run_session.py            # trade the frozen watchlist
     python scripts/run_session.py halt       # kill switch: flatten + lock
     python scripts/run_session.py resume     # release the lock
"""
import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alerts import AlertRouter                                    # noqa: E402
from src.checkpoints import analyze_eod, stats_weekly, validate_report  # noqa: E402
from src.config import load_or_exit                                   # noqa: E402
from src.data.alpaca_client import AlpacaClients, make_stream          # noqa: E402
from src.data.clock import NY, check_skew, ny, ny_time, utc_now        # noqa: E402
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

log = logging.getLogger("wd.session")

GUARDRAIL = ("Simulated (paper) trading for education and strategy validation. "
             "Not financial advice. Most day traders lose money.")


def load_frozen_watchlist(cfg) -> dict[str, Candidate]:
    """Wait for the premarket freeze if it's still finishing (slow scan, PC woke
    late): losing the 9:23 race must cost minutes, not the whole day."""
    import time as _time
    day = ny(utc_now()).date().isoformat()
    path = Path(cfg.reports.dir) / f"watchlist_{day}.json"
    for attempt in range(20):                          # up to ~10 minutes
        if path.exists():
            break
        print(f"waiting for {path.name} (premarket still freezing?) "
              f"— retry {attempt + 1}/20 in 30s")
        _time.sleep(30)
    else:
        raise SystemExit(f"no {path} after 10 minutes — run scripts/run_premarket.py first.")
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    return {r["symbol"]: Candidate.model_validate(r) for r in rows}


async def _stop_stream(stream) -> None:
    """Best-effort stream shutdown across alpaca-py variants."""
    for name in ("stop_ws", "stop", "close"):
        fn = getattr(stream, name, None)
        if fn is None:
            continue
        try:
            result = fn()
            if asyncio.iscoroutine(result):
                await result
            return
        except Exception as exc:
            log.debug("stream %s() failed: %s", name, exc)


async def session(cfg) -> int:
    print(GUARDRAIL)
    clients = AlpacaClients(cfg)
    clients.startup_banner()
    check_skew(clients.server_utc, cfg.data.clock_max_skew_seconds)

    candidates = load_frozen_watchlist(cfg)
    alerts = AlertRouter.from_config(cfg.alerts)
    if not candidates:
        # Honest quiet day: pre-market froze an empty list — nothing qualified.
        alerts.send("INFO", "no qualifying watchlist today — standing down (no session)")
        print("Watchlist is empty — no qualifying gappers today. Standing down.")
        return 0

    store = Store(cfg.data.db_path)
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

    # Adopt-or-warn: positions already sitting in the paper account (an old
    # dashboard test, a missed flatten) are NOT ours to manage. Alert loudly and
    # exclude them from reconciliation, otherwise §4.8 freezes entries all day
    # over stale history instead of real drift.
    preexisting: set[str] = set()
    try:
        preexisting = {p.symbol for p in broker.remote_positions()}
    except Exception as exc:
        log.warning("could not list pre-existing positions: %s", exc)
    if preexisting:
        alerts.send("DATA", "pre-existing paper positions ignored by reconciliation: "
                    + ", ".join(sorted(preexisting))
                    + " — flatten them in the Alpaca dashboard when convenient")

    start_equity = broker.account_equity()
    spy_bars: list[Bar] = []
    last_marks: dict[str, float] = {}
    engine = SessionEngine(cfg, broker, store, breakers, candidates,
                           regime=Regime.MIXED, alert=alerts.send)

    async def on_bar(b) -> None:
        bar = Bar(symbol=b.symbol, ts=b.timestamp, open=float(b.open), high=float(b.high),
                  low=float(b.low), close=float(b.close), volume=int(b.volume),
                  feed=cfg.data.feed)
        if bar.symbol == cfg.regime.symbol:
            spy_bars.append(bar)
            engine.regime = classify_regime(spy_bars[-60:], cfg.regime.ema_period).regime
            return
        engine.on_bar(bar)
        last_marks[bar.symbol] = bar.close     # rolling marks: no flicker to entry price
        export_positions(broker.open_positions(), dict(last_marks),
                         utc_now(), cfg.reports.live_dir)
        export_signals(engine.signals, utc_now(), cfg.reports.live_dir)

    stream = make_stream(cfg)

    async def housekeeping() -> None:
        while True:
            await asyncio.sleep(cfg.data.reconcile_interval_seconds)
            if ny_time(utc_now()).hour >= 16:
                break
            try:
                remote = [p for p in broker.remote_positions()
                          if p.symbol not in preexisting]
                # Server-side bracket fills first: a leg that filled at Alpaca
                # leaves our books holding a phantom — close it in the journal
                # (approx price = last bar close) BEFORE reconciling, so §4.8
                # flags real drift instead of the normal bracket lifecycle.
                remote_syms = {p.symbol for p in remote}
                for pos in list(broker.open_positions()):
                    if pos.symbol not in remote_syms:
                        px = engine.last_close(pos.symbol) or pos.target
                        engine.force_close(pos.symbol, px,
                                           "bracket_leg_filled_serverside(approx)",
                                           utc_now())
                # §4.8 for real: OUR books vs the BROKER's independent answer,
                # and OUR expected equity (start + realized) vs the broker's.
                local_equity = start_equity + sum(t.pnl_usd for t in engine.trades)
                reconciler.run(broker.open_positions(), remote,
                               local_equity, broker.account_equity(), utc_now())
            except Exception as exc:
                log.warning("reconcile pass failed: %s", exc)
            monitor.update(store.last_trades(cfg.journal.rolling_expectancy_trades))
            ok, state = breakers.entries_allowed(utc_now())
            export_expectancy(monitor.stats, state if not ok else "clear",
                              monitor.red, utc_now(), cfg.reports.live_dir)

    async def close_watchdog() -> None:
        """Bars stop after the close; stop the stream ourselves at 16:01 ET so
        the session ends cleanly and the EOD chain always runs."""
        now_et = ny(utc_now())
        target = now_et.replace(hour=16, minute=1, second=0, microsecond=0)
        if now_et >= target:
            target += timedelta(days=1)          # started after close: stop soon
            target = min(target, now_et + timedelta(minutes=2))
        await asyncio.sleep(max(5.0, (target - now_et).total_seconds()))
        log.info("close watchdog: stopping the stream")
        await _stop_stream(stream)

    symbols = list(candidates) + [cfg.regime.symbol]
    stream.subscribe_bars(on_bar, *symbols)
    export_watchlist(list(candidates.values()), utc_now(), cfg.reports.live_dir)
    alerts.send("INFO", f"session live on {', '.join(candidates)} ({cfg.data.feed})")

    tasks = [asyncio.create_task(housekeeping()), asyncio.create_task(close_watchdog())]
    try:
        await stream._run_forever()
    finally:
        for t in tasks:
            t.cancel()
        # Flatten-at-close safety net: the 15:55 time stop is bar-driven and a
        # thin name may print no bar in the last minutes. "No overnight holds,
        # ever" is enforced HERE regardless — cancel legs, close everything we
        # (or the broker) still hold, and journal it honestly as approximate.
        try:
            still_open = list(broker.open_positions())
            remote_left = [p for p in broker.remote_positions()
                           if p.symbol not in preexisting]
            if still_open or remote_left:
                alerts.send("EXIT", "shutdown flatten: "
                            + ", ".join(sorted({p.symbol for p in still_open + remote_left})))
                broker.close_all_positions()
                for pos in still_open:
                    px = engine.last_close(pos.symbol) or pos.entry
                    engine.force_close(pos.symbol, px, "shutdown_flatten(approx)",
                                       utc_now())
        except Exception:
            log.exception("shutdown flatten failed — check the Alpaca dashboard")
        try:
            await eod(cfg, store, engine, monitor)
        except Exception:
            log.exception("EOD chain failed — the session error above still stands")
    return 0


async def eod(cfg, store: Store, engine: SessionEngine, monitor: RollingMonitor) -> None:
    now = utc_now()
    session_open_et = ny(now).replace(hour=4, minute=0, second=0, microsecond=0)
    day_start = session_open_et.astimezone(timezone.utc)
    skipped = audit_skipped(store, day_start, now)
    carry = [s for s, st in engine.state.items()
             if st.hod and st.bars and st.bars[-1].close >= st.hod * 0.95]
    write_eod_report(store, day_start, now, monitor, skipped, carry,
                     cfg.reports.dir, auto_open=(ny_time(now).hour >= 15),
                     min_sample_n=cfg.journal.min_sample_n)
    analyze_eod.run(store, day_start, now, now, cfg.reports.dir, cfg.journal.min_sample_n)
    validate_report.run(store, day_start, now, cfg.reports.dir)
    if ny(now).weekday() == 4:                              # Friday ET: weekly stats (§5)
        stats_weekly.run(store, now, cfg.reports.dir, cfg.journal.min_sample_n)
    store.export_day_parquet(ny(now).date().isoformat(), Path(cfg.data.replay_dir))


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
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
