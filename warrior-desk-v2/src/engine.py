"""The session engine — ONE pipeline for live and replay (§7.3).

scanner → strategy → risk gates → execution → journal, driven bar-by-bar.
Live trading feeds it stream events; the replay harness feeds it stored bars.
No wall clock (time comes from the data), no randomness: same input, same
signals, deterministically.

Order of operations per bar: manage the open position FIRST (this bar may stop
us out), then consider a new entry. One position per symbol at a time.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .config import Config
from .data.store import Store
from .execution.broker import Broker
from .execution.trailing import PositionManager
from .journal.journal import Journal
from .models import (Bar, Candidate, Fill, Position, Quote, Regime, Signal,
                     SignalStatus, TradeRecord)
from .risk.circuit_breakers import CircuitBreakers
from .risk.pipeline import run_gates
from .score import score_signal
from .strategies.base import MarketView, Strategy, ema_last
from .strategies.bull_flag import BullFlag
from .strategies.gap_and_go import GapAndGo
from .strategies.hod_continuation import HodContinuation
from .strategies.vwap_breakout import VwapBreakout

log = logging.getLogger("wd.engine")


def default_strategies(cfg: Config) -> list[Strategy]:
    # Fixed order = deterministic first-match precedence.
    return [GapAndGo(cfg), BullFlag(cfg), VwapBreakout(cfg), HodContinuation(cfg)]


@dataclass
class SymbolState:
    bars: list[Bar] = field(default_factory=list)
    hod: float = 0.0
    position: Optional[Position] = None
    entry_fill: Optional[Fill] = None
    open_signal: Optional[Signal] = None


class SessionEngine:
    def __init__(self, cfg: Config, broker: Broker, store: Store,
                 breakers: CircuitBreakers, candidates: dict[str, Candidate],
                 regime: Regime = Regime.MIXED, alert=None,
                 strategies: Optional[list[Strategy]] = None):
        self.cfg = cfg
        self.broker = broker
        self.store = store
        self.breakers = breakers
        self.candidates = {k.upper(): v for k, v in candidates.items()}
        self.regime = regime
        self.alert = alert or (lambda kind, msg: None)
        self.strategies = strategies or default_strategies(cfg)
        self.journal = Journal(store)
        self.pm = PositionManager(cfg.exits)
        self.state: dict[str, SymbolState] = {}
        self.signals: list[Signal] = []
        self.trades: list[TradeRecord] = []

    # ── the one entry point ──
    def on_bar(self, bar: Bar, quote: Optional[Quote] = None) -> None:
        st = self.state.setdefault(bar.symbol, SymbolState())
        st.bars.append(bar)
        st.hod = max(st.hod, bar.high)
        self.store.write_bar(bar)

        if st.position is not None:
            self._manage(st, bar, quote)
        if st.position is None and bar.symbol in self.candidates:
            self._consider_entry(st, bar, quote)

    # ── exits ──
    def _manage(self, st: SymbolState, bar: Bar, quote: Optional[Quote]) -> None:
        pos = st.position
        closes = [b.close for b in st.bars]
        decision = self.pm.on_bar(pos, bar, closes, bar.ts)
        if decision.action != "exit":
            return
        exit_fill = self.broker.exit_position(pos, decision.reason, bar.ts, quote)
        trade = self.journal.record_close(pos, st.entry_fill, exit_fill,
                                          st.open_signal, decision.reason, bar.ts)
        self.trades.append(trade)
        self.breakers.on_trade_closed(trade)
        self.alert("EXIT", f"{pos.symbol} {decision.reason} {trade.realized_r:+.2f}R "
                           f"({trade.pnl_usd:+.2f} USD)")
        st.position = st.entry_fill = st.open_signal = None

    # ── entries ──
    def _consider_entry(self, st: SymbolState, bar: Bar, quote: Optional[Quote]) -> None:
        cand = self.candidates[bar.symbol]
        view = MarketView(now=bar.ts, candidate=cand, bars_1m=st.bars, quote=quote,
                          hod=st.hod, premkt_high=cand.premkt_high,
                          premkt_low=cand.premkt_low, feed=bar.feed)
        for strat in self.strategies:
            sig = strat.detect(view)
            if sig is None:
                continue
            sig.regime = self.regime
            sig.float_band = self._float_band(cand)
            closes = [b.close for b in st.bars]
            e9 = ema_last(closes, 9)
            dist = abs(bar.close - e9) / bar.close if (e9 and bar.close) else None
            sc = score_signal(sig, cand, self.cfg.score, dist_to_9ema_pct=dist,
                              dilution_risk=cand.dilution_flag)
            outcome = run_gates(sig, self.cfg, self.breakers,
                                self.broker.account_equity(), bar.ts,
                                regime=self.regime, score=sc)
            self.signals.append(sig)
            if not outcome.tradeable:
                self.journal.record_signal(sig)      # journaled with its skip/reject status
                return                                # one verdict per bar per symbol
            pos = self.broker.submit_bracket(sig, bar.ts, quote)
            if pos is None:
                sig.status = SignalStatus.REJECTED
                sig.status_reason = "broker_submit_failed"
                self.journal.record_signal(sig)
                return
            # journal AFTER the submit so the persisted row carries the FINAL
            # status — the /explore-data checkpoint caught 'proposed' rows for
            # trades that actually filled.
            sig.status = SignalStatus.FILLED
            self.journal.record_signal(sig)
            st.position = pos
            st.entry_fill = self.broker.fills[-1] if hasattr(self.broker, "fills") else Fill(
                ts=bar.ts, symbol=sig.symbol, side="buy", qty=sig.shares,
                price=pos.entry, intended_price=sig.entry)
            st.open_signal = sig
            self.alert("FILL", f"{sig.symbol} {sig.setup.value} x{sig.shares} @ "
                               f"{pos.entry:.2f} stop {sig.stop:.2f} target {sig.target:.2f}"
                               f"{' (half size)' if outcome.half_size else ''}")
            return

    def _float_band(self, cand: Candidate) -> str:
        from .data.floats import float_band
        return float_band(cand.float_shares, self.cfg.universe.float_aplus,
                          self.cfg.universe.float_max)

    # ── out-of-band closes (server-side bracket fill sync, EOD flatten) ──
    def force_close(self, symbol: str, price: float, reason: str,
                    now: datetime) -> Optional[TradeRecord]:
        """Close our books for a position that ended outside the bar loop —
        a bracket leg that filled server-side, or the shutdown flatten. The
        price is the best approximation available and the reason says so."""
        st = self.state.get(symbol)
        if st is None or st.position is None:
            return None
        pos = st.position
        exit_fill = Fill(ts=now, symbol=symbol, side="sell", qty=pos.qty,
                         price=round(price, 4), intended_price=pos.target)
        trade = self.journal.record_close(pos, st.entry_fill, exit_fill,
                                          st.open_signal, reason, now)
        self.trades.append(trade)
        self.breakers.on_trade_closed(trade)
        if hasattr(self.broker, "drop_local"):
            self.broker.drop_local(symbol)
        self.alert("EXIT", f"{symbol} {reason} {trade.realized_r:+.2f}R "
                           f"({trade.pnl_usd:+.2f} USD)")
        st.position = st.entry_fill = st.open_signal = None
        return trade

    def last_close(self, symbol: str) -> float:
        st = self.state.get(symbol)
        return st.bars[-1].close if (st and st.bars) else 0.0

    # ── determinism receipt (§7.3) ──
    def signals_digest(self) -> str:
        """Stable hash over every signal's decision-relevant fields: identical
        input data ⇒ identical digest, byte for byte."""
        rows = [[s.ts.isoformat(), s.symbol, s.setup.value, round(s.entry, 4),
                 round(s.stop, 4), round(s.target, 4), s.shares, s.status.value,
                 s.status_reason] for s in self.signals]
        return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
