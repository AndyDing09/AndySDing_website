"""The 12-step pre-trade gauntlet (Section 4).

Each step records PASS / FAIL / INFO with a reason and the metrics it used, so the
journal shows the full reasoning — fills and skips alike. Any hard FAIL ends the
trade (the engine short-circuits; ``warrior propose`` walks the whole way for
teaching value, marking dependent steps SKIP). The deterministic risk engine has
the final say at step 11; nothing here can talk it out of a rejection.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .catalysts import best_catalyst
from .config import Config
from .data.provider import AccountInfo, DataProvider
from .grading import grade_setup
from .indicators import (
    atr_last, ema_last, macd, pct_from, rsi_last, rvol as rvol_calc, vwap_last,
)
from .logging_setup import get_logger
from .models import (
    Bar, GauntletStep, Grade, PatternKind, RiskDecision, SessionWindow, Side,
    StepStatus, TradeProposal,
)
from .patterns import detect_pattern
from .risk import RiskContext, RiskEngine
from .selection import (
    catalyst_criterion, daily_strength, float_criterion, rank_candidates, rvol_criterion,
)
from .sessions import chart_timeframe, classify_window, in_allowed_session
from .sizing import size_position

log = get_logger("gauntlet")


def _macd_state(line, signal) -> str:
    if line is None or signal is None:
        return "n/a"
    if line > signal and line > 0:
        return "bullish (line>signal, >0)"
    if line > signal:
        return "improving (line>signal)"
    return "bearish (line<=signal)"


def _rsi_state(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    if v >= 70:
        return f"{v:.0f} overbought/extended"
    if v <= 30:
        return f"{v:.0f} oversold"
    return f"{v:.0f} neutral"


def _session_fraction(now: datetime) -> float:
    """Fraction of the 390-minute RTH session elapsed (for approximating RVOL)."""
    minutes = (now.hour - 9) * 60 + (now.minute - 30)
    if minutes <= 0:
        return 0.05
    return max(0.05, min(1.0, minutes / 390.0))


class Gauntlet:
    def __init__(self, cfg: Config, provider: DataProvider, reasoner=None):
        self.cfg = cfg
        self.provider = provider
        self.reasoner = reasoner
        self.risk = RiskEngine(cfg)

    # ── Step 2 helper, also used by `warrior watchlist` ──
    def scan(self, limit: int = 20):
        return rank_candidates(self.provider.get_movers(limit))

    def _rvol(self, intraday: list[Bar], daily: list[Bar], tf: str, symbol: str,
              now: datetime) -> tuple[float, bool]:
        """Return (rvol, approximate?)."""
        today_vol = sum(b.volume for b in intraday)
        baseline = self.provider.baseline_volume(symbol, tf)
        if baseline > 0:
            return rvol_calc(today_vol, baseline), False
        if len(daily) >= 5:
            avg_daily = sum(b.volume for b in daily[-20:]) / len(daily[-20:])
            expected = avg_daily * _session_fraction(now)
            return rvol_calc(today_vol, expected), True
        return 0.0, True

    def evaluate_symbol(
        self,
        symbol: str,
        account: AccountInfo,
        state,
        now: datetime,
        short_circuit: bool = True,
        watchlist_rank: Optional[int] = None,
    ) -> TradeProposal:
        symbol = symbol.upper()
        cfg = self.cfg
        steps: list[GauntletStep] = []
        m: dict = {}
        p = TradeProposal(symbol=symbol, side=Side.LONG, mode=cfg.trading_mode, created_at=now)
        aborted: list[str] = []

        def add(n, name, status, detail="", score=None, metrics=None):
            steps.append(GauntletStep(n, name, status, detail, score, metrics or {}))

        def skip_rest(from_step: int, reason: str):
            names = {
                7: "Define entry trigger", 8: "Define stop", 9: "Targets & R:R",
                10: "Position sizing", 11: "Risk-gate sweep", 12: "Proposal",
            }
            for k in range(from_step, 13):
                if k in names:
                    add(k, names[k], StepStatus.SKIP, f"skipped: {reason}")

        # ── Step 1: Session & regime ──
        window = classify_window(now, cfg)
        allowed = in_allowed_session(window, cfg)
        tf = chart_timeframe(window, cfg) if window in (SessionWindow.PRIME, SessionWindow.MIDDAY) else cfg.timeframe_prime
        p.session_window = window
        s1 = StepStatus.PASS if allowed else StepStatus.FAIL
        add(1, "Session & regime", s1,
            f"{window.value} window; trading {'allowed' if allowed else 'NOT allowed'}; chart {tf}",
            metrics={"session_window": window.value, "timeframe": tf})
        if not allowed:
            aborted.append(f"outside an allowed trading session ({window.value})")

        # ── gather data ──
        try:
            intraday = self.provider.get_bars(symbol, tf, 120)
        except Exception as exc:
            intraday = []
            log.warning("bars fetch failed for %s: %s", symbol, exc)
        try:
            daily = self.provider.get_bars(symbol, "1Day", 220)
        except Exception:
            daily = []
        quote = None
        try:
            quote = self.provider.get_quote(symbol)
        except Exception:
            pass
        try:
            news = self.provider.get_news(symbol, 10)
        except Exception:
            news = []
        fi = self.provider.get_float(symbol)
        catalyst = best_catalyst(news)

        price = quote.mid if quote else (intraday[-1].close if intraday else 0.0)
        closes = [b.close for b in intraday]
        e9 = ema_last(closes, 9)
        e20 = ema_last(closes, 20)
        e200 = ema_last(closes, 200)
        vwap_v = vwap_last(intraday)
        macd_line, macd_sig, macd_hist = macd(closes)
        rsi_v = rsi_last(closes)
        atr_v = atr_last(intraday)
        hod = max((b.high for b in intraday), default=0.0)
        prior_close = daily[-2].close if len(daily) >= 2 else None
        avg_daily_vol = (sum(b.volume for b in daily[-20:]) / len(daily[-20:])) if daily else 0.0
        avg_dollar_volume = avg_daily_vol * price
        rvol, rvol_approx = self._rvol(intraday, daily, tf, symbol, now)

        m.update({
            "price": round(price, 4), "rvol": rvol, "rvol_approx": rvol_approx,
            "spread": quote.spread if quote else None,
            "ema9": e9, "ema20": e20, "ema200": e200, "vwap": vwap_v,
            "pct_from_9ema": pct_from(price, e9) if e9 else None,
            "pct_from_vwap": pct_from(price, vwap_v) if vwap_v else None,
            "macd_state": _macd_state(macd_line[-1] if macd_line else None,
                                      macd_sig[-1] if macd_sig else None),
            "rsi": rsi_v, "rsi_state": _rsi_state(rsi_v), "atr": atr_v,
            "hod": round(hod, 4), "prior_close": prior_close,
            "avg_dollar_volume": round(avg_dollar_volume, 0),
            "float": fi.shares, "float_verified": fi.verified,
        })
        if catalyst and catalyst.present:
            m.update({
                "catalyst": catalyst.classification,
                "catalyst_material": catalyst.material,
                "catalyst_headline": catalyst.headline,
                "catalyst_source": catalyst.source,
                "catalyst_ts": catalyst.ts.isoformat() if catalyst.ts else None,
            })
        else:
            m["catalyst"] = None

        # ── Step 2: Scan & watchlist context ──
        add(2, "Scan & watchlist", StepStatus.INFO,
            f"rank #{watchlist_rank}" if watchlist_rank else "evaluated on demand",
            metrics={"watchlist_rank": watchlist_rank})

        # ── Step 3: Four-criteria qualification ──
        c_float = float_criterion(fi, cfg)
        c_rvol = rvol_criterion(rvol, cfg)
        c_daily = daily_strength(daily, price)
        c_cat = catalyst_criterion(catalyst)
        crit_metrics = {}
        for c in (c_float, c_rvol, c_daily, c_cat):
            crit_metrics.update(c.metrics)
        hard_fail_crit = [c for c in (c_float, c_rvol, c_daily, c_cat) if c.hard_fail]
        price_ok = cfg.selection.min_price <= price <= cfg.selection.max_price
        crit_fail = bool(hard_fail_crit) or not price_ok
        crit_detail = " | ".join(c.detail for c in (c_float, c_rvol, c_daily, c_cat))
        if not price_ok:
            crit_detail += f" | price ${price:.2f} outside [{cfg.selection.min_price},{cfg.selection.max_price}]"
        add(3, "Four-criteria qualification", StepStatus.FAIL if crit_fail else StepStatus.PASS,
            crit_detail, score=round(sum(c.score for c in (c_float, c_rvol, c_daily, c_cat)), 2),
            metrics=crit_metrics)
        if crit_fail:
            reasons = [c.detail for c in hard_fail_crit]
            if not price_ok:
                reasons.append(f"price ${price:.2f} out of range")
            aborted.append("; ".join(reasons))

        # ── Step 4: Catalyst verification ──
        if catalyst and catalyst.present:
            add(4, "Catalyst verification", StepStatus.INFO,
                f"{catalyst.classification} ({'material' if catalyst.material else 'soft'}): "
                f"\"{catalyst.headline[:90]}\" — {catalyst.source}"
                + (f" @ {catalyst.ts.isoformat()}" if catalyst.ts else ""),
                metrics={"catalyst": catalyst.classification})
        else:
            add(4, "Catalyst verification", StepStatus.INFO,
                "no material news — clean technical setup (downgraded)", metrics={"catalyst": None})

        # ── Step 5: Multi-timeframe read ──
        add(5, "Multi-timeframe read", StepStatus.INFO,
            f"price {price:.2f} | VWAP {vwap_v if vwap_v else 'n/a'} | 9-EMA {e9} | "
            f"20-EMA {e20} | 200-EMA {e200} | HOD {hod:.2f} | prior close {prior_close} | "
            f"MACD {m['macd_state']} | RSI {m['rsi_state']} | ATR {atr_v}",
            metrics={k: m[k] for k in ("vwap", "ema9", "ema20", "ema200", "hod",
                                       "prior_close", "macd_state", "rsi", "atr")})

        # ── Step 6: Pattern ID ──
        pattern = detect_pattern(intraday, cfg, ema9=e9, vwap=vwap_v)
        m["pattern"] = pattern.kind.value
        m["retrace_pct"] = pattern.retrace_pct
        m["vwap_held"] = pattern.holds_vwap
        p.pattern = pattern.kind
        if pattern.valid:
            add(6, "Pattern ID", StepStatus.PASS, "; ".join(pattern.reasons),
                metrics={"pattern": pattern.kind.value, "retrace_pct": pattern.retrace_pct,
                         "holds_9ema": pattern.holds_9ema, "holds_vwap": pattern.holds_vwap,
                         "pullback_len": pattern.pullback_len})
        else:
            add(6, "Pattern ID", StepStatus.FAIL,
                "; ".join(pattern.reasons) or "no clean bull flag / flat top",
                metrics={"pattern": pattern.kind.value})
            aborted.append("no clean bull flag / flat top")

        # If a hard fail already happened and we short-circuit, stop here.
        if aborted and short_circuit:
            return self._finalize_rejected(p, steps, m, aborted)
        if not pattern.valid:
            skip_rest(7, "no valid pattern")
            return self._finalize_rejected(p, steps, m, aborted)

        # ── Step 7: Define entry trigger ──
        entry = round(pattern.trigger_price, 4)
        add(7, "Define entry trigger", StepStatus.PASS,
            f"limit at/just above {entry:.2f} (max chase ${cfg.risk.max_chase:.2f}); "
            f"confirm with volume >= {pattern.confirm_volume:.0f}"
            + (" — breakout already fired" if pattern.triggered else " — not yet triggered"),
            metrics={"entry_trigger": entry, "confirm_volume": pattern.confirm_volume,
                     "triggered": pattern.triggered})

        # ── Step 8: Define stop ──
        stop = round(pattern.pullback_low, 4)
        stop_distance = round(entry - stop, 4)
        wide = stop_distance > cfg.risk.mechanical_stop_distance
        if wide and cfg.risk.wide_stop_policy == "mechanical":
            stop = round(entry - cfg.risk.mechanical_stop_distance, 4)
            stop_distance = round(entry - stop, 4)
            add(8, "Define stop", StepStatus.PASS,
                f"pullback low was wide; using mechanical ${cfg.risk.mechanical_stop_distance:.2f} "
                f"stop at {stop:.2f}, plan to re-enter on a tighter setup",
                metrics={"stop": stop, "stop_distance": stop_distance, "mechanical": True})
        elif wide:
            add(8, "Define stop", StepStatus.FAIL,
                f"pullback-low stop {stop:.2f} is ${stop_distance:.2f} away "
                f"(> ${cfg.risk.mechanical_stop_distance:.2f}) — reject, wait for a tighter setup",
                metrics={"stop": stop, "stop_distance": stop_distance})
            aborted.append("stop too wide for good R:R")
            skip_rest(9, "stop too wide")
            return self._finalize_rejected(p, steps, m, aborted)
        else:
            add(8, "Define stop", StepStatus.PASS,
                f"stop = pullback low {stop:.2f} (${stop_distance:.2f} risk/share)",
                metrics={"stop": stop, "stop_distance": stop_distance})

        # ── Step 9: Targets & R:R (HARD GATE) ──
        pole_size = (pattern.pole_high - pattern.pole_low) if pattern.pole_high else 0.0
        measured_move = round(entry + pole_size, 4)
        target = max(measured_move, round(hod, 4)) if hod else measured_move
        reward = target - entry
        reward_risk = round(reward / stop_distance, 3) if stop_distance > 0 else 0.0
        rr_ok = reward_risk >= cfg.risk.min_reward_risk
        add(9, "Targets & R:R", StepStatus.PASS if rr_ok else StepStatus.FAIL,
            f"target {target:.2f} (measured move {measured_move:.2f} / HOD {hod:.2f}); "
            f"R:R {reward_risk:.2f} {'>=' if rr_ok else '<'} {cfg.risk.min_reward_risk:.1f}",
            metrics={"target": target, "reward_risk": reward_risk, "measured_move": measured_move})
        p.entry, p.stop, p.target = entry, stop, target
        p.stop_distance, p.reward_risk = stop_distance, reward_risk
        if not rr_ok:
            aborted.append(f"R:R {reward_risk:.2f} below the 2:1 floor")
            skip_rest(10, "R:R below 2:1")
            return self._finalize_rejected(p, steps, m, aborted)

        # ── Grade the setup (drives size) ──
        gr = grade_setup(fi, rvol, catalyst, pattern, reward_risk, c_daily.score)
        p.grade, p.grade_score = gr.grade, gr.score
        m["grade"] = gr.grade.value
        m["grade_notes"] = "; ".join(gr.notes)

        # ── Step 10: Position sizing ──
        sz = size_position(cfg, entry, stop_distance, account.equity, account.buying_power, gr.grade)
        p.shares = sz.shares
        p.risk_dollars = sz.risk_dollars
        p.position_notional = sz.position_notional
        p.position_pct = sz.position_pct
        if sz.shares > 0:
            add(10, "Position sizing", StepStatus.PASS,
                f"{sz.shares} sh (grade {gr.grade.value} x{sz.grade_factor:g}); "
                f"${sz.risk_dollars:.0f} at risk; ${sz.position_notional:.0f} notional "
                f"({sz.position_pct:.1%}); bound by {sz.binding_constraint}",
                metrics={"shares": sz.shares, "risk_dollars": sz.risk_dollars,
                         "position_notional": sz.position_notional, "position_pct": sz.position_pct,
                         "binding_constraint": sz.binding_constraint})
        else:
            add(10, "Position sizing", StepStatus.FAIL,
                f"grade {gr.grade.value} / constraints yield 0 shares ({sz.binding_constraint})",
                metrics={"shares": 0})
            aborted.append(f"sizing -> 0 shares (grade {gr.grade.value})")

        # ── Step 11: Risk-gate / discipline sweep (THE AUTHORITY) ──
        ctx = RiskContext(
            now=now, in_allowed_session=allowed, session_window=window,
            day_pnl=state.day_pnl, consecutive_losses=state.consecutive_losses,
            open_positions=state.open_count, trades_today=state.trades_today,
            account_equity=account.equity, buying_power=account.buying_power,
            spread=quote.spread if quote else 9.99,
            avg_dollar_volume=avg_dollar_volume,
            is_halted=self.provider.is_halted(symbol),
            last_loss_ts=state.last_loss_dt(), symbol_last_trade_ts=state.symbol_last_dt(symbol),
            session_halted=state.session_halted, account_profile=cfg.account_profile,
            day_trade_dates=list(state.day_trade_dates), shorting_enabled=cfg.shorting_enabled,
        )
        decision = self.risk.evaluate(p, ctx)
        sweep_detail = "all gates pass" if decision.approved else "; ".join(decision.reasons)
        add(11, "Risk-gate / discipline sweep",
            StepStatus.PASS if decision.approved else StepStatus.FAIL, sweep_detail,
            metrics={"approved": decision.approved,
                     "failed_gates": [g.name for g in decision.failed_gates]})

        # The authoritative verdict combines the risk engine with ANY earlier hard
        # fail (selection criteria, pattern, stop, R:R). When we don't short-circuit
        # for teaching value, an earlier hard fail must still reject the trade — the
        # risk engine alone doesn't re-check the selection criteria.
        approved = decision.approved and not aborted
        reasons = ([] if approved else (aborted + list(decision.reasons)))
        p.decision = RiskDecision(approved=approved, gates=decision.gates, reasons=reasons)

        # ── Step 12: Proposal (assembled; approval/exec handled by the engine) ──
        add(12, "Proposal", StepStatus.PASS if approved else StepStatus.INFO,
            "proposal ready for approval" if approved else "logged as a rejected setup",
            metrics={"grade": gr.grade.value})

        p.steps = steps
        p.metrics = m
        self._thesis(p)
        return p

    def _finalize_rejected(self, p: TradeProposal, steps, m, aborted) -> TradeProposal:
        p.steps = steps
        p.metrics = m
        p.decision = RiskDecision(approved=False, gates=[],
                                  reasons=aborted or ["setup did not qualify"])
        self._thesis(p)
        return p

    def _thesis(self, p: TradeProposal) -> None:
        """Attach a plain-English thesis. The reasoning layer is READ-ONLY: we
        capture the authoritative verdict and restore it afterwards, so even a
        misbehaving model can never flip a gate or change a reason."""
        if self.reasoner is None:
            return
        approved = p.decision.approved
        reasons = list(p.decision.reasons)
        try:
            p.thesis = self.reasoner.write_thesis(p) or ""
        except Exception as exc:
            log.warning("thesis generation failed: %s", exc)
            p.thesis = ""
        p.decision.approved = approved
        p.decision.reasons = reasons
