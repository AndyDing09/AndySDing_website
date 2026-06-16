"""The orchestrator (Sections 5 & 6).

Wires the gauntlet, the approval gate, execution, and the position manager into a
session loop that respects the trading windows. ``step(now)`` is one pass and is
fully driveable by a clock + data cursor (the backtest reuses it). The live
``run_agent`` loop just calls ``step`` on a poll interval.

Order of a pass: manage open positions (handle exits) -> check day-level halts ->
maybe enter a new position -> re-check halts. End-of-day flattens everything (no
overnight holds) and halts.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Callable, Optional

from .broker import Broker, SimBroker
from .config import Config
from .data.provider import AccountInfo, DataProvider
from .execution import ExecutionEngine
from .gauntlet import Gauntlet
from .indicators import atr_last
from .locks import LiveLockError, enforce_mode_locks
from .logging_setup import get_logger
from .models import SessionWindow
from .position_manager import PositionManager
from .sessions import (
    chart_timeframe, classify_window, in_allowed_session, now_et, past_hard_flat_time,
)
from .state import State

log = get_logger("engine")


class TradingEngine:
    def __init__(self, cfg: Config, provider: DataProvider, broker: Broker,
                 reasoner=None, journal=None, state: Optional[State] = None,
                 account: Optional[AccountInfo] = None, alerter=None):
        self.cfg = cfg
        self.provider = provider
        self.broker = broker
        self.journal = journal
        self.alerter = alerter
        self.gauntlet = Gauntlet(cfg, provider, reasoner=reasoner)
        self.execution = ExecutionEngine(cfg, broker, journal=journal, alerter=alerter)
        self.pm = PositionManager(cfg, broker, alerter=alerter)
        self.recent_proposals: list = []   # ring buffer for the website snapshot
        self.state = state or State.load(cfg.state_path)
        try:
            self.account = account or broker.get_account()
        except Exception as exc:
            log.warning("account fetch failed (%s); using a zeroed account.", exc)
            self.account = AccountInfo(status="UNKNOWN")

    # ── management ──
    def manage_open_positions(self, now: datetime) -> None:
        window = classify_window(now, self.cfg)
        tf = chart_timeframe(window, self.cfg)
        for sym in list(self.state.open_positions):
            pos = self.state.open_positions.get(sym)
            if pos is None:
                continue
            # Never trade into a halt; on resume the gauntlet re-runs from scratch.
            try:
                if self.provider.is_halted(sym):
                    log.warning("%s is HALTED — holding, no orders into a halt.", sym)
                    continue
            except Exception:
                pass
            try:
                bars = self.provider.get_bars(sym, tf, 60)
            except Exception as exc:
                log.warning("manage: bars fetch failed for %s: %s", sym, exc)
                continue
            if not bars:
                continue
            bar = bars[-1]
            actions = self.pm.decide(pos, bar, atr_last(bars))
            closed = self.pm.apply(pos, actions, self.state, now)
            if closed and self.journal is not None:
                self._safe(lambda: self.journal.record_close(closed))

    # ── entry ──
    def maybe_enter(self, now: datetime, approval_fn: Optional[Callable] = None) -> None:
        cfg, st = self.cfg, self.state
        if st.session_halted:
            return
        if st.open_count >= cfg.risk.max_concurrent_positions:
            return
        if st.trades_today >= cfg.risk.max_trades_per_day:
            return
        window = classify_window(now, cfg)
        if not in_allowed_session(window, cfg):
            return
        candidates = self.gauntlet.scan()
        for c in candidates:
            if c.symbol in st.open_positions:
                continue
            proposal = self.gauntlet.evaluate_symbol(c.symbol, self.account, st, now)
            self._record_recent(proposal)
            if proposal.tradeable and proposal.triggered:
                # The breakout is confirmed — take it.
                self.execution.execute(proposal, st, now, approval_fn=approval_fn)
                return  # one entry attempt per pass
            if proposal.tradeable and not proposal.triggered:
                # A valid setup that hasn't broken out yet — watch, don't chase.
                log.debug("%s: setup ready, waiting for the breakout trigger.", c.symbol)
                continue
            # Only journal *meaningful* rejections (a real pattern that failed a
            # gate) — not every polling tick where nothing was setting up.
            if self.journal is not None and self._pattern_valid(proposal):
                self._safe(lambda p=proposal: self.journal.record_proposal(p))

    @staticmethod
    def _pattern_valid(proposal) -> bool:
        from .models import StepStatus
        return any(s.number == 6 and s.status == StepStatus.PASS for s in proposal.steps)

    # ── website snapshot ──
    def _record_recent(self, proposal, limit: int = 12) -> None:
        """Keep the latest proposal per symbol for the website to display."""
        self.recent_proposals = [p for p in self.recent_proposals if p.symbol != proposal.symbol]
        self.recent_proposals.append(proposal)
        self.recent_proposals = self.recent_proposals[-limit:]

    def evaluate_for_display(self, symbol: str, now: datetime) -> None:
        """Run the gauntlet on an on-demand (website-requested) ticker. Display
        only — never executes."""
        try:
            p = self.gauntlet.evaluate_symbol(symbol, self.account, self.state, now,
                                              short_circuit=False)
            self._record_recent(p)
        except Exception as exc:
            log.warning("evaluate_for_display(%s) failed: %s", symbol, exc)

    def build_snapshot(self, now: datetime, mode_label: str) -> dict:
        from .publish import build_snapshot
        window = classify_window(now, self.cfg)
        session = {
            "window": window.value, "halted": self.state.session_halted,
            "halt_reason": self.state.halt_reason, "day_pnl": round(self.state.day_pnl, 2),
            "trades_today": self.state.trades_today,
            "consecutive_losses": self.state.consecutive_losses,
            "open_positions": self.state.open_count,
        }
        try:
            watchlist = self.gauntlet.scan()
        except Exception:
            watchlist = []
        alerts = self.alerter.history if self.alerter is not None else []
        return build_snapshot(
            self.cfg, mode=mode_label, account_equity=self.account.equity, session=session,
            watchlist=watchlist, proposals=list(self.recent_proposals),
            open_positions=list(self.state.open_positions.values()),
            journal=self.journal, alerts=alerts)

    # ── halts ──
    def check_day_halts(self, now: datetime) -> None:
        r, st = self.cfg.risk, self.state
        if st.session_halted:
            return
        if st.day_pnl <= -r.max_daily_loss:
            self.flatten_all(now, "daily loss cap hit")
            st.halt(f"daily loss cap hit (P&L ${st.day_pnl:.2f})")
        elif st.consecutive_losses >= r.consecutive_loss_halt:
            self.flatten_all(now, "two consecutive losses")
            st.halt(f"{st.consecutive_losses} consecutive losses — no more trading today")

    def flatten_all(self, now: datetime, reason: str) -> None:
        for sym in list(self.state.open_positions):
            pos = self.state.open_positions.get(sym)
            if not pos:
                continue
            try:
                q = self.provider.get_quote(sym)
                price = q.mid if q else pos.avg_entry
            except Exception:
                price = pos.avg_entry
            closed = self.pm.flatten(pos, price, self.state, now, reason)
            if closed and self.journal is not None:
                self._safe(lambda: self.journal.record_close(closed))

    # ── one pass ──
    def step(self, now: datetime, approval_fn: Optional[Callable] = None) -> None:
        self.state.start_session(now.date())
        if self.state.session_halted:
            return
        if past_hard_flat_time(now, self.cfg) and self.state.open_positions:
            self.flatten_all(now, "EOD hard flat — no overnight holds")
        if past_hard_flat_time(now, self.cfg):
            if not self.state.session_halted:
                self.state.halt("end of day — flattened, done trading")
            return
        # Managing exits is more important than entering; isolate failures so a
        # transient data glitch in one phase never spams orders or crashes the loop.
        try:
            self.manage_open_positions(now)
            self.check_day_halts(now)
        except Exception as exc:
            log.exception("manage phase failed this pass: %s", exc)
        try:
            self.maybe_enter(now, approval_fn)
            self.check_day_halts(now)
        except Exception as exc:
            log.exception("entry phase failed this pass: %s", exc)

    def _safe(self, fn) -> None:
        try:
            fn()
        except Exception as exc:
            log.warning("journal hook failed: %s", exc)


def _build_runtime(cfg: Config, demo: bool, equity: float, advisory: bool = False):
    """Return (provider, broker, account, approval_fn, now_fn, simulated)."""
    from .broker import ManualBroker

    # ── live data provider ──
    if demo:
        from .demo import DEMO_NOW, DemoProvider
        provider, now_fn = DemoProvider(), (lambda: DEMO_NOW)
    elif cfg.secrets.has_alpaca:
        from .data import build_scan_sources
        from .data.alpaca_provider import AlpacaProvider
        scanner, float_source = build_scan_sources(cfg)
        provider = AlpacaProvider(cfg.secrets.alpaca_api_key, cfg.secrets.alpaca_secret_key,
                                  mode="paper", float_source=float_source, scanner=scanner)
        now_fn = lambda: now_et(cfg)
    else:
        raise SystemExit("No Alpaca keys and --demo not set. Try: warrior run --demo --once")

    # ── broker + account ──
    if advisory:
        # Advisory: NO API is called for execution. Size off your real (e.g.
        # Firstrade) equity via --equity so alerted share counts match reality.
        acct = AccountInfo(equity=equity, cash=equity, buying_power=equity,
                           status="ADVISORY", mode="advisory")
        return provider, ManualBroker(acct), acct, (lambda _p: True), now_fn, True
    if demo:
        acct = AccountInfo(equity=equity, cash=equity, buying_power=equity,
                           status="SIMULATED", mode="paper")
        return provider, SimBroker(acct), acct, (lambda _p: True), now_fn, True
    # real Alpaca paper (or live, once unlocked) execution
    from .broker import AlpacaBroker
    mode = "live" if cfg.is_live else "paper"
    broker = AlpacaBroker(cfg.secrets.alpaca_api_key, cfg.secrets.alpaca_secret_key, mode=mode)
    try:
        acct = broker.get_account()
        sim = False
    except Exception:
        acct = AccountInfo(equity=equity, buying_power=equity, status="SIMULATED")
        sim = True
    return provider, broker, acct, None, now_fn, sim


def require_graduation(cfg: Config):
    """Decline live until the PAPER track record clears the graduation gate
    (Ross steps 4–7). Raises LiveLockError with what's still missing."""
    from pathlib import Path
    from .stats import compute_stats, graduation_status, read_closed_trades
    closed = read_closed_trades(str(Path(cfg.journal_dir) / "closed_trades.csv"))
    grad = graduation_status(cfg, compute_stats(closed))
    if not grad.eligible:
        raise LiveLockError(
            "Live trading declined — your PAPER track record hasn't cleared the graduation gate:\n"
            + "\n".join(f"  - {m}" for m in grad.missing)
            + "\n\nKeep paper trading and run 'warrior stats'. The discipline is the edge.")
    return grad


