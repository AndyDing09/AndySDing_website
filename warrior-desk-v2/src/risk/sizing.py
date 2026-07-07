"""Position sizing + per-signal risk checks (§2.3).

shares = floor(risk_per_trade_usd / (entry − stop)), where risk_per_trade is
recomputed daily as % of current equity (the config USD value acts as a cap).
Then: notional ≤ max_position_pct of equity (thin floats can't absorb size) and
spread ≤ max_spread_pct at signal time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import RiskCfg
from ..models import Signal, SignalStatus


def daily_risk_usd(cfg: RiskCfg, equity: float) -> float:
    """% of current equity, capped by the configured USD amount."""
    pct_based = max(0.0, equity) * cfg.risk_pct_of_equity
    return min(pct_based, cfg.risk_per_trade_usd) if cfg.risk_per_trade_usd > 0 else pct_based


@dataclass
class SizingDecision:
    shares: int
    risk_usd: float
    notional: float
    ok: bool
    reject_reason: str = ""


def size_signal(signal: Signal, cfg: RiskCfg, equity: float,
                spread_pct: float | None = None) -> SizingDecision:
    """Compute shares and apply the §2.3 per-signal rejections. On rejection the
    signal is mutated to rejected:<gate> so the journal keeps the evidence."""
    risk_per_share = signal.entry - signal.stop
    budget = daily_risk_usd(cfg, equity)

    def reject(reason: str) -> SizingDecision:
        signal.status = SignalStatus.REJECTED
        signal.status_reason = reason
        return SizingDecision(0, 0.0, 0.0, False, reason)

    if risk_per_share <= 0:
        return reject("invalid_stop")

    sp = signal.spread_pct_at_signal if spread_pct is None else spread_pct
    if sp > cfg.max_spread_pct:
        return reject("spread")

    shares = math.floor(budget / risk_per_share)
    if shares < 1:
        return reject("risk_budget_too_small_for_stop")

    notional = shares * signal.entry
    max_notional = cfg.max_position_pct * equity
    if notional > max_notional:
        shares = math.floor(max_notional / signal.entry)
        notional = shares * signal.entry
        if shares < 1:
            return reject("notional_cap")

    signal.shares = shares
    return SizingDecision(shares=shares, risk_usd=shares * risk_per_share,
                          notional=notional, ok=True)
