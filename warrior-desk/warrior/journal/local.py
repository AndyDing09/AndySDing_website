"""Local-first journal: trades.csv + closed_trades.csv + journal.md.

Always works, never blocks a trade. Every write is guarded — if anything goes
wrong (or Google Docs is down) the local record still captures everything.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..disclaimer import DISCLAIMER_SHORT
from ..logging_setup import get_logger
from .glossary import GLOSSARY

log = get_logger("journal")

TRADE_FIELDS = [
    "ts", "date", "symbol", "mode", "grade", "pattern", "window", "approval",
    "approved", "reasons", "entry", "stop", "target", "stop_distance", "reward_risk",
    "shares", "risk_dollars", "position_notional", "position_pct", "float",
    "float_verified", "rvol", "price", "spread", "catalyst", "catalyst_headline", "thesis",
]
CLOSED_FIELDS = [
    "ts_closed", "date", "symbol", "side", "entry", "exit", "qty", "gross_pnl",
    "r_multiple", "hold_seconds", "exit_reason", "mode",
]


class LocalJournal:
    def __init__(self, journal_dir: str):
        self.dir = Path(journal_dir)
        self.trades_csv = self.dir / "trades.csv"
        self.closed_csv = self.dir / "closed_trades.csv"
        self.md = self.dir / "journal.md"
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._ensure_md_header()
        except Exception as exc:
            log.error("could not initialise journal dir %s: %s", journal_dir, exc)

    def _ensure_md_header(self) -> None:
        if self.md.exists():
            return
        header = (
            "# Warrior Desk — Learning Journal\n\n"
            f"> {DISCLAIMER_SHORT}\n\n"
            "This journal records every trade *and every setup the agent chose not to take* —\n"
            "the skips are where most of the learning is.\n\n"
            f"{GLOSSARY}\n\n---\n"
        )
        self.md.write_text(header)

    def _append_row(self, path: Path, fields: list[str], row: dict) -> None:
        try:
            new = not path.exists()
            with path.open("a", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
                if new:
                    w.writeheader()
                w.writerow(row)
        except Exception as exc:
            log.error("CSV append failed (%s): %s", path.name, exc)

    def append_trade_row(self, row: dict) -> None:
        self._append_row(self.trades_csv, TRADE_FIELDS, row)

    def append_closed_row(self, row: dict) -> None:
        self._append_row(self.closed_csv, CLOSED_FIELDS, row)

    def append_md(self, text: str) -> None:
        try:
            with self.md.open("a") as fh:
                fh.write("\n" + text.rstrip() + "\n")
        except Exception as exc:
            log.error("journal.md append failed: %s", exc)
