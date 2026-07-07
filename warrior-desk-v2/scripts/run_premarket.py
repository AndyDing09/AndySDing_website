#!/usr/bin/env python3
"""Pre-market run (§3.1): start at 7:00 ET.

Scans on the configured refresh, prints the ranked gapper table, freezes the
watchlist at 9:15 (immediately, if started late), runs the validation
checkpoint, and writes the 9:20 morning brief. Requires Alpaca PAPER keys
(secrets.local.ps1 / .env / environment — see `python -m src.data.secrets`).

Data honesty on the free IEX feed (the startup banner says so too):
- RVOL baseline = each symbol's real 30-day average daily volume scaled by the
  time-of-day fraction — an approximation, never a fabricated constant.
- Exchange comes from Alpaca's asset registry (real OTC exclusion), not a guess.
- Pre-market high/low are used only when today's daily bar is actually today's.
"""
import json
import os
import sys
import time as _time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alerts import AlertRouter                                   # noqa: E402
from src.checkpoints import validate_watchlist as vw                 # noqa: E402
from src.config import load_or_exit                                  # noqa: E402
from src.data.alpaca_client import AlpacaClients                     # noqa: E402
from src.data.clock import check_skew, minute_of_session, ny, ny_time, utc_now  # noqa: E402
from src.data.corp_actions import CorpActionsGuard                   # noqa: E402
from src.data.floats import (CrossValidatedFloat, FinnhubFloatProvider,  # noqa: E402
                             FMPFloatProvider, YFinanceFloatProvider)
from src.data.news import classify                                   # noqa: E402
from src.models import NewsItem, Regime                               # noqa: E402
from src.reporting.morning_brief import write_brief                  # noqa: E402
from src.scanners.gapper import (Snapshot, freeze_watchlist, render_table,  # noqa: E402
                                 scan, write_watchlist_json)
from src.scanners.regime import RegimeCall                            # noqa: E402

GUARDRAIL = ("Simulated (paper) trading for education and strategy validation. "
             "Not financial advice. Most day traders lose money.")

_EXCHANGE_MAP: dict[str, str] = {}
_BASELINE_CACHE: dict[str, float] = {}


def load_exchange_map(clients: AlpacaClients) -> dict[str, str]:
    """symbol -> real exchange from Alpaca's asset registry (once per run).
    This is what makes the §2.1 OTC exclusion real instead of assumed."""
    global _EXCHANGE_MAP
    if _EXCHANGE_MAP:
        return _EXCHANGE_MAP
    from alpaca.trading.enums import AssetClass, AssetStatus
    from alpaca.trading.requests import GetAssetsRequest
    assets = clients.trading.get_all_assets(GetAssetsRequest(
        status=AssetStatus.ACTIVE, asset_class=AssetClass.US_EQUITY))
    _EXCHANGE_MAP = {a.symbol: str(getattr(a.exchange, "value", a.exchange))
                     for a in assets if getattr(a, "tradable", False)}
    print(f"asset registry loaded: {len(_EXCHANGE_MAP)} tradable US equities")
    return _EXCHANGE_MAP


def session_fraction(now: datetime) -> float:
    """Fraction of the 390-minute session elapsed; pre-market clamps to 5% so a
    pre-open cumulative volume is compared against 5% of an average day."""
    return max(0.05, min(1.0, minute_of_session(now) / 390.0))


def load_volume_baselines(clients: AlpacaClients, symbols: list[str], cfg) -> dict[str, float]:
    """Real 30-day average daily volume per symbol (one batched request)."""
    missing = [s for s in symbols if s not in _BASELINE_CACHE]
    if missing:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        try:
            bars = clients.market.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=missing, timeframe=TimeFrame.Day,
                start=utc_now() - timedelta(days=45), feed=cfg.data.feed))
            data = getattr(bars, "data", {}) or {}
            for sym in missing:
                rows = data.get(sym, [])
                vols = [float(b.volume) for b in rows][-30:]
                _BASELINE_CACHE[sym] = (sum(vols) / len(vols)) if vols else 0.0
        except Exception as exc:
            print(f"warning: daily-volume baseline fetch failed ({exc}); "
                  f"affected symbols get rvol=0 (excluded, never faked)")
            for sym in missing:
                _BASELINE_CACHE.setdefault(sym, 0.0)
    return _BASELINE_CACHE