def run_agent(cfg: Config, demo: bool = False, once: bool = False, equity: float = 30_000.0,
              advisory: bool = False, sound: bool = True) -> int:
    # The mode locks are the gate to live. demo/advisory are never live. A real
    # live run must FIRST clear the paper graduation gate, then satisfy every §0
    # lock (incl. the typed confirmation) — or this raises and refuses to start.
    if not demo and not advisory:
        if cfg.is_live:
            require_graduation(cfg)
        enforce_mode_locks(cfg, interactive=True)
    from .alerts import Alerter
    from .reasoning import make_reasoner
    provider, broker, account, approval_fn, now_fn, simulated = _build_runtime(
        cfg, demo, equity, advisory)
    journal = None
    try:
        from .journal import JournalManager
        journal = JournalManager(cfg)
    except Exception as exc:  # journal must never block trading
        log.warning("journal unavailable (%s); continuing without it.", exc)

    alerter = Alerter(sound=sound, broker_name=cfg.manual_broker_name)
    reasoner = make_reasoner(cfg, cfg.secrets)
    engine = TradingEngine(cfg, provider, broker, reasoner=reasoner, journal=journal,
                           account=account, alerter=alerter)

    if advisory:
        log.info("ADVISORY run: NO orders sent anywhere — the agent alerts you live to "
                 "ENTER/SCALE/EXIT; place each by hand in %s.", cfg.manual_broker_name)
        print(f"\nADVISORY MODE — live signals only, sized off ${account.equity:,.0f} equity. "
              f"Place every alerted order by hand in {cfg.manual_broker_name}.\n")
    elif demo:
        log.info("DEMO run: non-interactive auto-approve; SIMULATED account.")

    mode_label = "advisory" if advisory else cfg.trading_mode

    if once:
        engine.step(now_fn(), approval_fn=approval_fn)
        _handle_requests(cfg, engine, now_fn())
        _publish_safe(cfg, engine, now_fn(), mode_label)
        _report(engine, simulated)
        if journal is not None:
            engine._safe(lambda: journal.write_daily_summary(engine.state))
        return 0

    log.info("Starting the agent loop (mode=%s). Ctrl-C to stop.", mode_label)
    errors = 0
    try:
        while True:
            now = now_fn()
            try:
                engine.step(now, approval_fn=approval_fn)
                _handle_requests(cfg, engine, now)   # on-demand tickers from the website
                errors = 0
            except Exception as exc:
                # Never spam orders on a glitch — back off exponentially.
                errors += 1
                backoff = min(cfg.poll_seconds * (2 ** errors), 300)
                log.exception("pass failed (%d in a row); backing off %ds: %s", errors, backoff, exc)
                if errors >= 8:
                    log.error("too many consecutive failures — stopping the loop.")
                    break
                time.sleep(backoff)
                continue
            _publish_safe(cfg, engine, now, mode_label)   # keep the website tab fresh
            if engine.state.session_halted:
                log.info("Session halted (%s). Stopping.", engine.state.halt_reason)
                break
            if classify_window(now, cfg) == SessionWindow.CLOSED:
                log.info("Market closed. Stopping.")
                break
            time.sleep(max(1, cfg.poll_seconds))
    except KeyboardInterrupt:
        log.info("Interrupted by Operator.")
    _publish_safe(cfg, engine, now_fn(), mode_label)
    _report(engine, simulated)
    if journal is not None:
        engine._safe(lambda: journal.write_daily_summary(engine.state))
    return 0


def _handle_requests(cfg: Config, engine: TradingEngine, now: datetime) -> None:
    if not cfg.secrets.publish_url:
        return
    try:
        from .publish import fetch_requests
        for sym in fetch_requests(cfg):
            engine.evaluate_for_display(sym, now)
    except Exception as exc:
        log.debug("request handling failed: %s", exc)


def _publish_safe(cfg: Config, engine: TradingEngine, now: datetime, mode_label: str) -> None:
    if not cfg.secrets.publish_url:
        return
    try:
        from .publish import publish_snapshot
        ok, msg = publish_snapshot(cfg, engine.build_snapshot(now, mode_label))
        if not ok:
            log.debug("publish: %s", msg)
    except Exception as exc:
        log.debug("publish failed: %s", exc)


def _report(engine: TradingEngine, simulated: bool) -> None:
    st = engine.state
    print(f"\nPASS COMPLETE — day P&L ${st.day_pnl:.2f}, trades {st.trades_today}, "
          f"open {st.open_count}, halted={st.session_halted}"
          f"{' (SIMULATED)' if simulated else ''}")
