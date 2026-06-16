"""``warrior`` command-line interface (Section 10).

    warrior run            # start the agent in the configured mode
    warrior status         # account, positions, day P&L, gates state
    warrior watchlist      # ranked candidates + criteria scores
    warrior propose SYM    # run the 12-step gauntlet on one symbol; place no order
    warrior journal today  # print today's journal summary
    warrior stats          # cumulative performance + graduation-gate progress
    warrior kill           # FLATTEN ALL + cancel orders + halt the session
    warrior backtest ...   # replay historical data through the same gauntlet

``propose`` and ``backtest`` are the main learning tools — full reasoning, zero
execution risk.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from .config import load_config
from .data.provider import AccountInfo
from .disclaimer import DISCLAIMER, DISCLAIMER_SHORT
from .logging_setup import get_logger, setup_logging
from .reasoning import make_reasoner
from .sessions import now_et

log = get_logger("cli")

DEFAULT_SIM_EQUITY = 30_000.0


# ──────────────────────────────────────────────────────────────────────────
# shared context
# ──────────────────────────────────────────────────────────────────────────
def _provider_and_account(cfg, demo: bool, equity: float):
    """Build a (provider, account, is_simulated_account) triple."""
    if demo:
        from .demo import DemoProvider
        return DemoProvider(), AccountInfo(equity=equity, cash=equity, buying_power=equity,
                                           status="SIMULATED", mode="paper"), True
    if cfg.secrets.has_alpaca:
        from .data.alpaca_provider import AlpacaProvider
        from .data.float_source import StaticFloatSource, UnknownFloatSource
        fs = UnknownFloatSource()
        prov = AlpacaProvider(cfg.secrets.alpaca_api_key, cfg.secrets.alpaca_secret_key,
                              mode="paper", float_source=fs)
        try:
            acct = prov.get_account()
            return prov, acct, False
        except Exception as exc:
            log.warning("Could not fetch Alpaca account (%s); using a simulated account.", exc)
            return prov, AccountInfo(equity=equity, cash=equity, buying_power=equity,
                                     status="SIMULATED", mode="paper"), True
    raise SystemExit(
        "No Alpaca keys found (set ALPACA_API_KEY / ALPACA_SECRET_KEY in .env) and "
        "--demo not given.\nTry:  warrior propose --demo WARR")


def _now(cfg, demo: bool) -> datetime:
    if demo:
        from .demo import DEMO_NOW
        return DEMO_NOW
    return now_et(cfg)


# ──────────────────────────────────────────────────────────────────────────
# commands
# ──────────────────────────────────────────────────────────────────────────
def cmd_propose(args) -> int:
    from .gauntlet import Gauntlet
    from .render import render_proposal
    from .state import State

    cfg = load_config(args.config)
    setup_logging(cfg.log_level, cfg.log_dir)
    provider, account, simulated = _provider_and_account(cfg, args.demo, args.equity)
    reasoner = make_reasoner(cfg, cfg.secrets)
    now = _now(cfg, args.demo)

    state = State.load(cfg.state_path)
    state.start_session(now.date(), save=False)   # read-only

    g = Gauntlet(cfg, provider, reasoner=reasoner)
    proposal = g.evaluate_symbol(args.symbol.upper(), account, state, now, short_circuit=False)

    print(render_proposal(proposal))
    if simulated:
        print("NOTE: using a SIMULATED account (equity "
              f"${account.equity:,.0f}); no broker connected.")
    print("(propose places NO order.)  " + DISCLAIMER_SHORT)
    return 0


def cmd_watchlist(args) -> int:
    from .gauntlet import Gauntlet
    cfg = load_config(args.config)
    setup_logging(cfg.log_level, cfg.log_dir)
    provider, _, _ = _provider_and_account(cfg, args.demo, args.equity)
    g = Gauntlet(cfg, provider)
    cands = g.scan(limit=args.limit)
    if not cands:
        print("No candidates (scanner returned nothing — Alpaca's mover coverage is "
              "thin for true low-float names; wire a real scanner via DataProvider).")
        return 0
    print(f"{'#':>2}  {'SYM':<6} {'price':>8} {'gap%':>7} {'rvol':>6} {'score':>7}")
    for i, c in enumerate(cands, 1):
        print(f"{i:>2}  {c.symbol:<6} {c.price:>8.2f} {c.gap_pct*100:>6.1f}% "
              f"{(c.rvol or 0):>6.1f} {c.score:>7.2f}")
    print("\n" + DISCLAIMER_SHORT)
    return 0


def cmd_status(args) -> int:
    from .state import State
    cfg = load_config(args.config)
    setup_logging(cfg.log_level, cfg.log_dir)
    provider, account, simulated = _provider_and_account(cfg, args.demo, args.equity)
    now = _now(cfg, args.demo)
    state = State.load(cfg.state_path)
    state.start_session(now.date(), save=False)

    r = cfg.risk
    print("WARRIOR DESK — STATUS")
    print(f"  mode             {cfg.trading_mode}{' (SIMULATED acct)' if simulated else ''}")
    print(f"  account status   {account.status}")
    print(f"  equity           ${account.equity:,.2f}")
    print(f"  buying power     ${account.buying_power:,.2f}")
    print(f"  day P&L          ${state.day_pnl:,.2f}   (cap -${r.max_daily_loss:,.0f})")
    print(f"  trades today     {state.trades_today} / {r.max_trades_per_day}")
    print(f"  consec. losses   {state.consecutive_losses} / {r.consecutive_loss_halt} (halt)")
    print(f"  open positions   {state.open_count} / {r.max_concurrent_positions}")
    print(f"  session halted   {state.session_halted}"
          + (f' — {state.halt_reason}' if state.session_halted else ''))
    if state.open_positions:
        print("  positions:")
        for sym, pos in state.open_positions.items():
            print(f"    {sym}: {pos.qty} @ {pos.avg_entry:.2f} stop {pos.stop:.2f} "
                  f"target {pos.target:.2f}")
    return 0


def cmd_kill(args) -> int:
    from .kill import kill_switch
    from .state import State
    cfg = load_config(args.config)
    setup_logging(cfg.log_level, cfg.log_dir)
    state = State.load(cfg.state_path)
    broker = None
    if cfg.secrets.has_alpaca:
        try:
            from .broker import AlpacaBroker
            broker = AlpacaBroker(cfg.secrets.alpaca_api_key, cfg.secrets.alpaca_secret_key,
                                  mode="paper")
        except Exception as exc:
            log.warning("Could not build broker for kill: %s", exc)
    report = kill_switch(state, broker, reason=args.reason or "manual kill via CLI")
    print("KILL SWITCH ENGAGED")
    print(f"  orders cancelled : {report['orders_cancelled']}")
    print(f"  positions closed : {report['positions_closed']}")
    if report["errors"]:
        print("  errors:")
        for e in report["errors"]:
            print(f"    - {e}")
    print("  session is halted for the rest of the day.")
    return 0


def cmd_run(args) -> int:
    from .engine import run_agent
    cfg = load_config(args.config)
    setup_logging(cfg.log_level, cfg.log_dir)
    print(DISCLAIMER)
    return run_agent(cfg, demo=args.demo, once=args.once, equity=args.equity,
                     advisory=args.advisory, sound=not args.no_sound)


def cmd_journal(args) -> int:
    from .journal import JournalManager
    cfg = load_config(args.config)
    setup_logging(cfg.log_level, cfg.log_dir)
    jm = JournalManager(cfg)
    print(jm.render_today_summary())
    return 0


def cmd_stats(args) -> int:
    from .stats import render_stats
    cfg = load_config(args.config)
    setup_logging(cfg.log_level, cfg.log_dir)
    print(render_stats(cfg))
    return 0


def cmd_publish(args) -> int:
    import json
    from pathlib import Path
    from .gauntlet import Gauntlet
    from .journal import JournalManager
    from .publish import build_snapshot, fetch_requests, publish_snapshot
    from .sessions import classify_window
    from .state import State

    cfg = load_config(args.config)
    setup_logging(cfg.log_level, cfg.log_dir)
    provider, account, simulated = _provider_and_account(cfg, args.demo, args.equity)
    reasoner = make_reasoner(cfg, cfg.secrets)
    now = _now(cfg, args.demo)
    state = State.load(cfg.state_path)
    state.start_session(now.date(), save=False)
    journal = JournalManager(cfg)
    g = Gauntlet(cfg, provider, reasoner=reasoner)

    watch = g.scan()
    requested = fetch_requests(cfg) if cfg.secrets.publish_url else []
    syms: list[str] = []
    for s in list(args.symbols or []) + requested + [c.symbol for c in watch[:5]]:
        if s.upper() not in syms:
            syms.append(s.upper())
    proposals = [g.evaluate_symbol(s, account, state, now, short_circuit=False) for s in syms]

    window = classify_window(now, cfg)
    session = {"window": window.value, "halted": state.session_halted,
               "halt_reason": state.halt_reason, "day_pnl": round(state.day_pnl, 2),
               "trades_today": state.trades_today, "consecutive_losses": state.consecutive_losses,
               "open_positions": state.open_count}
    snap = build_snapshot(cfg, mode=cfg.trading_mode, account_equity=account.equity,
                          session=session, watchlist=watch, proposals=proposals,
                          open_positions=list(state.open_positions.values()), journal=journal)

    if cfg.secrets.publish_url:
        ok, msg = publish_snapshot(cfg, snap)
        print(f"{'Published' if ok else 'Publish FAILED'} to {cfg.secrets.publish_url} ({msg}); "
              f"{len(proposals)} proposals, {len(watch)} watchlist.")
    else:
        out = Path(cfg.journal_dir) / "snapshot.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(snap, indent=2))
        print(f"No WARRIOR_PUBLISH_URL set — wrote snapshot to {out} "
              f"({len(proposals)} proposals). Set the URL to push it to your site.")
    print(DISCLAIMER_SHORT)
    return 0


def cmd_backtest(args) -> int:
    from .backtest import run_backtest
    cfg = load_config(args.config)
    setup_logging(cfg.log_level, cfg.log_dir)
    return run_backtest(cfg, args)


# ──────────────────────────────────────────────────────────────────────────
# parser
# ──────────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    # Common options shared by every subcommand (so `propose --demo SYM` works).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default="config.yaml", help="path to config.yaml")
    common.add_argument("--demo", action="store_true",
                        help="use the offline demo data (no keys needed)")
    common.add_argument("--equity", type=float, default=DEFAULT_SIM_EQUITY,
                        help="simulated account equity when no broker is connected")

    p = argparse.ArgumentParser(
        prog="warrior",
        description="Warrior Desk momentum day-trading agent (educational; paper by default).")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("propose", parents=[common],
                        help="run the 12-step gauntlet on a symbol; place no order")
    sp.add_argument("symbol")
    sp.set_defaults(func=cmd_propose)

    sw = sub.add_parser("watchlist", parents=[common], help="show ranked candidates")
    sw.add_argument("--limit", type=int, default=20)
    sw.set_defaults(func=cmd_watchlist)

    sub.add_parser("status", parents=[common],
                   help="account, positions, day P&L, gates").set_defaults(func=cmd_status)

    sk = sub.add_parser("kill", parents=[common],
                        help="FLATTEN ALL + cancel orders + halt the session")
    sk.add_argument("--reason", default="")
    sk.set_defaults(func=cmd_kill)

    sr = sub.add_parser("run", parents=[common], help="start the agent loop")
    sr.add_argument("--once", action="store_true", help="one scan/evaluate pass then exit")
    sr.add_argument("--advisory", action="store_true",
                    help="live ENTER/SCALE/EXIT alerts only; NO orders sent (place by hand)")
    sr.add_argument("--no-sound", action="store_true", help="silence alert bell/desktop pings")
    sr.set_defaults(func=cmd_run)

    sj = sub.add_parser("journal", parents=[common], help="print today's journal summary")
    sj.add_argument("when", nargs="?", default="today")
    sj.set_defaults(func=cmd_journal)

    sub.add_parser("stats", parents=[common],
                   help="cumulative performance + graduation gate").set_defaults(func=cmd_stats)

    spub = sub.add_parser("publish", parents=[common],
                          help="evaluate tickers + watchlist and push a snapshot to your website tab")
    spub.add_argument("symbols", nargs="*", help="extra tickers to evaluate")
    spub.set_defaults(func=cmd_publish)

    sb = sub.add_parser("backtest", parents=[common],
                        help="replay historical data through the gauntlet")
    sb.add_argument("--symbol", default=None)
    sb.add_argument("--bars", default=None, help="path to a CSV of OHLCV bars")
    sb.set_defaults(func=cmd_backtest)

    return p


def main(argv=None) -> int:
    from .locks import LiveLockError
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except LiveLockError as exc:
        # A deliberate, clean refusal — not a crash. No traceback.
        print(f"\n{exc}\n", file=sys.stderr)
        return 2
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:  # pragma: no cover
        log.exception("command failed")
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
