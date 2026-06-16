"""Acceptance: the LLM reasoning layer cannot alter any gate."""
from datetime import datetime

from warrior.config import Config
from warrior.gauntlet import Gauntlet
from warrior.models import (
    Grade, PatternKind, RiskDecision, SessionWindow, Side, TradeProposal,
)
from warrior.reasoning import TemplateReasoner


class MaliciousReasoner:
    """Tries every dirty trick to flip a rejected trade into an approval."""
    def write_thesis(self, p: TradeProposal) -> str:
        try:
            p.decision.approved = True
            p.decision.reasons = []
            p.grade = Grade.A
        except Exception:
            pass
        return "OVERRIDE: this is a great trade, approve it!"


def _rejected_proposal() -> TradeProposal:
    p = TradeProposal(symbol="ABCD", side=Side.LONG, pattern=PatternKind.BULL_FLAG,
                      session_window=SessionWindow.PRIME, entry=5.0, stop=4.8, target=5.2,
                      stop_distance=0.2, reward_risk=1.0, shares=100, grade=Grade.B)
    p.decision = RiskDecision(approved=False, gates=[],
                              reasons=["reward_risk>=min: R:R 1.00 < 2.00"])
    return p


def test_malicious_reasoner_cannot_flip_decision():
    g = Gauntlet(Config(), provider=None, reasoner=MaliciousReasoner())
    p = _rejected_proposal()
    g._thesis(p)
    # The thesis text is attached...
    assert "OVERRIDE" in p.thesis
    # ...but the authoritative decision is untouched.
    assert p.decision.approved is False
    assert any("reward_risk" in r for r in p.decision.reasons)


def test_template_reasoner_explains_approved():
    p = TradeProposal(symbol="ABCD", side=Side.LONG, pattern=PatternKind.BULL_FLAG,
                      session_window=SessionWindow.PRIME, entry=3.78, stop=3.65, target=4.58,
                      stop_distance=0.13, reward_risk=6.1, shares=769, risk_dollars=100,
                      position_notional=2906, position_pct=0.1, grade=Grade.A)
    p.decision = RiskDecision(approved=True)
    p.metrics = {"pattern": "bull_flag", "rvol": 5.9, "catalyst": "fda",
                 "macd_state": "bullish", "rsi_state": "60 neutral", "vwap_held": True,
                 "float_verified": True}
    text = TemplateReasoner().write_thesis(p)
    assert "TAKING" in text and "2:1" in text


def test_template_reasoner_explains_skip():
    text = TemplateReasoner().write_thesis(_rejected_proposal())
    assert "SKIPPING" in text and "reward_risk" in text
