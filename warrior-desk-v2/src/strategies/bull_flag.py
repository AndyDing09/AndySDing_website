"""Bull flag / first pullback (§2.2 B) — the bread-and-butter, 9:30–11:30 ET.

Precondition: a strong upward move (≥ N wide-range green 1-min candles), then a
pullback retracing ≤ 50% of the move, ideally holding the 9-EMA.
Entry: the first green candle that breaks the HIGH of the previous red candle
(trend resuming). Stop: the LOW of that previous red candle (the pullback low).
Target: new high of day — if HOD-minus-entry < 2× the stop distance the signal
dies at the gate downstream (logged skipped:insufficient_rr), by design.
"""

from __future__ import annotations

from datetime import time
from typing import Optional

from ..models import Signal, SetupName
from .base import MarketView, Strategy, ema_last


class BullFlag(Strategy):
    name = SetupName.BULL_FLAG

    def window(self) -> tuple[time, time]:
        return self.cfg.setups.bull_flag.window

    def _detect(self, view: MarketView) -> Optional[Signal]:
        s = self.cfg.setups.bull_flag
        bars = view.bars_1m
        if len(bars) < s.min_pole_candles + 2:
            return None

        cur = bars[-1]
        if not cur.green:
            return None                      # entry candle must be green

        # The pullback: consecutive red candles immediately before the current one.
        i = len(bars) - 2
        pullback: list = []
        while i >= 0 and bars[i].red:
            pullback.append(bars[i])
            i -= 1
        if not pullback:
            return None
        prev_red = pullback[0]                # the candle whose high we must break
        pullback_low = min(b.low for b in pullback)

        # The pole: green run before the pullback, wide-range vs session average.
        pole: list = []
        while i >= 0 and bars[i].green:
            pole.append(bars[i])
            i -= 1
        if len(pole) < s.min_pole_candles:
            return None
        session_avg_range = sum(b.range for b in bars) / len(bars)
        wide = [b for b in pole if b.range >= session_avg_range]
        if len(wide) < s.min_pole_candles:
            return None

        pole_low = min(b.low for b in pole)
        pole_high = max(b.high for b in pole)
        move = pole_high - pole_low
        if move <= 0:
            return None
        retrace = (pole_high - pullback_low) / move
        if retrace > s.max_retrace:
            return None                       # gave back too much — not a flag

        # Trend resuming: current green candle breaks the previous red's high.
        if not (cur.high > prev_red.high and cur.close > prev_red.high):
            return None

        # "Ideally holding the 9-EMA": annotate rather than reject — cleanliness
        # feeds the quality score, the hard geometry above is the gate here.
        closes = [b.close for b in bars]
        e9 = ema_last(closes, 9)
        holds_9ema = bool(e9 is not None and pullback_low >= e9 * 0.999)

        entry = round(prev_red.high + 0.01, 4)
        stop = round(pullback_low, 4)
        target = round(max(view.hod, pole_high), 4)   # new high of day

        sig = Signal(
            ts=view.now, symbol=view.candidate.symbol, setup=SetupName.BULL_FLAG,
            entry=entry, stop=stop, target=target,
            regime=view.regime, feed=view.feed,
            spread_pct_at_signal=view.quote.spread_pct if view.quote else 0.0,
            catalyst_type=view.candidate.catalyst_type,
            obviousness_rank=view.candidate.obviousness_rank,
        )
        sig.status_reason = "holds_9ema" if holds_9ema else ""
        return sig
