"""The human-approval gate + bracket submission."""
from datetime import datetime

from warrior.broker import SimBroker
from warrior.config import Config
from warrior.data.provider import AccountInfo
from warrior.execution import ExecutionEngine
from warrior.models import Grade, PatternKind, RiskDecision, SessionWindow, Side, TradeProposal
from warrior.state import State

NOW = datetime(2026, 6, 16, 9, 50)


def approved_proposal():
    p = TradeProposal(symbol="ABCD", side=Side.LONG, pattern=PatternKind.BULL_FLAG,
                      session_window=SessionWindow.PRIME, entry=3.78, stop=3.65, target=4.58,
                      stop_distance=0.13, reward_risk=6.1, shares=700, risk_dollars=91,
                      position_notional=2646, position_pct=0.09, grade=Grade.A, mode="paper")
    p.decision = RiskDecision(approved=True)
    return p


def setup(cfg=None):
    cfg = cfg or Config()
    broker = SimBroker(AccountInfo(equity=30_000, buying_power=30_000, status="SIM"))
    eng = ExecutionEngine(cfg, broker)
    st = State(path="/tmp/warrior_exec_state.json")
    return cfg, broker, eng, st


def test_paper_auto_approve_executes():
    cfg, broker, eng, st = setup(Config(paper_auto_approve=True))
    pos = eng.execute(approved_proposal(), st, NOW, show=False)
    assert pos is not None
    assert broker.get_position("ABCD") is not None
    assert st.open_count == 1
    assert st.trades_today == 1


def test_operator_skip_places_no_order():
    cfg, broker, eng, st = setup()
    p = approved_proposal()
    pos = eng.execute(p, st, NOW, approval_fn=lambda _p: False, show=False)
    assert pos is None
    assert broker.get_position("ABCD") is None
    assert p.approval == "approved-skipped"


def test_operator_approve_places_order():
    cfg, broker, eng, st = setup()
    p = approved_proposal()
    pos = eng.execute(p, st, NOW, approval_fn=lambda _p: True, show=False)
    assert pos is not None
    assert p.approval == "approved"
    assert pos.initial_risk == round(3.78 - 3.65, 4)


def test_rejected_proposal_never_executes():
    cfg, broker, eng, st = setup(Config(paper_auto_approve=True))
    p = approved_proposal()
    p.decision = RiskDecision(approved=False, reasons=["reward_risk>=min: 1.0 < 2.0"])
    pos = eng.execute(p, st, NOW, show=False)
    assert pos is None
    assert p.approval == "rejected"


def test_live_ignores_paper_auto_approve():
    # In live, the gate is mandatory even with paper_auto_approve set.
    cfg, broker, eng, st = setup(Config(trading_mode="live", paper_auto_approve=True))
    p = approved_proposal()
    pos = eng.execute(p, st, NOW, approval_fn=lambda _p: False, show=False)
    assert pos is None  # auto-approve did NOT apply; the (declining) gate ran
    assert p.approval == "approved-skipped"
