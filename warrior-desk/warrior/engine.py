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
from .locks import enforce_mode_locks
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
                 account: Optional[AccountInfo] = None):
        self.cfg = cfg
        self.provider = provider
        self.broker = broker
        self.journal = journal
        self.gauntlet = Gauntlet(cfg, provider, reasoner=reasoner)
        self.execution = ExecutionEngine(cfg, broker, journal=journal)
        self.pm = PositionManager(cfg, broker)
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
        self.manage_open_positions(now)
        self.check_day_halts(now)
        self.maybe_enter(now, approval_fn)
        self.check_day_halts(now)

    def _safe(self, fn) -> None:
        try:
            fn()
        except Exception as exc:
            log.warning("journal hook failed: %s", exc)


def _build_runtime(cfg: Config, demo: bool, equity: float):
    """Return (provider, broker, account, approval_fn, now_fn, simulated)."""
    if demo:
        from .demo import DEMO_NOW, DemoProvider
        acct = AccountInfo(equity=equity, cash=equity, buying_power=equity,
                           status="SIMULATED", mode="paper")
        return DemoProvider(), SimBroker(acct), acct, (lambda _p: True), (lambda: DEMO_NOW), True
    if cfg.secrets.has_alpaca:
        from .broker import AlpacaBroker
        from .data.alpaca_provider import AlpacaProvider
        from .data.float_source import UnknownFloatSource
        mode = "live" if cfg.is_live else "paper"
        prov = AlpacaProvider(cfg.secrets.alpaca_api_key, cfg.secrets.alpaca_secret_key,
                              mode="paper", float_source=UnknownFloatSource())
        broker = AlpacaBroker(cfg.secrets.alpaca_api_key, cfg.secrets.alpaca_secret_key, mode=mode)
        try:
            acct = broker.get_account()
            sim = False
        except Exception:
            acct = AccountInfo(equity=equity, buying_power=equity, status="SIMULATED")
            sim = True
        return prov, broker, acct, None, (lambda: now_et(cfg)), sim
    raise SystemExit("No Alpaca keys and --demo not set. Try: warrior run --demo --once")


def run_agent(cfg: Config, demo: bool = False, once: bool = False, equity: float = 30_000.0) -> int:
    # The mode locks are the gate to live. demo is always paper; a real live run
    # must clear every §0 lock (incl. the typed confirmation) or this raises.
    enforce_mode_locks(cfg, interactive=True)
    from .reasoning import make_reasoner
    provider, broker, account, approval_fn, now_fn, simulated = _build_runtime(cfg, demo, equity)
    journal = None
    try:
        from .journal import JournalManager
        journal = JournalManager(cfg)
    except Exception as exc:  # journal must never block trading
        log.warning("journal unavailable (%s); continuing without it.", exc)

    reasoner = make_reasoner(cfg, cfg.secrets)
    engine = TradingEngine(cfg, provider, broker, reasoner=reasoner, journal=journal, account=account)

    if demo:
        log.info("DEMO run: non-interactive auto-approve; SIMULATED account.")

    if once:
        engine.step(now_fn(), approval_fn=approval_fn)
        _report(engine, simulated)
        if journal is not None:
            engine._safe(lambda: journal.write_daily_summary(engine.state))
        return 0

    log.info("Starting the agent loop (mode=%s). Ctrl-C to stop.", cfg.trading_mode)
    try:
        while True:
            now = now_fn()
            engine.step(now, approval_fn=approval_fn)
            if engine.state.session_halted:
                log.info("Session halted (%s). Stopping.", engine.state.halt_reason)
                break
            if classify_window(now, cfg) == SessionWindow.CLOSED:
                log.info("Market closed. Stopping.")
                break
            time.sleep(max(1, cfg.poll_seconds))
    except KeyboardInterrupt:
        log.info("Interrupted by Operator.")
    _report(engine, simulated)
    if journal is not None:
        engine._safe(lambda: journal.write_daily_summary(engine.state))
    return 0


def _report(engine: TradingEngine, simulated: bool) -> None:
    st = engine.state
    print(f"\nPASS COMPLETE — day P&L ${st.day_pnl:.2f}, trades {st.trades_today}, "
          f"open {st.open_count}, halted={st.session_halted}"
          f"{' (SIMULATED)' if simulated else ''}")
