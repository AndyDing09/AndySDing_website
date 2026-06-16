"""M7 hardening: gaps, halts, restart safety, loop resilience, partial fills."""
from datetime import datetime

from warrior.broker import SimBroker
from warrior.config import Config
from warrior.data.provider import AccountInfo
from warrior.data.synthetic import SyntheticProvider
from warrior.engine import TradingEngine
from warrior.models import Bar, OrderResult, Position, Side
from warrior.position_manager import PositionManager
from warrior.state import State

T0 = datetime(2026, 6, 16, 10, 0)


def _pm():
    cfg = Config()
    broker = SimBroker(AccountInfo(equity=30_000, buying_power=30_000))
    return cfg, broker, PositionManager(cfg, broker), State(path="/tmp/warrior_hard.json")


def test_gap_through_stop_fills_at_the_open_not_the_stop():
    cfg, broker, pm, st = _pm()
    broker.submit_bracket("ABCD", 100, 5.0, 4.8, 5.6)
    pos = Position(symbol="ABCD", qty=100, avg_entry=5.0, stop=4.8, target=5.6, opened_at=T0)
    st.open_positions["ABCD"] = pos
    # Candle gaps WAY down and opens at 4.50, below the 4.80 stop.
    gap = Bar(ts=T0, open=4.50, high=4.55, low=4.40, close=4.45, volume=5000)
    closed = pm.apply(pos, pm.decide(pos, gap), st, T0)
    assert closed is not None
    assert closed.exit == 4.50                  # filled at the worse open, not 4.80
    assert "GAPPED" in closed.exit_reason


def test_engine_holds_through_a_halt():
    bars = [Bar(ts=T0, open=5.0, high=5.1, low=4.70, close=4.80, volume=1000)]  # would hit stop
    provider = SyntheticProvider(bars={"ABCD": bars}, halted={"ABCD"})
    cfg = Config()
    broker = SimBroker(AccountInfo(equity=30_000, buying_power=30_000, status="SIM"))
    st = State(path="/tmp/warrior_hard_halt.json")
    eng = TradingEngine(cfg, provider, broker, state=st,
                        account=AccountInfo(equity=30_000, buying_power=30_000))
    pos = Position(symbol="ABCD", qty=100, avg_entry=5.0, stop=4.8, target=5.6, opened_at=T0)
    st.open_positions["ABCD"] = pos
    eng.manage_open_positions(T0)
    assert st.open_count == 1                    # never traded into the halt


def test_restart_preserves_open_position_and_counts(tmp_path):
    path = str(tmp_path / "state.json")
    st = State(path=path)
    st.start_session(datetime(2026, 6, 16).date())
    st.record_entry(Position(symbol="ABCD", qty=500, avg_entry=5.0, stop=4.8, target=5.6,
                             opened_at=T0), T0)
    st.day_pnl = -50.0
    st.save()
    # simulate a crash + restart
    st2 = State.load(path)
    st2.start_session(datetime(2026, 6, 16).date())   # same day -> no reset
    assert "ABCD" in st2.open_positions
    assert st2.trades_today == 1
    assert st2.day_pnl == -50.0
    assert st2.day_trade_dates == ["2026-06-16"]


def test_engine_step_survives_a_data_outage():
    class BrokenProvider(SyntheticProvider):
        def get_movers(self, limit=20):
            raise RuntimeError("data feed down")
        def get_bars(self, symbol, timeframe, limit=200):
            raise RuntimeError("data feed down")

    cfg = Config(paper_auto_approve=True)
    broker = SimBroker(AccountInfo(equity=30_000, buying_power=30_000, status="SIM"))
    st = State(path="/tmp/warrior_hard_outage.json")
    eng = TradingEngine(cfg, BrokenProvider(), broker, state=st,
                        account=AccountInfo(equity=30_000, buying_power=30_000))
    # A prime-time pass with a broken feed must NOT raise.
    eng.step(datetime(2026, 6, 16, 10, 0))
    assert st.open_count == 0


def test_partial_fill_tracked_in_position():
    from warrior.execution import ExecutionEngine
    from warrior.models import Grade, PatternKind, RiskDecision, SessionWindow, TradeProposal

    class PartialBroker(SimBroker):
        def submit_bracket(self, symbol, qty, entry_limit, stop, target):
            # broker only fills half
            super().submit_bracket(symbol, qty // 2, entry_limit, stop, target)
            return OrderResult(id="x", symbol=symbol, qty=qty // 2, side="buy",
                               status="partially_filled", filled_avg_price=entry_limit)

    cfg = Config(paper_auto_approve=True)
    broker = PartialBroker(AccountInfo(equity=30_000, buying_power=30_000, status="SIM"))
    eng = ExecutionEngine(cfg, broker)
    st = State(path="/tmp/warrior_hard_partial.json")
    p = TradeProposal(symbol="ABCD", side=Side.LONG, pattern=PatternKind.BULL_FLAG,
                      session_window=SessionWindow.PRIME, entry=5.0, stop=4.8, target=5.6,
                      stop_distance=0.2, reward_risk=3.0, shares=100, grade=Grade.A)
    p.decision = RiskDecision(approved=True)
    pos = eng.execute(p, st, T0, show=False)
    assert pos is not None
    assert pos.qty == 50                          # tracked the actual fill, not 100