def fetch_news_batch(clients: AlpacaClients, symbols: list[str]) -> dict[str, list[NewsItem]]:
    """ONE news call for all pre-gated symbols (comma-joined), mapped back per
    symbol from each article's own symbol list — instead of a GET per name."""
    out: dict[str, list[NewsItem]] = {s: [] for s in symbols}
    if not symbols:
        return out
    try:
        from alpaca.data.historical.news import NewsClient
        from alpaca.data.requests import NewsRequest
        nc = NewsClient(clients.key, clients.secret)
        res = nc.get_news(NewsRequest(symbols=",".join(symbols), limit=50))
        articles = (getattr(res, "data", {}) or {}).get("news", [])
        for n in articles:
            ts = n.created_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            for sym in (n.symbols or []):
                if sym in out:
                    out[sym].append(classify(NewsItem(symbol=sym, ts=ts,
                                                      headline=n.headline,
                                                      source="benzinga")))
    except Exception as exc:
        print(f"warning: news fetch failed ({exc}) — catalysts unknown this cycle")
    return out


def premarket_stats_from_minute_bars(clients: AlpacaClients, symbols: list[str],
                                     cfg, now: datetime) -> dict[str, tuple]:
    """Fallback when the snapshot's daily bar isn't today's (a known premarket
    behavior on some feeds): derive premarket high/low/cumulative volume from
    today's 1-minute bars before 9:30 ET. One batched request."""
    out: dict[str, tuple] = {}
    if not symbols:
        return out
    try:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        start_et = ny(now).replace(hour=4, minute=0, second=0, microsecond=0)
        bars = clients.market.get_stock_bars(StockBarsRequest(
            symbol_or_symbols=symbols, timeframe=TimeFrame.Minute,
            start=start_et.astimezone(timezone.utc), feed=cfg.data.feed))
        data = getattr(bars, "data", {}) or {}
        open_et = start_et.replace(hour=9, minute=30)
        for sym in symbols:
            rows = [b for b in data.get(sym, []) if ny(b.timestamp) < open_et]
            if rows:
                out[sym] = (max(float(b.high) for b in rows),
                            min(float(b.low) for b in rows),
                            int(sum(float(b.volume) for b in rows)))
    except Exception as exc:
        print(f"warning: premarket minute-bar fallback failed: {exc}")
    return out


