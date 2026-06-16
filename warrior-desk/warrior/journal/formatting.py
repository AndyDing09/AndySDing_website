"""Markdown formatting for journal entries, outcomes, and the daily summary."""

from __future__ import annotations

from datetime import datetime

from ..models import ClosedTrade, StepStatus, TradeProposal
from ..render import metric_rows, render_steps


def _ts(p: TradeProposal) -> str:
    return p.created_at.isoformat() if p.created_at else datetime.now().isoformat()


def _status_label(p: TradeProposal) -> str:
    if p.approval == "approved":
        return "TAKEN ✓"
    if p.approval == "approved-skipped":
        return "SKIPPED (passed gauntlet, Operator declined)"
    return "REJECTED ✗"


def trade_entry_md(p: TradeProposal) -> str:
    rows = metric_rows(p)
    table = "| metric | value |\n|---|---|\n" + "\n".join(f"| {k} | {v} |" for k, v in rows)
    cat = "none"
    if p.metrics.get("catalyst_headline"):
        cat = (f"{p.metrics.get('catalyst')} — \"{p.metrics['catalyst_headline']}\" "
               f"({p.metrics.get('catalyst_source', '')}"
               + (f", {p.metrics['catalyst_ts']}" if p.metrics.get('catalyst_ts') else "") + ")")
    elif p.metrics.get("catalyst"):
        cat = str(p.metrics["catalyst"])
    return (
        f"### {_status_label(p)} — {p.symbol} — grade {p.grade.value} — "
        f"{p.pattern.value} — {p.session_window.value}\n"
        f"- **When:** {_ts(p)}  |  **mode:** {p.mode}\n"
        f"- **Catalyst:** {cat}\n\n"
        f"**Why I took / skipped this trade:**\n\n{p.thesis or '(no thesis)'}\n\n"
        f"**Metrics:**\n\n{table}\n\n"
        f"**12-step decision trace:**\n\n```\n{render_steps(p)}\n```\n"
    )


def rejected_md(p: TradeProposal) -> str:
    """A lighter entry for setups that didn't clear the gauntlet — the Operator
    learns the most from seeing why a tempting chart didn't qualify."""
    reasons = "; ".join(p.decision.reasons) if p.decision else "did not qualify"
    failed = [f"#{s.number} {s.name}" for s in p.steps if s.status == StepStatus.FAIL]
    return (
        f"- **{p.symbol}** ({p.session_window.value}, {p.metrics.get('pattern', 'n/a')}): "
        f"REJECTED — {reasons}. "
        f"Failed: {', '.join(failed) if failed else 'n/a'}. "
        f"RVOL {p.metrics.get('rvol', 'n/a')}, float {p.metrics.get('float', 'n/a')}, "
        f"R:R {p.reward_risk:.2f}."
    )


def _lesson(c: ClosedTrade) -> str:
    if c.gross_pnl > 0 and "extension" in c.exit_reason:
        return "Sold into the spike — locked the parabolic move before the snap-back."
    if c.gross_pnl > 0 and "break-even" in c.exit_reason:
        return "Scaled at target, stop at break-even made it a free trade; held for more."
    if c.gross_pnl > 0:
        return "Let the winner work and took profit into strength."
    if "stop" in c.exit_reason:
        return "Stop did its job — small, defined loss; no revenge trade."
    if "first red" in c.exit_reason:
        return "Momentum faded on the first red candle; got out without giving it back."
    return "Followed the rules; review the entry timing next time."


def outcome_md(c: ClosedTrade) -> str:
    mins = int(c.hold_seconds // 60)
    secs = int(c.hold_seconds % 60)
    return (
        f"**Outcome — {c.symbol}:** exit @ {c.exit:.2f} ({c.qty} sh from {c.entry:.2f}), "
        f"gross P&L **${c.gross_pnl:.2f}** ({c.r_multiple:+.2f}R), hold {mins}m{secs:02d}s. "
        f"Exit: {c.exit_reason}.\n\n_What worked / what I'd do differently:_ {_lesson(c)}\n"
    )


def daily_summary_md(date: str, stats, counts: dict, rules: list[tuple[str, bool]]) -> str:
    pf = "n/a" if stats.profit_factor is None else f"{stats.profit_factor:.2f}"
    checklist = "\n".join(f"  - [{'x' if ok else ' '}] {name}" for name, ok in rules)
    return (
        f"\n## Daily summary — {date}\n"
        f"- Setups: **{counts.get('taken', 0)} taken**, "
        f"{counts.get('skipped', 0)} skipped, {counts.get('rejected', 0)} rejected\n"
        f"- Closed trades: {stats.n} ({stats.wins}W / {stats.losses}L), "
        f"win rate {stats.win_rate:.1%}\n"
        f"- Avg win/loss: ${stats.avg_win:.2f} / ${stats.avg_loss:.2f}; "
        f"profit factor {pf}; expectancy ${stats.expectancy:.2f}/trade ({stats.expectancy_r:+.2f}R)\n"
        f"- Largest win/loss: ${stats.largest_win:.2f} / ${stats.largest_loss:.2f}; "
        f"day P&L ${stats.total_pnl:.2f}; max intraday drawdown ${stats.max_drawdown:.2f}\n"
        f"- Rules-followed checklist:\n{checklist}\n"
    )
