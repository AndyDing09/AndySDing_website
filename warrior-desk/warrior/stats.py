"""Performance statistics + the paper->live graduation gate (Sections 0, 6, 8).

Pure functions over a list of closed trades (objects or CSV dict rows). Used by
the journal's daily summary, by ``warrior stats``, and by the graduation gate that
refuses to discuss live trading until a real paper track record exists.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .config import Config

DEFAULT_STARTING_EQUITY = 30_000.0


def _pnl(t) -> float:
    return float(t["gross_pnl"]) if isinstance(t, dict) else float(t.gross_pnl)


def _r(t) -> float:
    try:
        return float(t["r_multiple"]) if isinstance(t, dict) else float(t.r_multiple)
    except (KeyError, TypeError, ValueError):
        return 0.0


@dataclass
class TradeStats:
    n: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0           # negative
    gross_profit: float = 0.0
    gross_loss: float = 0.0          # positive magnitude
    profit_factor: float | None = None
    expectancy: float = 0.0          # average $ per trade
    expectancy_r: float = 0.0        # average R per trade
    total_pnl: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    max_drawdown: float = 0.0        # $ peak-to-trough on the equity curve
    max_drawdown_pct: float = 0.0


def compute_stats(trades: Sequence, starting_equity: float = DEFAULT_STARTING_EQUITY) -> TradeStats:
    s = TradeStats()
    if not trades:
        return s
    pnls = [_pnl(t) for t in trades]
    rs = [_r(t) for t in trades]
    s.n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    s.wins, s.losses = len(wins), len(losses)
    s.win_rate = round(s.wins / s.n, 4)
    s.gross_profit = round(sum(wins), 2)
    s.gross_loss = round(-sum(losses), 2)
    s.avg_win = round(sum(wins) / len(wins), 2) if wins else 0.0
    s.avg_loss = round(sum(losses) / len(losses), 2) if losses else 0.0
    s.profit_factor = round(s.gross_profit / s.gross_loss, 3) if s.gross_loss > 0 else None
    s.total_pnl = round(sum(pnls), 2)
    s.expectancy = round(sum(pnls) / s.n, 2)
    s.expectancy_r = round(sum(rs) / s.n, 3)
    s.largest_win = round(max(pnls), 2)
    s.largest_loss = round(min(pnls), 2)

    # Max drawdown on the cumulative-equity curve.
    equity = starting_equity
    peak = starting_equity
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    s.max_drawdown = round(max_dd, 2)
    s.max_drawdown_pct = round(max_dd / peak, 4) if peak > 0 else 0.0
    return s


def read_closed_trades(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@dataclass
class GraduationStatus:
    eligible: bool = False
    criteria: list[tuple[str, bool, str]] = field(default_factory=list)  # (name, met, detail)

    @property
    def missing(self) -> list[str]:
        return [f"{n}: {d}" for n, met, d in self.criteria if not met]


def graduation_status(cfg: Config, stats: TradeStats) -> GraduationStatus:
    """Ross's steps 4–7 graduation bar (paper -> live eligibility)."""
    g = cfg.graduation_gate
    crit: list[tuple[str, bool, str]] = []

    enough = stats.n >= g.min_closed_trades
    crit.append(("closed_trades", enough, f"{stats.n} / {g.min_closed_trades} closed paper trades"))

    pos_exp = (not g.require_positive_expectancy) or stats.expectancy > 0
    crit.append(("positive_expectancy", pos_exp,
                 f"expectancy ${stats.expectancy:.2f}/trade ({stats.expectancy_r:+.2f}R)"))

    # A record with no losing trades has an "infinite" profit factor — that passes.
    pf_ok = (stats.profit_factor is not None and stats.profit_factor >= 1.0) or \
            (stats.profit_factor is None and stats.total_pnl > 0)
    pf_label = "inf (no losses)" if stats.profit_factor is None and stats.total_pnl > 0 else \
        (stats.profit_factor if stats.profit_factor is not None else "n/a")
    crit.append(("profit_factor>=1", pf_ok and stats.n > 0, f"profit factor {pf_label}"))

    dd_ok = stats.max_drawdown_pct <= g.max_drawdown_pct
    crit.append(("max_drawdown", dd_ok,
                 f"max drawdown {stats.max_drawdown_pct:.1%} (limit {g.max_drawdown_pct:.0%})"))

    eligible = all(met for _, met, _ in crit)
    return GraduationStatus(eligible=eligible, criteria=crit)


def render_stats(cfg: Config) -> str:
    closed_path = str(Path(cfg.journal_dir) / "closed_trades.csv")
    trades = read_closed_trades(closed_path)
    s = compute_stats(trades)
    grad = graduation_status(cfg, s)

    pf = "n/a" if s.profit_factor is None else f"{s.profit_factor:.2f}"
    lines = [
        "WARRIOR DESK — CUMULATIVE STATS",
        f"  closed trades   {s.n}  ({s.wins}W / {s.losses}L)",
        f"  win rate        {s.win_rate:.1%}",
        f"  avg win/loss    ${s.avg_win:.2f} / ${s.avg_loss:.2f}",
        f"  profit factor   {pf}",
        f"  expectancy      ${s.expectancy:.2f}/trade  ({s.expectancy_r:+.2f}R)",
        f"  total P&L       ${s.total_pnl:.2f}",
        f"  largest W/L     ${s.largest_win:.2f} / ${s.largest_loss:.2f}",
        f"  max drawdown    ${s.max_drawdown:.2f}  ({s.max_drawdown_pct:.1%})",
        "",
        "GRADUATION GATE (paper -> live):",
    ]
    for name, met, detail in grad.criteria:
        lines.append(f"  [{'x' if met else ' '}] {detail}")
    if grad.eligible:
        lines.append("\n  ELIGIBLE on these metrics — but live still requires the §0 multi-lock.")
    else:
        lines.append("\n  NOT eligible for live yet. Live requests are declined until the bar is met.")
    return "\n".join(lines)