def fetch_snapshots(clients: AlpacaClients, cfg) -> list[Snapshot]:
    """Most-actives seed universe → snapshots → honest Snapshot rows.

    News is fetched ONLY for names that pass the cheap pre-gate (price band +
    gap floor) — ~a handful of API calls, not one per active."""
    from alpaca.data.historical.screener import ScreenerClient
    from alpaca.data.requests import MostActivesRequest, StockSnapshotRequest

    screener = ScreenerClient(clients.key, clients.secret)
    actives = screener.get_most_actives(MostActivesRequest(top=100))
    exchanges = load_exchange_map(clients)
    symbols = [a.symbol for a in getattr(actives, "most_actives", [])
               if a.symbol in exchanges]
    if not symbols:
        return []

    snaps_raw = clients.market.get_stock_snapshot(StockSnapshotRequest(
        symbol_or_symbols=symbols, feed=cfg.data.feed))
    now = utc_now()
    today_et = ny(now).date()
    frac = session_fraction(now)

    # Pass 1: cheap pre-gate (price band + gap floor) and today's-bar detection.
    pregated: list[tuple] = []          # (sym, last, prev_close, hi, lo, day_vol)
    need_fallback: list[str] = []
    for sym, s in (snaps_raw or {}).items():
        try:
            prev_close = float(s.previous_daily_bar.close) if s.previous_daily_bar else 0.0
            last = float(s.latest_trade.price) if s.latest_trade else 0.0
            daily = s.daily_bar
            daily_is_today = bool(daily and ny(daily.timestamp).date() == today_et)
            day_vol = int(daily.volume) if daily_is_today else 0
            hi = float(daily.high) if daily_is_today else None
            lo = float(daily.low) if daily_is_today else None
        except (AttributeError, TypeError):
            continue
        if not last or not prev_close:
            continue
        gap = (last - prev_close) / prev_close
        if not (cfg.universe.price_min <= last <= cfg.universe.price_max):
            continue
        if gap < cfg.scanners.gapper_min_gap_pct:
            continue
        if day_vol == 0:
            need_fallback.append(sym)   # snapshot daily bar stale/absent premarket
        pregated.append((sym, last, prev_close, hi, lo, day_vol))

    # Pass 2 (only for the handful that pre-gated): today's 1-min bars fill in
    # premarket high/low/volume when the snapshot's daily bar wasn't today's.
    fallback = premarket_stats_from_minute_bars(clients, need_fallback, cfg, now)
    baselines = load_volume_baselines(clients, [p[0] for p in pregated], cfg)
    news = fetch_news_batch(clients, [p[0] for p in pregated])

    out: list[Snapshot] = []
    for sym, last, prev_close, hi, lo, day_vol in pregated:
        if sym in fallback:
            hi, lo, day_vol = fallback[sym]
        baseline_cum = baselines.get(sym, 0.0) * frac    # time-of-day matched (§2.1)
        out.append(Snapshot(symbol=sym, exchange=exchanges.get(sym, "UNKNOWN"),
                            last=last, prior_close=prev_close, premkt_vol=day_vol,
                            premkt_high=hi, premkt_low=lo,
                            cum_vol_baseline=baseline_cum,
                            news=news.get(sym, [])))
    return out


def main() -> int:
    import logging
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
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

    while True:
        # A transient HTTP error at 7:30 must not kill the whole morning: guard
        # the scan cycle; only the freeze-write itself runs unguarded.
        try:
            snaps = fetch_snapshots(clients, cfg)
            now = utc_now()          # AFTER the fetch: the freeze can't slip a cycle
            cands = scan(snaps, cfg, floats, guard, now)
        except Exception as exc:
            print(f"scan cycle failed ({exc}) — retrying in "
                  f"{cfg.scanners.premarket_refresh_seconds}s")
            alerts.send("DATA", f"premarket scan cycle failed: {exc}")
            _time.sleep(cfg.scanners.premarket_refresh_seconds)
            continue

        if ny_time(now) >= cfg.scanners.watchlist_freeze:
            # Freeze immediately — also the late-start path (PC woke up at 9:20).
            raw = {s.symbol: s for s in snaps}
            frozen = freeze_watchlist(cands, cfg)
            write_watchlist_json(frozen, now, cfg.reports.dir)
            vw.run(frozen, raw, now, cfg.reports.dir)          # §5 checkpoint
            write_brief(frozen, RegimeCall(Regime.MIXED), now, cfg.reports.dir)
            if frozen:
                alerts.send("INFO", "watchlist frozen: "
                            + ", ".join(c.symbol for c in frozen))
                print(render_table(frozen))
            else:
                alerts.send("DATA", "watchlist frozen EMPTY — no qualifying gappers today")
                print("No qualifying gappers today — the session will start and stand down.")
            print("Frozen. run_session.py takes it from here (9:23 task).")
            return 0
        print(f"\n[{ny(now).strftime('%H:%M:%S')} ET] top gappers:")
        print(render_table(cands) if cands else "  (none qualifying yet)")
        _time.sleep(cfg.scanners.premarket_refresh_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
