"""Market regime tagger (§3.3).

SPY on the 5-minute chart: above both VWAP and the 9-EMA = trending; below both
= also a tradeable trend day for longs only if extended criteria hold, but for
this long-only book we tag it chop-averse: mixed. Straddling = mixed; whipsawing
around flat VWAP with EMA crosses = chop. In chop the required setup score rises
(§7.1) instead of trading the same size into a dead tape.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Bar, Regime


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def session_vwap(bars: list[Bar]) -> float | None:
    pv = v = 0.0
    for b in bars:
        typical = (b.high + b.low + b.close) / 3
        pv += typical * b.volume
        v += b.volume
    return (pv / v) if v > 0 else None


@dataclass
class RegimeCall:
    regime: Regime
    spy_close: float | None = None
    spy_vwap: float | None = None
    spy_ema9: float | None = None


def classify_regime(spy_5m_bars: list[Bar], ema_period: int = 9) -> RegimeCall:
    if len(spy_5m_bars) < ema_period:
        return RegimeCall(Regime.MIXED)
    closes = [b.close for b in spy_5m_bars]
    last = closes[-1]
    vw = session_vwap(spy_5m_bars)
    e9 = ema(closes, ema_period)
    if vw is None or e9 is None:
        return RegimeCall(Regime.MIXED, last, vw, e9)

    above_vwap = last > vw
    above_ema = last > e9

    # Chop = price pinned to VWAP (within 10 bps) or signals disagreeing while
    # the last few closes alternate around the EMA.
    near_vwap = abs(last - vw) / vw < 0.001
    recent = closes[-6:]
    crosses = sum(
        1 for a, b in zip(recent, recent[1:])
        if (a - e9) * (b - e9) < 0
    )
    if near_vwap or crosses >= 2:
        return RegimeCall(Regime.CHOP, last, vw, e9)
    if above_vwap and above_ema:
        return RegimeCall(Regime.TRENDING, last, vw, e9)
    return RegimeCall(Regime.MIXED, last, vw, e9)


def required_score(base_required: int, regime: Regime, chop_bump: int) -> int:
    """In chop, raise the bar instead of trading the same size into a dead tape."""
    return base_required + (chop_bump if regime == Regime.CHOP else 0)
