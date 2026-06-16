"""Pattern recognition (Sections 2.2–2.4): bull flag and flat-top breakout.

Only these two patterns are traded by default. Anything that isn't a clean bull
flag or flat top is rejected and logged as a rejected setup with the reason.

A bull flag = a sharp up-move (the "pole") on volume, then a shallow, low-volume
pullback of a few red candles that retraces ≤ 50% of the pole and ideally holds
the 9-EMA / VWAP. The entry trigger is the break of the prior red candle's high
(or the flat-top line). The stop is the low of the pullback.
"""

from __future__ import annotations

from typing import Optional, Sequence

from .config import Config
from .models import Bar, PatternKind, PatternResult

MAX_PULLBACK = 4      # a "few" red candles; ideal is 2–3
MAX_POLE = 8          # how far back we'll look for the pole base


def _avg_vol(bars: Sequence[Bar]) -> float:
    return sum(b.volume for b in bars) / len(bars) if bars else 0.0


def detect_pattern(
    bars: Sequence[Bar],
    cfg: Config,
    ema9: Optional[float] = None,
    vwap: Optional[float] = None,
) -> PatternResult:
    """Detect a bull flag / flat top in the trailing candles.

    Handles both the *forming* state (last candle is the pullback) and the
    *triggered* state (last candle is the green breakout that broke the pullback
    high). ``ema9``/``vwap`` are the latest indicator values used to judge whether
    the pullback held support.
    """
    res = PatternResult()
    n = len(bars)
    if n < 4:
        res.reasons.append("not enough bars to read a pattern")
        return res

    # 1) Locate the trailing pullback (consecutive non-green candles). If the last
    #    candle is green it may be the breakout, so the pullback ends one bar back.
    last = bars[-1]
    breakout_candle: Optional[Bar] = None
    end = n - 1
    if last.is_green:
        breakout_candle = last
        end = n - 2

    pull_idx: list[int] = []
    i = end
    while i >= 0 and not bars[i].is_green and len(pull_idx) < MAX_PULLBACK:
        pull_idx.append(i)
        i -= 1
    pull_idx.reverse()

    if not pull_idx:
        res.reasons.append("no pullback — price is trending without a flag")
        return res
    if len(pull_idx) > MAX_PULLBACK - 1 and end - i > MAX_PULLBACK:
        res.reasons.append("pullback too long to be a tight flag")

    pull_bars = [bars[j] for j in pull_idx]
    pole_end = pull_idx[0] - 1
    if pole_end < 0:
        res.reasons.append("no pole before the pullback")
        return res

    # 2) Walk back to find the pole base (rising candles / higher lows).
    pole_start = pole_end
    steps = 0
    while pole_start - 1 >= 0 and steps < MAX_POLE:
        prev = bars[pole_start - 1]
        cur = bars[pole_start]
        if cur.low >= prev.low or prev.is_green:
            pole_start -= 1
            steps += 1
        else:
            break
    pole_bars = bars[pole_start:pole_end + 1]
    if not pole_bars:
        res.reasons.append("could not isolate a pole")
        return res

    pole_high = max(b.high for b in pole_bars)
    pole_low = min(b.low for b in pole_bars)
    pole_size = pole_high - pole_low
    if pole_size <= 0 or pole_bars[-1].close <= pole_bars[0].open:
        res.reasons.append("no real upward pole (move is not sharp/positive)")
        return res
    if not any(b.is_green for b in pole_bars):
        res.reasons.append("pole has no green candles")
        return res

    pullback_low = min(b.low for b in pull_bars)
    retrace = (pole_high - pullback_low) / pole_size if pole_size else 1.0

    res.pole_high = round(pole_high, 4)
    res.pole_low = round(pole_low, 4)
    res.pullback_low = round(pullback_low, 4)
    res.retrace_pct = round(retrace, 4)
    res.pullback_len = len(pull_bars)
    res.pole_volume = round(_avg_vol(pole_bars), 2)
    res.pullback_volume = round(_avg_vol(pull_bars), 2)
    res.confirm_volume = round(max(_avg_vol(pole_bars), _avg_vol(pull_bars)), 2)

    if ema9 is not None:
        res.holds_9ema = pullback_low >= ema9 * 0.999  # tiny tolerance
    if vwap is not None:
        res.holds_vwap = pullback_low >= vwap * 0.999

    # 3) Trigger = break of the pullback high (prior red candle / flat-top line).
    pull_highs = [b.high for b in pull_bars]
    res.trigger_price = round(max(pull_highs), 4)

    # 4) Flat top vs bull flag: a flat ceiling = pullback highs cluster tightly.
    ref_price = pole_high or 1.0
    flatness = (max(pull_highs) - min(pull_highs)) / ref_price if ref_price else 1.0
    if len(pull_bars) >= 2 and flatness <= 0.005:
        res.kind = PatternKind.FLAT_TOP
        res.flat_top_price = res.trigger_price
    else:
        res.kind = PatternKind.BULL_FLAG

    # 5) Was the breakout already confirmed (green candle broke the trigger on volume)?
    if breakout_candle is not None and breakout_candle.high > res.trigger_price:
        res.triggered = breakout_candle.volume >= res.confirm_volume * 0.8

    # 6) Validity verdict.
    if retrace > cfg.selection.pullback_max_retrace:
        res.reasons.append(
            f"pullback retraced {retrace:.0%} of the pole (> "
            f"{cfg.selection.pullback_max_retrace:.0%}) — too deep")
        res.valid = False
        return res

    res.valid = True
    res.reasons.append(
        f"{res.kind.value}: pole {pole_low:.2f}->{pole_high:.2f}, "
        f"{len(pull_bars)}-candle pullback to {pullback_low:.2f} "
        f"({retrace:.0%} retrace), trigger {res.trigger_price:.2f}")
    return res
