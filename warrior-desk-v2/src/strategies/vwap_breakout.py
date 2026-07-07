"""VWAP breakout (§2.2 C) — window 9:45–15:30 ET.

Precondition: consolidation just UNDER VWAP for ≥ 10 minutes on declining
volume. Entry: a 1-min close above VWAP with volume ≥ 2× the consolidation
average. Stop: consolidation low or VWAP − 1×ATR(1-min,14), whichever is
TIGHTER. Target: HOD, then measured move; the 2:1 gate applies downstream.
"""

from __future__ import annotations

from datetime import time
from typing import Optional

from ..models import Signal, SetupName
from .base import MarketView, Strategy, atr, session_vwap


class VwapBreakout(Strategy):
    name = SetupName.VWAP_BREAKOUT

    def window(self) -> tuple[time, time]:
        return self.cfg.setups.vwap_breakout.window

    def _detect(self, view: MarketView) -> Optional[Signal]:
        s = self.cfg.setups.vwap_breakout
        bars = view.bars_1m
        need = s.min_consolidation_minutes + 1
        if len(bars) < need:
            return None

        vwap = session_vwap(bars)
        if vwap is None:
            return None

        cur = bars[-1]
        consol = bars[-need:-1]              # the N minutes before the breakout candle

        # Consolidating just under VWAP: every close below-or-at VWAP but within 1%.
        under = all(b.close <= vwap and b.close >= vwap * 0.99 for b in consol)
        if not under:
            return None
        # Declining volume across the consolidation (first half vs second half).
        half = len(consol) // 2
        v1 = sum(b.volume for b in consol[:half]) / max(1, half)
        v2 = sum(b.volume for b in consol[half:]) / max(1, len(consol) - half)
        if not (v2 < v1):
            return None

        consol_avg_vol = sum(b.volume for b in consol) / len(consol)
        breakout = cur.close > vwap and cur.volume >= s.breakout_volume_mult * consol_avg_vol
        if not breakout:
            return None

        consol_low = min(b.low for b in consol)
        a = atr(bars, s.atr_period)
        stop_candidates = [consol_low]
        if a is not None:
            stop_candidates.append(vwap - a)
        entry = round(cur.close, 4)
        valid = [x for x in stop_candidates if x < entry]
        if not valid:
            return None
        stop = max(valid)                    # tighter wins

        target = round(max(view.hod, entry + (entry - stop) * 2), 4)

        return Signal(
            ts=view.now, symbol=view.candidate.symbol, setup=SetupName.VWAP_BREAKOUT,
            entry=entry, stop=round(stop, 4), target=target,
            regime=view.regime, feed=view.feed,
            spread_pct_at_signal=view.quote.spread_pct if view.quote else 0.0,
            catalyst_type=view.candidate.catalyst_type,
            obviousness_rank=view.candidate.obviousness_rank,
        )
