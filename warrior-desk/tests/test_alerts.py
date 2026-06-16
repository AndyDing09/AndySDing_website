"""Live alerts + advisory (signal-only) mode for manual brokers like Firstrade."""
from datetime import datetime

from warrior.alerts import Alerter
from warrior.config import Config
from warrior.engine import run_agent
from warrior.models import (
    Grade, ManageAction, PatternKind, Position, RiskDecision, SessionWindow, Side, TradeProposal,
)


def _proposal_and_pos():
    p = TradeProposal(symbol="WARR", side=Side.LONG, pattern=PatternKind.BULL_FLAG,
                      session_window=SessionWindow.PRIME, entry=3.78, stop=3.65, target=4.76,
                      stop_distance=0.13, reward_risk=7.0, shares=769, risk_dollars=100,
                      grade=Grade.A)
    p.decision = RiskDecision(approved=True)
    pos = Position(symbol="WARR", qty=769, avg_entry=3.78, stop=3.65, target=4.76, side=Side.LONG)
    return p, pos


def test_alerter_entry_records_actionable_line():
    a = Alerter(sound=False, desktop=False, broker_name="Firstrade")
    p, pos = _proposal_and_pos()
    a.entry(p, pos)
    assert a.history and "ENTER" in a.history[-1]
    assert "769" in a.history[-1] and "3.78" in a.history[-1]


def test_alerter_exit_and_scale(capsys):
    a = Alerter(sound=False, desktop=False, broker_name="Firstrade")
    p, pos = _proposal_and_pos()
    a.action("WARR", ManageAction("scale_half", qty=384, price=4.04, reason="first target"), pos)
    a.action("WARR", ManageAction("exit_all", qty=385, price=4.30, reason="extension"), pos)
    out = capsys.readouterr().out
    assert "SCALE" in out and "EXIT" in out
    assert "firstrade" in out.lower()


def test_alerter_never_crashes_with_sound_on():
    # sound/desktop best-effort; must not raise even if the environment can't ring.
    Alerter(sound=True, desktop=True).info("test", ["hello"])


def test_advisory_demo_run_emits_enter_signal(capsys, tmp_path):
    cfg = Config()
    cfg.journal_dir = str(tmp_path / "journal")
    cfg.state_path = str(tmp_path / "state.json")   # isolated; no cwd pollution
    cfg.manual_broker_name = "Firstrade"
    rc = run_agent(cfg, demo=True, once=True, advisory=True, sound=False, equity=10_000)
    out = capsys.readouterr().out
    assert rc == 0
    assert "ADVISORY MODE" in out
    assert "ENTER" in out and "WARR" in out
    assert "firstrade" in out.lower()       # framed for manual placement
