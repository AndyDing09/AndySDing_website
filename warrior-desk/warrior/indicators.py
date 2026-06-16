"""Technical indicators — pure Python, standard library only (Section 2.8).

The agent computes exactly these and no more: volume, 9/20/200-EMA, VWAP, MACD,
RSI, ATR, RVOL. No "holy grail" indicator hunting.

All series functions return a list the same length as the input, with ``None`` in
the warm-up region where the indicator isn't defined yet. ``*_last`` helpers
return just the final defined value (or None).
"""

from __future__ import annotations

from typing import Optional, Sequence

from .models import Bar


def sma(values: Sequence[float], period: int) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * len(values)
    if period <= 0:
        return out
    run = 0.0
    for i, v in enumerate(values):
        run += v
        if i >= period:
            run -= values[i - period]
        if i >= period - 1:
            out[i] = run / period
    return out


def ema(values: Sequence[float], period: int) -> list[Optional[float]]:
    """EMA seeded with the SMA of the first ``period`` values (the convention)."""
    out: list[Optional[float]] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    k = 2.0 / (period + 1.0)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def ema_last(values: Sequence[float], period: int) -> Optional[float]:
    s = ema(values, period)
    return s[-1] if s else None


def rsi(values: Sequence[float], period: int = 14) -> list[Optional[float]]:
    """Wilder's RSI. The first defined value (at index ``period``) uses a simple
    average of the initial gains/losses; subsequent values use Wilder smoothing."""
    n = len(values)
    out: list[Optional[float]] = [None] * n
    if n <= period:
        return out

    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        ch = values[i] - values[i - 1]
        gains += max(ch, 0.0)
        losses += max(-ch, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = _rsi_from(avg_gain, avg_loss)

    for i in range(period + 1, n):
        ch = values[i] - values[i - 1]
        gain = max(ch, 0.0)
        loss = max(-ch, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = _rsi_from(avg_gain, avg_loss)
    return out


def _rsi_from(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def rsi_last(values: Sequence[float], period: int = 14) -> Optional[float]:
    s = rsi(values, period)
    return s[-1] if s else None


def macd(values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """Return (macd_line, signal_line, histogram), each a list with None warm-up."""
    n = len(values)
    fast_e = ema(values, fast)
    slow_e = ema(values, slow)
    macd_line: list[Optional[float]] = [None] * n
    for i in range(n):
        if fast_e[i] is not None and slow_e[i] is not None:
            macd_line[i] = fast_e[i] - slow_e[i]
    # signal = EMA of the defined macd_line values
    defined = [(i, v) for i, v in enumerate(macd_line) if v is not None]
    signal_line: list[Optional[float]] = [None] * n
    hist: list[Optional[float]] = [None] * n
    if len(defined) >= signal:
        vals = [v for _, v in defined]
        sig = ema(vals, signal)
        for (orig_i, _), s in zip(defined, sig):
            signal_line[orig_i] = s
        for i in range(n):
            if macd_line[i] is not None and signal_line[i] is not None:
                hist[i] = macd_line[i] - signal_line[i]
    return macd_line, signal_line, hist


def true_range(bars: Sequence[Bar]) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * len(bars)
    for i, b in enumerate(bars):
        if i == 0:
            out[i] = b.high - b.low
        else:
            pc = bars[i - 1].close
            out[i] = max(b.high - b.low, abs(b.high - pc), abs(b.low - pc))
    return out


def atr(bars: Sequence[Bar], period: int = 14) -> list[Optional[float]]:
    """Wilder's ATR."""
    n = len(bars)
    out: list[Optional[float]] = [None] * n
    if n < period:
        return out
    tr = [t for t in true_range(bars)]
    seed = sum(tr[:period]) / period            # type: ignore[arg-type]
    out[period - 1] = seed
    prev = seed
    for i in range(period, n):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def atr_last(bars: Sequence[Bar], period: int = 14) -> Optional[float]:
    s = atr(bars, period)
    return s[-1] if s else None


def vwap(bars: Sequence[Bar]) -> list[Optional[float]]:
    """Session VWAP using the typical price (h+l+c)/3. Assumes ``bars`` is a
    single session (reset daily by the caller)."""
    out: list[Optional[float]] = [None] * len(bars)
    cum_pv = 0.0
    cum_v = 0.0
    for i, b in enumerate(bars):
        tp = (b.high + b.low + b.close) / 3.0
        cum_pv += tp * b.volume
        cum_v += b.volume
        out[i] = (cum_pv / cum_v) if cum_v > 0 else b.close
    return out


def vwap_last(bars: Sequence[Bar]) -> Optional[float]:
    s = vwap(bars)
    return s[-1] if s else None


def rvol(current_volume: float, baseline_volume: float) -> float:
    """Relative volume = today's volume (for this time of day) / the average.
    The *baseline* must be supplied by the data layer; ≥ 2.0 signals unusual
    interest. Returns 0.0 when the baseline is unknown/zero."""
    if baseline_volume <= 0:
        return 0.0
    return round(current_volume / baseline_volume, 3)


def pct_from(price: float, reference: float) -> Optional[float]:
    """Percent distance of ``price`` from a reference line (e.g. VWAP/9-EMA)."""
    if not reference:
        return None
    return round((price - reference) / reference, 5)
