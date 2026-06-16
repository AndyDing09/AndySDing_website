"""Snapshot building for the website viewer."""
from datetime import datetime

from warrior.config import Config
from warrior.models import (
    Candidate, GauntletStep, Grade, PatternKind, RiskDecision, SessionWindow, Side,
    StepStatus, TradeProposal,
)
from warrior.publish import build_snapshot, proposal_to_dict


def _proposal():
    p = TradeProposal(symbol="WARR", side=Side.LONG, pattern=PatternKind.BULL_FLAG,
                      session_window=SessionWindow.PRIME, entry=3.78, stop=3.65, target=4.76,
                      stop_distance=0.13, reward_risk=7.5, shares=529, risk_dollars=69,
                      position_notional=2000, position_pct=0.2, grade=Grade.A, triggered=True,
                      mode="advisory", created_at=datetime(2026, 6, 16, 10, 31), approval="approved",
                      thesis="Clean bull flag, FDA catalyst.")
    p.metrics = {"rvol": 5.9, "price": 3.78, "catalyst": "fda",
                 "catalyst_headline": "Phase 3 win", "catalyst_source": "PR"}
    p.steps = [GauntletStep(6, "Pattern ID", StepStatus.PASS, "bull flag"),
               GauntletStep(9, "Targets & R:R", StepStatus.PASS, "R:R 7.5")]
    p.decision = RiskDecision(approved=True)
    return p


def test_proposal_to_dict_is_complete():
    d = proposal_to_dict(_proposal())
    assert d["symbol"] == "WARR" and d["grade"] == "A" and d["approved"] is True
    assert d["triggered"] is True
    assert d["entry"] == 3.78 and d["stop"] == 3.65 and d["shares"] == 529
    assert len(d["steps"]) == 2 and d["steps"][0]["status"] == "PASS"
    assert d["catalyst"]["classification"] == "fda"
    # catalyst_* keys are folded into the catalyst object, not left in metrics
    assert "catalyst_headline" not in d["metrics"]


def test_build_snapshot_shape():
    cfg = Config()
    session = {"window": "prime", "halted": False, "day_pnl": 0, "trades_today": 1,
               "consecutive_losses": 0, "open_positions": 1}
    snap = build_snapshot(cfg, mode="advisory", account_equity=10_000, session=session,
                          watchlist=[Candidate("WARR", price=3.78, gap_pct=0.46, rvol=5.9, score=6.8)],
                          proposals=[_proposal()], open_positions=[], journal=None)
    assert snap["schema"] == 1
    assert snap["mode"] == "advisory"
    assert snap["account_equity"] == 10_000
    assert len(snap["proposals"]) == 1 and snap["proposals"][0]["symbol"] == "WARR"
    assert len(snap["watchlist"]) == 1
    assert "disclaimer" in snap and "generated_at" in snap
