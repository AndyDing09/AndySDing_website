"""Engine session mechanics: entry, managed exit, EOD flatten, day halts."""
from datetime import datetime

from warrior.broker import SimBroker
from warrior.config import Config
from warrior.data.provider import AccountInfo
from warrior.data.synthetic import SyntheticProvider
from warrior.demo import DEMO_NOW, DemoProvider
from warrior.engine import TradingEngine
from warrior.models import Bar, Position, Side
from warrior.state import State


def _engine(provider, cfg=None, equity=30_000):
    cfg = cfg or Config(paper_auto_approve=True)
    acct = AccountInfo(equity=equity, cash=equity, buying_power=equity, status="SIM")
    broker = SimBroker(acct)
    st = State(path="/tmp/warrior_engine_state.json")
    return TradingEngine(cfg, provider, broker, state=st, account=acct), broker, st


def test_engine_enters_on_a_qualifying_candidate():
    eng, broker, st = _engine(DemoProvider())
    st.start_session(DEMO_NOW.date())
    eng.maybe_enter(DEMO_NOW, approval_fn=lambda _p: True)
    assert st.open_count == 1
    assert broker.get_position("WARR") is not None


def test_engine_eod_flatten_and_halt():
    eng, broker, st = _engine(DemoProvider())
    st.start_session(DEMO_NOW.date())
    eng.maybe_enter(DEMO_NOW, approval_fn=lambda _p: True)
    assert st.open_count == 1
    eng.step(datetime(2026, 6, 16, 15, 56), approval_fn=lambda _p: True)
    assert st.open_count == 0
    assert st.session_halted is True
    assert "end of day" in st.halt_reason or "EOD" in st.halt_reason


def test_engine_day_loss_halt_stops_trading():
    eng, broker, st = _engine(DemoProvider())
    st.start_session(DEMO_NOW.date())
    st.day_pnl = -300.0
    eng.check_day_halts(DEMO_NOW)
    assert st.session_halted is True
    # and a halted session refuses new entries
    eng.maybe_enter(DEMO_NOW, approval_fn=lambda _p: True)
    assert st.open_count == 0


def test_engine_manage_exits_on_stop():
    bars = [
        Bar(ts=datetime(2026, 6, 16, 9, 50), open=5.0, high=5.1, low=5.0, close=5.05, volume=1000),
        Bar(ts=datetime(2026, 6, 16, 9, 51), open=5.0, high=5.02, low=4.70, close=4.80, volume=2000),
    ]
    provider = SyntheticProvider(bars={"ABCD": bars})
    eng, broker, st = _engine(provider)
    st.start_session(datetime(2026, 6, 16).date())
    broker.submit_bracket("ABCD", 100, 5.0, 4.8, 5.6)
    pos = Position(symbol="ABCD", qty=100, avg_entry=5.0, stop=4.8, target=5.6,
                   side=Side.LONG, opened_at=datetime(2026, 6, 16, 9, 50))
    st.open_positions["ABCD"] = pos
    eng.manage_open_positions(datetime(2026, 6, 16, 9, 51))
    assert st.open_count == 0
    assert st.consecutive_losses == 1     # exited at the protective stop for a loss


def test_engine_respects_max_concurrent_positions():
    eng, broker, st = _engine(DemoProvider())
    st.start_session(DEMO_NOW.date())
    # pretend we already hold one position
    st.open_positions["XYZ"] = Position(symbol="XYZ", qty=10, avg_entry=2.0, stop=1.9, target=2.3)
    eng.maybe_enter(DEMO_NOW, approval_fn=lambda _p: True)
    assert "WARR" not in st.open_positions   # blocked: max_concurrent_positions = 1
