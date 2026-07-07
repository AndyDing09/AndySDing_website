"""Slippage-honest paper fills (§7.2).

Alpaca paper fills are optimistic; low-float stats that ignore slippage are
fiction. Every simulated fill is degraded: entries assume ask + N ticks,
stop-outs assume bid − 1 tick, and both scale up when the spread is wide
(one extra tick per full multiple of max_spread_pct in the observed spread).
The journal stores BOTH the intended and the adjusted price so the model itself
is auditable.
"""

from __future__ import annotations

from ..config import SlippageCfg


def _extra_ticks(spread_pct: float, max_spread_pct: float, per_multiple: int) -> int:
    if max_spread_pct <= 0:
        return 0
    multiples = int(spread_pct / max_spread_pct)
    return multiples * per_multiple


def entry_fill_price(ask: float, spread_pct: float, cfg: SlippageCfg,
                     max_spread_pct: float) -> float:
    ticks = cfg.ticks + _extra_ticks(spread_pct, max_spread_pct, cfg.wide_spread_extra_ticks)
    return round(ask + ticks * cfg.tick_size, 4)


def stop_fill_price(bid: float, spread_pct: float, cfg: SlippageCfg,
                    max_spread_pct: float) -> float:
    ticks = 1 + _extra_ticks(spread_pct, max_spread_pct, cfg.wide_spread_extra_ticks)
    return round(bid - ticks * cfg.tick_size, 4)


def target_fill_price(limit_price: float) -> float:
    """A resting limit at the target fills at the limit (no positive slippage
    is ever assumed — optimism is the failure mode being corrected)."""
    return round(limit_price, 4)
