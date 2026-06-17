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
    """Detect a bull flag / flat top using a forgiving "recent-high + pullback +
    break" model that survives choppy real-world intraday bars.

    The pole is the run up into the most recent swing high; the flag is the
    pullback off that high. The entry trigger is the break of that swing high.
    A *breakout* (triggered) is the current candle pushing a green bar through it.
    """
    res = PatternResult()
    n = len(bars)
    if n < 4:
        res.reasons.append("not enough bars to read a pattern")
        return res

    look = min(n, 15)
    recent = list(bars[-look:])
    current = recent[-1]
    prior = recent[:-1]

    # The swing high among the prior bars = the pole top / consolidation ceiling.
    sh_idx = max(range(len(prior)), key=lambda i: prior[i].high)
    sh_high = prior[sh_idx].high
    pole_bars = prior[: sh_idx + 1]
    pole_low = min(b.low for b in pole_bars)
    pole_size = sh_high - pole_low
    if pole_low <= 0 or pole_size <= 0 or (pole_size / pole_low) < cfg.selection.min_pole_gain_pct:
        res.reasons.append("no real pole (move too small to be momentum)")
        return res
    if not any(b.is_green for b in pole_bars):
        res.reasons.append("pole has no green candles")
        return res

    triggered_high = current.high >= sh_high
    # The pullback is everything between the swing high and now. If we're breaking
    # out this bar, the pullback is the bars *before* the breakout candle.
    pull = prior[sh_idx + 1:] if triggered_high else recent[sh_idx + 1:]
    if len(pull) < 1:
        res.reasons.append("no pullback yet — not a flag")
        return res

    pullback_low = min(b.low for b in pull)
    retrace = (sh_high - pullback_low) / pole_size

    res.kind = PatternKind.BULL_FLAG
    # Flat top = the high was tested by 2+ bars (a seller capping one price).
    near_ceiling = sum(1 for b in prior if abs(b.high - sh_high) <= 0.003 * sh_high)
    if near_ceiling >= 2:
        res.kind = PatternKind.FLAT_TOP
        res.flat_top_price = round(sh_high, 4)

    res.pole_high = round(sh_high, 4)
    res.pole_low = round(pole_low, 4)
    res.pullback_low = round(pullback_low, 4)
    res.retrace_pct = round(retrace, 4)
    res.pullback_len = len(pull)
    res.pole_volume = round(_avg_vol(pole_bars), 2)
    res.pullback_volume = round(_avg_vol(pull), 2)
    res.confirm_volume = round(max(_avg_vol(pole_bars), _avg_vol(pull)), 2)
    res.trigger_price = round(sh_high, 4)
    res.triggered = triggered_high and current.is_green
    if ema9 is not None:
        res.holds_9ema = pullback_low >= ema9 * 0.999
    if vwap is not None:
        res.holds_vwap = pullback_low >= vwap * 0.999

    if retrace > cfg.selection.pullback_max_retrace:
        res.reasons.append(
            f"pullback retraced {retrace:.0%} of the pole (> "
            f"{cfg.selection.pullback_max_retrace:.0%}) — too deep")
        return res
    if current.close < pole_low:
        res.reasons.append("price broke down below the base — not a flag")
        return res

    res.valid = True
    res.reasons.append(
        f"{res.kind.value}: pole {pole_low:.2f}->{sh_high:.2f} "
        f"({pole_size / pole_low:.0%}), {len(pull)}-bar pullback to {pullback_low:.2f} "
        f"({retrace:.0%} retrace), "
        + ("broke out" if res.triggered else f"trigger {sh_high:.2f}"))
    return res
