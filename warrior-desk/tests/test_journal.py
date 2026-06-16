"""Journal: local CSV/MD, decision traces, outcomes, daily summary, rejects."""
from datetime import datetime

from warrior.config import Config
from warrior.journal import JournalManager
from warrior.models import (
    ClosedTrade, GauntletStep, Grade, PatternKind, RiskDecision, SessionWindow,
    Side, StepStatus, TradeProposal,
)

NOW = datetime(2026, 6, 16, 9, 50)


def _cfg(tmp_path):
    c = Config()
    c.journal_dir = str(tmp_path / "journal")
    c.secrets.google_doc_id = ""        # gdoc disabled -> local only
    return c


def _proposal(approved=True, approval="approved", symbol="ABCD"):
    p = TradeProposal(symbol=symbol, side=Side.LONG, pattern=PatternKind.BULL_FLAG,
                      session_window=SessionWindow.PRIME, entry=3.78, stop=3.65, target=4.58,
                      stop_distance=0.13, reward_risk=6.1, shares=700, risk_dollars=91,
                      position_notional=2646, position_pct=0.09, grade=Grade.A,
                      mode="paper", created_at=NOW, approval=approval,
                      thesis="Clean bull flag with an FDA catalyst; 6:1 R:R.")
    p.metrics = {"float": 8_000_000, "float_verified": True, "rvol": 5.9, "price": 3.67,
                 "spread": 0.02, "pattern": "bull_flag", "catalyst": "fda",
                 "catalyst_headline": "Positive Phase 3", "catalyst_source": "PR"}
    p.steps = [GauntletStep(1, "Session & regime", StepStatus.PASS, "prime"),
               GauntletStep(9, "Targets & R:R", StepStatus.PASS, "R:R 6.1 >= 2.0")]
    p.decision = RiskDecision(approved=approved,
                              reasons=[] if approved else ["reward_risk>=min: 1.0 < 2.0"])
    return p


def test_journal_header_has_glossary_and_disclaimer(tmp_path):
    JournalManager(_cfg(tmp_path))
    md = (tmp_path / "journal" / "journal.md").read_text()
    assert "Glossary" in md
    assert "not investment advice" in md.lower()


def test_record_taken_trade_writes_csv_and_md(tmp_path):
    jm = JournalManager(_cfg(tmp_path))
    jm.record_proposal(_proposal())
    csv_text = (tmp_path / "journal" / "trades.csv").read_text()
    assert "ABCD" in csv_text and "approved" in csv_text
    md = (tmp_path / "journal" / "journal.md").read_text()
    assert "TAKEN" in md
    assert "| metric | value |" in md           # metric table
    assert "12-step decision trace" in md         # trace
    assert "FDA catalyst" in md or "bull flag" in md.lower() or "Clean bull flag" in md


def test_rejected_setup_goes_to_lighter_section(tmp_path):
    jm = JournalManager(_cfg(tmp_path))
    p = _proposal(approved=False, approval="rejected", symbol="JUNK")
    jm.record_proposal(p)
    md = (tmp_path / "journal" / "journal.md").read_text()
    assert "Rejected setups" in md
    assert "JUNK" in md and "REJECTED" in md


def test_record_close_and_outcome(tmp_path):
    jm = JournalManager(_cfg(tmp_path))
    c = ClosedTrade(symbol="ABCD", side=Side.LONG, entry=3.78, exit=4.58, qty=700,
                    gross_pnl=560.0, r_multiple=6.1, opened_at=NOW, closed_at=NOW,
                    hold_seconds=420, exit_reason="first target ~2R — sold half", mode="paper")
    jm.record_close(c)
    closed = (tmp_path / "journal" / "closed_trades.csv").read_text()
    assert "ABCD" in closed and "560.0" in closed
    md = (tmp_path / "journal" / "journal.md").read_text()
    assert "Outcome" in md and "+6.10R" in md


def test_daily_summary_counts_taken_skipped_rejected(tmp_path):
    cfg = _cfg(tmp_path)
    jm = JournalManager(cfg)
    jm.record_proposal(_proposal(approval="approved", symbol="AAA"))
    jm.record_proposal(_proposal(approval="approved-skipped", symbol="BBB"))
    jm.record_proposal(_proposal(approved=False, approval="rejected", symbol="CCC"))
    c = ClosedTrade(symbol="AAA", side=Side.LONG, entry=3.78, exit=4.58, qty=700,
                    gross_pnl=560.0, r_multiple=6.1, closed_at=NOW, exit_reason="target", mode="paper")
    jm.record_close(c)
    text = jm.render_today_summary(date_iso="2026-06-16")
    assert "1 taken" in text and "1 skipped" in text and "1 rejected" in text
    assert "win rate 100.0%" in text


def test_gdoc_degrades_gracefully(tmp_path):
    jm = JournalManager(_cfg(tmp_path))
    assert jm.gdoc.enabled is False
    # append returns False but never raises, and local write still happens
    jm.record_proposal(_proposal())
    assert (tmp_path / "journal" / "trades.csv").exists()
