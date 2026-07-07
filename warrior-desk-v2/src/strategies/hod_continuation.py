"""HOD momentum continuation (§2.2 D).

Triggered by the §3.2 scanner printing a new high of day on a qualifying stock.
Entry only on the MICRO-PULLBACK after the HOD break — never chasing the spike
candle itself (chasing the spike is buying someone else's exit). Stop/target
share the bull-flag structure: stop under the micro-pullback low, target the
measured continuation.
"""

from __future__ import annotations

from datetime import time
from typing import Optional

from ..models import Signal, SetupName
from .base import MarketView, Strategy


class HodContinuation(Strategy):
    name = SetupName.HOD_CONTINUATION

    def window(self) -> tuple[time, time]:
        return self.cfg.setups.hod_continuation.window

    def _detect(self, view: MarketView) -> Optional[Signal]:
        bars = view.bars_1m
        if len(bars) < 4:
            return None
        cur = bars[-1]

        # Shape: spike candle set the HOD, then >=1 red micro-pullback candle,
        # now a green candle reclaiming the prior red's high.
        i = len(bars) - 2
        pullback = []
        while i >= 0 and bars[i].red:
            pullback.append(bars[i])
            i -= 1
        if not (1 <= len(pullback) <= 3):
            return None                        # no pullback = still the spike; too long = trend over
        spike = bars[i] if i >= 0 else None
        if spike is None or not spike.green:
            return None
        if spike.high < view.hod * 0.999:      # the spike is what printed the HOD
            return None

        prev_red = pullback[0]
        if not (cur.green and cur.high > prev_red.high and cur.close > prev_red.high):
            return None

        pullback_low = min(b.low for b in pullback)
        entry = round(prev_red.high + 0.01, 4)
        stop = round(pullback_low, 4)
        risk = entry - stop
        if risk <= 0:
            return None
        # Continuation target: measured from the spike's range above the HOD.
        target = round(max(view.hod + spike.range, entry + 2 * risk), 4)

        return Signal(
            ts=view.now, symbol=view.candidate.symbol, setup=SetupName.HOD_CONTINUATION,
            entry=entry, stop=stop, target=target,
            regime=view.regime, feed=view.feed,
            spread_pct_at_signal=view.quote.spread_pct if view.quote else 0.0,
            catalyst_type=view.candidate.catalyst_type,
            obviousness_rank=view.candidate.obviousness_rank,
        )
