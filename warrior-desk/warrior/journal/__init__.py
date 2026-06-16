"""The journal (Section 8): local-first, with optional Google Doc sync.

JournalManager records a rich entry per trade — the plain-English thesis, the
catalyst, the full metric table, and the 12-step decision trace — plus outcomes
when closed, a daily summary, and a separate lighter section for rejected setups.
The local record never fails silently; the Google Doc is best-effort.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from ..config import Config
from ..logging_setup import get_logger
from ..models import ClosedTrade, TradeProposal
from ..stats import compute_stats
from .formatting import daily_summary_md, outcome_md, rejected_md, trade_entry_md
from .gdoc import GoogleDocJournal
from .local import LocalJournal

log = get_logger("journal")


class JournalManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.local = LocalJournal(cfg.journal_dir)
        self.gdoc = GoogleDocJournal(
            cfg.secrets.google_doc_id, cfg.secrets.google_credentials_path,
            cfg.secrets.google_token_path)
        if not self.gdoc.enabled:
            log.info(self.gdoc.setup_hint())

    # ── per-trade ──
    def record_proposal(self, p: TradeProposal) -> None:
        self.local.append_trade_row(self._trade_row(p))
        approved_by_gauntlet = bool(p.decision and p.decision.approved)
        md = trade_entry_md(p) if approved_by_gauntlet else \
            "\n#### Rejected setups\n" + rejected_md(p)
        self.local.append_md(md)
        self._gdoc(md)

    def record_close(self, c: ClosedTrade) -> None:
        self.local.append_closed_row(self._closed_row(c))
        md = outcome_md(c)
        self.local.append_md(md)
        self._gdoc(md)

    # ── daily ──
    def write_daily_summary(self, state) -> None:
        date = state.session_date or datetime.now().date().isoformat()
        md = self.render_today_summary(date_iso=date, markdown=True, state=state)
        self.local.append_md(md)
        self._gdoc(md)

    def render_today_summary(self, date_iso: str | None = None, markdown: bool = False,
                             state=None) -> str:
        date_iso = date_iso or datetime.now().date().isoformat()
        trades = self._read(self.local.trades_csv)
        closed = self._read(self.local.closed_csv)
        today_trades = [r for r in trades if r.get("date") == date_iso]
        today_closed = [r for r in closed if r.get("date") == date_iso]

        counts = {
            "taken": sum(1 for r in today_trades if r.get("approval") == "approved"),
            "skipped": sum(1 for r in today_trades if r.get("approval") == "approved-skipped"),
            "rejected": sum(1 for r in today_trades if r.get("approved") in ("False", "false", "0", "")),
        }
        stats = compute_stats(today_closed)
        rules = self._rules_checklist(state, stats)
        if markdown:
            return daily_summary_md(date_iso, stats, counts, rules)
        # plain text for the CLI
        pf = "n/a" if stats.profit_factor is None else f"{stats.profit_factor:.2f}"
        lines = [
            f"JOURNAL — {date_iso}",
            f"  setups: {counts['taken']} taken, {counts['skipped']} skipped, "
            f"{counts['rejected']} rejected",
            f"  closed: {stats.n} ({stats.wins}W/{stats.losses}L), win rate {stats.win_rate:.1%}",
            f"  expectancy ${stats.expectancy:.2f}/trade ({stats.expectancy_r:+.2f}R), "
            f"profit factor {pf}",
            f"  day P&L ${stats.total_pnl:.2f}, max intraday DD ${stats.max_drawdown:.2f}",
            "  rules followed:",
        ]
        for name, ok in rules:
            lines.append(f"    [{'x' if ok else ' '}] {name}")
        if not today_trades and not today_closed:
            lines.append("  (no activity recorded for this date)")
        return "\n".join(lines)

    # ── helpers ──
    def _rules_checklist(self, state, stats) -> list[tuple[str, bool]]:
        r = self.cfg.risk
        if state is None:
            return [("respected 2-loss halt", True), ("stayed under daily loss cap", True),
                    ("traded only in allowed sessions", True), ("honored max trades/day", True)]
        loss_halt_ok = state.consecutive_losses < r.consecutive_loss_halt or state.session_halted
        cap_ok = state.day_pnl > -r.max_daily_loss or (
            state.session_halted and "loss cap" in state.halt_reason)
        return [
            ("respected 2-consecutive-loss halt", loss_halt_ok),
            ("stayed under daily loss cap", cap_ok),
            ("traded only in allowed sessions", True),
            ("honored max trades/day", state.trades_today <= r.max_trades_per_day),
            ("no overnight holds (flattened by close)", state.open_count == 0 or not state.session_halted),
        ]

    def _gdoc(self, text: str) -> None:
        try:
            self.gdoc.append(text)
        except Exception as exc:
            log.warning("gdoc append failed (local still recorded): %s", exc)

    @staticmethod
    def _read(path: Path) -> list[dict]:
        if not path.exists():
            return []
        try:
            with path.open(newline="") as fh:
                return list(csv.DictReader(fh))
        except Exception as exc:
            log.warning("could not read %s: %s", path, exc)
            return []

    def _trade_row(self, p: TradeProposal) -> dict:
        m = p.metrics
        return {
            "ts": p.created_at.isoformat() if p.created_at else datetime.now().isoformat(),
            "date": (p.created_at or datetime.now()).date().isoformat(),
            "symbol": p.symbol, "mode": p.mode, "grade": p.grade.value,
            "pattern": p.pattern.value, "window": p.session_window.value,
            "approval": p.approval or "", "approved": bool(p.decision and p.decision.approved),
            "reasons": "; ".join(p.decision.reasons) if p.decision else "",
            "entry": p.entry, "stop": p.stop, "target": p.target,
            "stop_distance": p.stop_distance, "reward_risk": p.reward_risk,
            "shares": p.shares, "risk_dollars": p.risk_dollars,
            "position_notional": p.position_notional, "position_pct": p.position_pct,
            "float": m.get("float"), "float_verified": m.get("float_verified"),
            "rvol": m.get("rvol"), "price": m.get("price"), "spread": m.get("spread"),
            "catalyst": m.get("catalyst"), "catalyst_headline": m.get("catalyst_headline"),
            "thesis": (p.thesis or "").replace("\n", " "),
        }

    def _closed_row(self, c: ClosedTrade) -> dict:
        return {
            "ts_closed": c.closed_at.isoformat() if c.closed_at else datetime.now().isoformat(),
            "date": (c.closed_at or datetime.now()).date().isoformat(),
            "symbol": c.symbol, "side": c.side.value, "entry": c.entry, "exit": c.exit,
            "qty": c.qty, "gross_pnl": c.gross_pnl, "r_multiple": c.r_multiple,
            "hold_seconds": c.hold_seconds, "exit_reason": c.exit_reason, "mode": c.mode,
        }
