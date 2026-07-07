"""The expectancy engine (§6) — where the money is.

A 2:1 ratio only prints money if the win rate stays above ~33.4% after slippage
and fees:  breakeven win% for R reward per 1 risked = 1 / (1 + R)  →  1/3 for
2:1, ≈33.4% with costs. Expectancy per trade = (win% × avg win) − (loss% × avg
loss). This module computes that number honestly and continuously, with a
Wilson 95% confidence interval on the win rate so five lucky trades can't
masquerade as an edge, and n < min_sample flagged "insufficient sample — do not
conclude."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Iterable

from ..models import TradeRecord

Z95 = 1.959963984540054     # two-sided 95%


def wilson_interval(wins: int, n: int, z: float = Z95) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, center - half), min(1.0, center + half))


def breakeven_win_rate(avg_win_r: float, avg_loss_r: float) -> float:
    """Win rate needed for zero expectancy given the realized R profile.
    With 2R wins and 1R losses this is 1/3 ≈ 33.4% after costs."""
    if avg_win_r <= 0:
        return 1.0
    return avg_loss_r / (avg_win_r + avg_loss_r)


@dataclass
class ExpectancyStats:
    n: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    win_rate_ci: tuple[float, float] = (0.0, 1.0)
    avg_win_usd: float = 0.0
    avg_loss_usd: float = 0.0          # positive magnitude
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0            # positive magnitude
    profit_factor: float | None = None
    expectancy_usd: float = 0.0
    expectancy_r: float = 0.0
    breakeven_wr: float = 0.0
    total_pnl: float = 0.0
    total_slippage: float = 0.0
    insufficient_sample: bool = True
    note: str = ""


def compute(trades: Iterable[TradeRecord | dict], min_sample_n: int = 30) -> ExpectancyStats:
    """Accepts models or raw DB rows so the DB and fixtures share one code path."""
    pnls, rs, slips = [], [], []
    for t in trades:
        if isinstance(t, dict):
            pnls.append(float(t["pnl_usd"])); rs.append(float(t["realized_r"]))
            slips.append(float(t.get("slippage_usd", 0.0)))
        else:
            pnls.append(t.pnl_usd); rs.append(t.realized_r)
            slips.append(t.slippage_usd)

    s = ExpectancyStats()
    s.n = len(pnls)
    if s.n == 0:
        s.note = "no closed trades"
        return s

    wins = [(p, r) for p, r in zip(pnls, rs) if p > 0]
    losses = [(p, r) for p, r in zip(pnls, rs) if p <= 0]
    s.wins, s.losses = len(wins), len(losses)
    s.win_rate = s.wins / s.n
    s.win_rate_ci = wilson_interval(s.wins, s.n)
    s.avg_win_usd = sum(p for p, _ in wins) / s.wins if wins else 0.0
    s.avg_loss_usd = -sum(p for p, _ in losses) / s.losses if losses else 0.0
    s.avg_win_r = sum(r for _, r in wins) / s.wins if wins else 0.0
    s.avg_loss_r = -sum(r for _, r in losses) / s.losses if losses else 0.0
    gross_win = sum(p for p, _ in wins)
    gross_loss = -sum(p for p, _ in losses)
    s.profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None
    # Expectancy identities: mean pnl == win%*avg_win − loss%*avg_loss (exact).
    s.expectancy_usd = sum(pnls) / s.n
    s.expectancy_r = sum(rs) / s.n
    s.breakeven_wr = breakeven_win_rate(s.avg_win_r, s.avg_loss_r)
    s.total_pnl = sum(pnls)
    s.total_slippage = sum(slips)
    s.insufficient_sample = s.n < min_sample_n
    if s.insufficient_sample:
        s.note = f"insufficient sample (n={s.n} < {min_sample_n}) — do not conclude"
    return s


@dataclass
class RollingMonitor:
    """Rolling last-N expectancy (§6): negative ⇒ a red banner the agent must
    never bury — printed at startup and in every EOD report."""
    window: int = 20
    min_sample_n: int = 30
    stats: ExpectancyStats = field(default_factory=ExpectancyStats)

    def update(self, last_trades: list[TradeRecord | dict]) -> ExpectancyStats:
        self.stats = compute(last_trades[-self.window:], self.min_sample_n)
        return self.stats

    @property
    def red(self) -> bool:
        return self.stats.n > 0 and self.stats.expectancy_usd < 0

    def banner(self) -> str | None:
        if not self.red:
            return None
        s = self.stats
        return (f"\x1b[1;31mSTRATEGY CURRENTLY UNPROFITABLE ON REALIZED DATA: "
                f"rolling {s.n}-trade expectancy {s.expectancy_usd:+.2f} USD "
                f"({s.expectancy_r:+.2f}R)/trade, win rate {s.win_rate:.0%} "
                f"(95% CI {s.win_rate_ci[0]:.0%}–{s.win_rate_ci[1]:.0%}). "
                f"Reduce risk or stand down.\x1b[0m")


def cut_by(trades: list[dict], key: str, min_sample_n: int = 30) -> dict[str, ExpectancyStats]:
    """Metrics cut by setup / time bucket / DOW / float band / catalyst / regime.
    These cuts are the actionable output of the entire system (§6)."""
    groups: dict[str, list[dict]] = {}
    for t in trades:
        groups.setdefault(str(t.get(key, "unknown")), []).append(t)
    return {k: compute(v, min_sample_n) for k, v in sorted(groups.items())}


def time_bucket(closed_at) -> str:
    """30-minute session bucket label in exchange time, e.g. '09:30-10:00'."""
    from ..data.clock import ny
    t = ny(closed_at)
    half = 0 if t.minute < 30 else 30
    end_h, end_m = (t.hour, half + 30) if half == 0 else (t.hour + 1, 0)
    return f"{t.hour:02d}:{half:02d}-{end_h:02d}:{end_m:02d}"
