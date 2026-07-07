"""Gap & Go (§2.2 A) — window 9:30–10:15 ET.

Precondition: gapped ≥ 4% pre-market (A-grade ≥ 10%) and passed §2.1.
Entry: break of the PRE-MARKET HIGH after the open on above-average 1-min volume.
Stop: low of the first 1-min pullback, or the pre-market consolidation low,
whichever is TIGHTER. Target: measured move (gap size projected) or HOD
structure; the 2:1 gate downstream decides if it's tradeable.
"""

from __future__ import annotations

from datetime import time
from typing import Optional

from ..models import Signal, SetupName
from .base import MarketView, Strategy, avg_volume


class GapAndGo(Strategy):
    name = SetupName.GAP_AND_GO

    def window(self) -> tuple[time, time]:
        return self.cfg.setups.gap_and_go.window

    def _detect(self, view: MarketView) -> Optional[Signal]:
        s = self.cfg.setups.gap_and_go
        c = view.candidate
        if c.gap_pct < s.min_gap_pct or view.premkt_high is None:
            return None
        bars = view.bars_1m
        if len(bars) < 2:
            return None

        last = bars[-1]
        # Entry trigger: current candle takes out the pre-market high on
        # above-average volume (vs the session so far, excluding this candle).
        baseline = avg_volume(bars[:-1])
        broke = last.high > view.premkt_high and bars[-2].high <= view.premkt_high
        if not (broke and baseline > 0 and last.volume > baseline):
            return None

        # Stop: first pullback low after the open vs pre-market low — tighter wins.
        pullback_lows = [b.low for b in bars if b.red]
        first_pullback_low = pullback_lows[0] if pullback_lows else bars[0].low
        stop_candidates = [first_pullback_low]
        if view.premkt_low is not None:
            stop_candidates.append(view.premkt_low)
        entry = round(view.premkt_high + 0.01, 4)          # break of the level
        stop = max(x for x in stop_candidates if x < entry)  # tighter = closer to entry

        # Target: measured move — project the gap's dollar size from the entry.
        prior_close = c.last / (1 + c.gap_pct) if c.gap_pct > -1 else 0.0
        gap_dollars = max(0.0, c.last - prior_close)
        target = round(entry + gap_dollars, 4)

        return Signal(
            ts=view.now, symbol=c.symbol, setup=SetupName.GAP_AND_GO,
            entry=entry, stop=round(stop, 4), target=target,
            regime=view.regime, feed=view.feed,
            spread_pct_at_signal=view.quote.spread_pct if view.quote else 0.0,
            catalyst_type=c.catalyst_type, obviousness_rank=c.obviousness_rank,
        )
