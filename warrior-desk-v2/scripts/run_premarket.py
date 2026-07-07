#!/usr/bin/env python3
"""Pre-market run (§3.1): start at 7:00 ET.

Scans on the configured refresh, prints the ranked gapper table, freezes the
watchlist at 9:15, runs the validation checkpoint, and writes the 9:20 morning
brief. Requires ALPACA_API_KEY / ALPACA_SECRET_KEY (paper) in the environment.
"""
import json
import os
import sys
import time as _time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alerts import AlertRouter                                   # noqa: E402
from src.checkpoints import validate_watchlist as vw                 # noqa: E402
from src.config import load_or_exit                                  # noqa: E402
from src.data.alpaca_client import AlpacaClients                     # noqa: E402
from src.data.clock import check_skew, ny, ny_time, utc_now          # noqa: E402
from src.data.corp_actions import CorpActionsGuard                   # noqa: E402
from src.data.floats import (CrossValidatedFloat, FinnhubFloatProvider,  # noqa: E402
                             FMPFloatProvider, YFinanceFloatProvider)
from src.data.news import classify                                   # noqa: E402
from src.models import NewsItem                                      # noqa: E402
from src.reporting.morning_brief import write_brief                  # noqa: E402
from src.scanners.gapper import (Snapshot, freeze_watchlist, render_table,  # noqa: E402
                                 scan, write_watchlist_json)
from src.scanners.regime import RegimeCall, classify_regime          # noqa: E402
from src.models import Regime                                        # noqa: E402

GUARDRAIL = ("Simulated (paper) trading for education and strategy validation. "
             "Not financial advice. Most day traders lose money.")


def fetch_snapshots(clients: AlpacaClients, cfg) -> list[Snapshot]:
    """Most-actives seed universe → snapshots → Snapshot rows.

    On the free IEX feed this is an approximation of the full tape (the startup
    banner says so); it works unchanged on SIP."""
    from alpaca.data.historical.screener import ScreenerClient
    from alpaca.data.requests import MostActivesRequest, StockSnapshotRequest

    screener = ScreenerClient(clients.key, clients.secret)
    actives = screener.get_most_actives(MostActivesRequest(top=100))
    symbols = [a.symbol for a in getattr(actives, "most_actives", [])]
    if not symbols:
        return []
    snaps = clients.market.get_stock_snapshot(StockSnapshotRequest(
        symbol_or_symbols=symbols, feed=cfg.data.feed))
    news_client = None
    out: list[Snapshot] = []
    for sym, s in (snaps or {}).items():
        try:
            prev_close = float(s.previous_daily_bar.close) if s.previous_daily_bar else 0.0
            last = float(s.latest_trade.price) if s.latest_trade else 0.0
            day_vol = int(s.daily_bar.volume) if s.daily_bar else 0
            hi = float(s.daily_bar.high) if s.daily_bar else last
            lo = float(s.daily_bar.low) if s.daily_bar else last
        except (AttributeError, TypeError):
            continue
        out.append(Snapshot(symbol=sym, exchange="NASDAQ", last=last,
                            prior_close=prev_close, premkt_vol=day_vol,
                            premkt_high=hi, premkt_low=lo,
                            cum_vol_baseline=max(1.0, day_vol / max(cfg.universe.rvol_min * 2, 1)),
                            news=fetch_news(clients, sym)))
    return out


def fetch_news(clients: AlpacaClients, symbol: str) -> list[NewsItem]:
    try:
        from alpaca.data.historical.news import NewsClient
        from alpaca.data.requests import NewsRequest
        nc = NewsClient(clients.key, clients.secret)
        res = nc.get_news(NewsRequest(symbols=symbol, limit=10))
        items = []
        for n in getattr(res, "news", []) or []:
            items.append(classify(NewsItem(symbol=symbol, ts=n.created_at,
                                           headline=n.headline, source="benzinga")))
        return items
    except Exception:
        return []


def main() -> int:
    cfg = load_or_exit()
    print(GUARDRAIL)
    clients = AlpacaClients(cfg)
    clients.startup_banner()
    skew = check_skew(clients.server_utc, cfg.data.clock_max_skew_seconds)
    print(f"clock skew vs exchange: {skew:.2f}s (limit {cfg.data.clock_max_skew_seconds}s)")

    alerts = AlertRouter.from_config(cfg.alerts)
    floats = CrossValidatedFloat(
        [FMPFloatProvider(), FinnhubFloatProvider(), YFinanceFloatProvider()],
        cfg.data.float_disagreement_pct)
    guard = CorpActionsGuard()
    frozen = None

    while True:
        now = utc_now()
        t = ny_time(now)
        if t >= cfg.scanners.watchlist_freeze and frozen is None:
            snaps = fetch_snapshots(clients, cfg)
            raw = {s.symbol: s for s in snaps}
            cands = scan(snaps, cfg, floats, guard, now)
            frozen = freeze_watchlist(cands, cfg)
            write_watchlist_json(frozen, now, cfg.reports.dir)
            vw.run(frozen, raw, now, cfg.reports.dir)          # §5 checkpoint
            regime = RegimeCall(Regime.MIXED)                   # refined at the open
            write_brief(frozen, regime, now, cfg.reports.dir)
            alerts.send("INFO", f"watchlist frozen: {', '.join(c.symbol for c in frozen)}")
            print(render_table(frozen))
            print("Frozen. Start scripts/run_session.py before 9:25 ET.")
            return 0
        snaps = fetch_snapshots(clients, cfg)
        cands = scan(snaps, cfg, floats, guard, now)
        print(f"\n[{ny(now).strftime('%H:%M:%S')} ET] top gappers:")
        print(render_table(cands))
        _time.sleep(cfg.scanners.premarket_refresh_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
