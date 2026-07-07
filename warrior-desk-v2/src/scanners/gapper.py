"""Pre-market Top Gapper scan (§3.1).

Runs 7:00–9:30 ET on a refresh interval, pulling pre-market snapshots for the
price band and ranking by gap %. At the freeze time (9:15 ET) the top A-grade
names become the Gap & Go candidates with their pre-market high/low marked.

The scan itself is a pure function over snapshot inputs so replay and tests use
the identical code path; the async loop wrapper only schedules refreshes.

Rationale (spec §2.1): momentum trading is "buy high, sell higher" on stocks
already moving outside their normal range; sideways large-caps offer no intraday
edge. Small caps with a fresh catalyst and thin float are where the outsized
ranges live.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import Config
from ..data.corp_actions import CorpActionsGuard
from ..data.floats import CrossValidatedFloat, float_band
from ..data.news import best_catalyst
from ..models import Candidate, CatalystType, NewsItem

log = logging.getLogger("wd.gapper")


@dataclass
class Snapshot:
    """Raw pre-market state for one symbol, as delivered by the data layer."""
    symbol: str
    exchange: str
    last: float
    prior_close: float
    premkt_vol: int
    premkt_high: float
    premkt_low: float
    cum_vol_baseline: float      # avg cumulative volume at this time-of-day, 30 sessions
    news: list[NewsItem]


def rvol_time_of_day(cum_vol_today: float, baseline: float) -> float:
    """Relative volume matched to time-of-day (§2.1): today's cumulative volume
    divided by the 30-day average cumulative volume at the same minute. A 9:40
    print is compared to 9:40 history, never to full-day averages."""
    return (cum_vol_today / baseline) if baseline > 0 else 0.0


def evaluate_snapshot(
    snap: Snapshot,
    cfg: Config,
    floats: CrossValidatedFloat,
    guard: CorpActionsGuard,
    now: datetime,
) -> Optional[Candidate]:
    """Apply the §2.1 5-point criteria. Returns a Candidate or None (with the
    reason logged) — every drop reason is also what the missed-move postmortem
    reports, so the logic lives in exactly one place."""
    u = cfg.universe

    if snap.exchange.upper() not in {e.upper() for e in u.exchanges}:
        return None
    if guard.excluded(snap.symbol, now.date()):
        log.info("%s excluded: corporate action with unknown ratio", snap.symbol)
        return None
    prior = guard.adjusted_prior_close(snap.symbol, snap.prior_close, now.date())
    if prior is None or prior <= 0:
        return None

    if not (u.price_min <= snap.last <= u.price_max):
        return None

    gap = (snap.last - prior) / prior
    if gap < u.pct_change_min:
        return None

    rvol = rvol_time_of_day(snap.premkt_vol, snap.cum_vol_baseline)
    if rvol < u.rvol_min:
        return None

    fi = floats.get(snap.symbol)
    if fi.shares is not None and fi.shares > u.float_max:
        return None

    cat, dilution = best_catalyst(snap.news, now, u.catalyst_max_age_hours)
    if dilution:
        log.info("%s excluded: offering/dilution headline (anti-catalyst)", snap.symbol)
        return None
    if u.catalyst_required and cat is None:
        return None

    a_grade = (fi.shares is not None and fi.verified and fi.shares < u.float_aplus)
    return Candidate(
        symbol=snap.symbol, gap_pct=round(gap, 4), last=snap.last,
        premkt_vol=snap.premkt_vol, rvol=round(rvol, 2),
        float_shares=fi.shares, float_unverified=not fi.verified,
        catalyst_headline=cat.headline if cat else "",
        catalyst_type=cat.catalyst_type if cat else CatalystType.OTHER,
        dilution_flag=False, premkt_high=snap.premkt_high, premkt_low=snap.premkt_low,
        exchange=snap.exchange, a_grade=a_grade,
    )


def rank(cands: list[Candidate]) -> list[Candidate]:
    """Sort by gap %; obviousness rank by (gap % × rvol) — the crowd's attention
    concentrates on #1 (§3.3), so every signal carries the rank."""
    by_attention = sorted(cands, key=lambda c: c.gap_pct * c.rvol, reverse=True)
    for i, c in enumerate(by_attention, 1):
        c.obviousness_rank = i
    return sorted(cands, key=lambda c: c.gap_pct, reverse=True)


def scan(snapshots: list[Snapshot], cfg: Config, floats: CrossValidatedFloat,
         guard: CorpActionsGuard, now: datetime) -> list[Candidate]:
    out = []
    for snap in snapshots:
        c = evaluate_snapshot(snap, cfg, floats, guard, now)
        if c is not None:
            out.append(c)
    return rank(out)[: cfg.scanners.top_table_rows]


def freeze_watchlist(cands: list[Candidate], cfg: Config) -> list[Candidate]:
    """At 9:15 ET: the top 3–5 A-grade names become the Gap & Go watchlist."""
    a = [c for c in cands if c.a_grade] or cands   # degrade honestly if no A-grades
    n = max(cfg.scanners.freeze_top_n_min, min(cfg.scanners.freeze_top_n_max, len(a)))
    return a[:n]


def write_watchlist_json(cands: list[Candidate], now: datetime, out_dir: str | Path) -> Path:
    p = Path(out_dir)
    p.mkdir(parents=True, exist_ok=True)
    dest = p / f"watchlist_{now.date().isoformat()}.json"
    dest.write_text(json.dumps(
        {"schema": 1, "generated_at": now.isoformat(),
         "rows": [c.model_dump() for c in cands]},
        indent=2, default=str))
    return dest


def render_table(cands: list[Candidate]) -> str:
    """Rich table for the terminal; returns plain text so tests can assert on it."""
    from rich.console import Console
    from rich.table import Table
    t = Table(title="Pre-market Top Gappers")
    for col in ("sym", "gap%", "last", "pm vol", "rvol", "float", "catalyst", "A+"):
        t.add_column(col)
    for c in cands:
        fl = "?" if c.float_shares is None else f"{c.float_shares/1e6:.1f}M"
        if c.float_unverified and c.float_shares is not None:
            fl += "*"
        t.add_row(c.symbol, f"{c.gap_pct:+.1%}", f"{c.last:.2f}", f"{c.premkt_vol:,}",
                  f"{c.rvol:.1f}x", fl, c.catalyst_type.value, "✓" if c.a_grade else "")
    console = Console(record=True, width=110)
    console.print(t)
    return console.export_text()
