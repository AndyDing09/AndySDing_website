"""Historical replay through the IDENTICAL gauntlet (Section 11, M6).

Replays bars one candle at a time: set the data cursor, advance the clock to the
bar's timestamp, and call ``engine.step`` — the very same gauntlet, risk engine,
approval path (auto in a sim), and position manager used live. No orders are ever
sent; a SimBroker fills deterministically.

Results go to a SEPARATE journal/state so a backtest never contaminates the paper
track record that feeds the graduation gate.
"""

from __future__ import annotations

import csv
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .broker import SimBroker
from .catalysts import classify_catalyst
from .config import Config
from .data.provider import AccountInfo, FloatInfo
from .data.synthetic import SyntheticProvider
from .engine import TradingEngine
from .logging_setup import get_logger
from .models import Bar, Candidate, Quote
from .reasoning import TemplateReasoner
from .state import State
from .stats import compute_stats, read_closed_trades

log = get_logger("backtest")


class ReplayProvider(SyntheticProvider):
    """SyntheticProvider that also serves a synthesized daily history (so the
    daily-strength + liquidity checks have data) and a live-derived quote."""

    def __init__(self, symbol: str, intraday: list[Bar], daily: list[Bar],
                 catalyst_headline: Optional[str] = None, float_shares: Optional[float] = None,
                 baseline: float = 0.0):
        sym = symbol.upper()
        news = {sym: [classify_catalyst(catalyst_headline, "backtest")]} if catalyst_headline else {}
        floats = {sym: FloatInfo(float_shares, verified=True, source="backtest")} if float_shares else {}
        super().__init__(bars={sym: intraday}, news=news,
                         movers=[Candidate(sym, price=intraday[-1].close if intraday else 0.0)],
                         floats=floats, baselines={sym: baseline} if baseline else {})
        self._daily = daily
        self._sym = sym

    def get_bars(self, symbol, timeframe, limit=200):
        if timeframe == "1Day":
            return self._daily[-limit:]
        return super().get_bars(symbol, timeframe, limit)

    def get_quote(self, symbol):
        bars = self.visible_bars(symbol)
        if bars:
            c = bars[-1].close
            return Quote(bid=round(c - 0.01, 4), ask=round(c + 0.01, 4))
        return super().get_quote(symbol)


def load_bars_csv(path: str) -> list[Bar]:
    out: list[Bar] = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                ts = row.get("ts") or row.get("timestamp") or row.get("t")
                out.append(Bar(ts=datetime.fromisoformat(ts) if ts else datetime.now(),
                               open=float(row["open"]), high=float(row["high"]),
                               low=float(row["low"]), close=float(row["close"]),
                               volume=float(row.get("volume", row.get("v", 0)))))
            except (KeyError, ValueError):
                continue
    return out


def _synth_daily_from_intraday(intraday: list[Bar], days: int = 210) -> list[Bar]:
    """Build a plausible rising daily history below the current price so the daily
    chart reads 'strong' and liquidity has data. Clearly synthetic."""
    if not intraday:
        return []
    last = intraday[-1].close
    vol = sum(b.volume for b in intraday) or 1_000_000
    out = []
    base = max(0.5, last * 0.4)
    step = (last * 0.9 - base) / max(1, days)
    for i in range(days):
        c = base + i * step
        out.append(Bar(ts=intraday[0].ts - timedelta(days=days - i),
                       open=c - 0.02, high=c + 0.05, low=c - 0.05, close=c, volume=vol))
    return out


def run_backtest(cfg: Config, args) -> int:
    symbol = (args.symbol or "WARR").upper()

    if getattr(args, "demo", False) or not getattr(args, "bars", None):
        from .demo import demo_backtest_provider
        provider = demo_backtest_provider(symbol if args.symbol else "WARR")
        symbol = provider._sym
        full = list(provider._bars[symbol])
        print(f"Backtest (DEMO): replaying {len(full)} candles of {symbol} through the gauntlet.")
    else:
        intraday = load_bars_csv(args.bars)
        if not intraday:
            print(f"No bars loaded from {args.bars} (expected CSV with ts,open,high,low,close,volume).")
            return 1
        provider = ReplayProvider(symbol, intraday, _synth_daily_from_intraday(intraday),
                                  catalyst_headline=f"{symbol} backtest catalyst",
                                  float_shares=10_000_000,
                                  baseline=(sum(b.volume for b in intraday) / max(1, len(intraday))))
        full = intraday
        print(f"Backtest: replaying {len(full)} candles of {symbol} from {args.bars}.")

    # Isolated journal + state so the paper track record is untouched.
    bt_journal_dir = str(Path(cfg.journal_dir) / "backtest")
    cfg.journal_dir = bt_journal_dir
    equity = getattr(args, "equity", 30_000.0)
    account = AccountInfo(equity=equity, cash=equity, buying_power=equity, status="BACKTEST")
    broker = SimBroker(account)
    from .journal import JournalManager
    journal = JournalManager(cfg)
    state = State(path=str(Path(tempfile.gettempdir()) / "warrior_backtest_state.json"))
    if Path(state.path).exists():
        Path(state.path).unlink()
    state = State(path=state.path)

    engine = TradingEngine(cfg, provider, broker, reasoner=TemplateReasoner(),
                           journal=journal, state=state, account=account)

    last_now = full[0].ts if full else datetime.now()
    for i in range(len(full)):
        provider.set_cursor(symbol, i)
        last_now = full[i].ts
        engine.step(last_now, approval_fn=lambda _p: True)

    # Safety: flatten anything still open at the end of the replay.
    if state.open_positions:
        engine.flatten_all(last_now, "backtest end — flatten")

    journal_summary = journal.render_today_summary(date_iso=last_now.date().isoformat(), state=state)

    closed = read_closed_trades(str(Path(bt_journal_dir) / "closed_trades.csv"))
    s = compute_stats(closed, starting_equity=equity)
    pf = "n/a" if s.profit_factor is None else f"{s.profit_factor:.2f}"
    print("\n=== BACKTEST RESULT (sim — NO orders were sent) ===")
    for t in closed:
        print(f"  {t['symbol']}: {t['entry']}->{t['exit']} x{t['qty']}  "
              f"P&L ${float(t['gross_pnl']):.2f} ({float(t['r_multiple']):+.2f}R)  [{t['exit_reason']}]")
    print(f"  trades {s.n} ({s.wins}W/{s.losses}L) | win rate {s.win_rate:.0%} | "
          f"expectancy ${s.expectancy:.2f} ({s.expectancy_r:+.2f}R) | profit factor {pf} | "
          f"P&L ${s.total_pnl:.2f}")
    print(f"\n{journal_summary}")
    print(f"\nBacktest journal written to {bt_journal_dir}/  (kept separate from paper stats).")
    print("Backtests do NOT count toward the paper->live graduation gate.")
    return 0
