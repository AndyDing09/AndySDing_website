"""Backtest replay through the identical gauntlet + the entry-trigger gate."""
from types import SimpleNamespace

from warrior.backtest import run_backtest
from warrior.config import Config
from warrior.broker import SimBroker
from warrior.data.provider import AccountInfo
from warrior.demo import DemoProvider, _flag_bars
from warrior.engine import TradingEngine
from warrior.stats import compute_stats, read_closed_trades
from warrior.state import State


def test_demo_backtest_produces_a_winning_round_trip(tmp_path):
    cfg = Config()
    cfg.journal_dir = str(tmp_path / "journal")
    args = SimpleNamespace(demo=True, symbol=None, bars=None, equity=30_000.0)
    rc = run_backtest(cfg, args)
    assert rc == 0
    closed = read_closed_trades(str(tmp_path / "journal" / "backtest" / "closed_trades.csv"))
    assert len(closed) == 1
    s = compute_stats(closed)
    assert s.total_pnl > 0          # the clean A-grade setup wins in the sim
    assert s.wins == 1


def test_entry_waits_for_confirmed_breakout():
    """A valid setup that hasn't broken out yet must NOT be entered."""
    cfg = Config(paper_auto_approve=True)
    acct = AccountInfo(equity=30_000, buying_power=30_000, status="SIM")
    broker = SimBroker(acct)
    st = State(path="/tmp/warrior_bt_trigger_state.json")
    # _flag_bars ends on the pullback (no breakout) -> not triggered.
    provider = DemoProvider(intraday=_flag_bars())
    from warrior.demo import DEMO_NOW
    eng = TradingEngine(cfg, provider, broker, state=st, account=acct)
    st.start_session(DEMO_NOW.date())
    eng.maybe_enter(DEMO_NOW, approval_fn=lambda _p: True)
    assert st.open_count == 0           # ready but not triggered -> no entry


def test_entry_fires_on_confirmed_breakout():
    cfg = Config(paper_auto_approve=True)
    acct = AccountInfo(equity=30_000, buying_power=30_000, status="SIM")
    broker = SimBroker(acct)
    st = State(path="/tmp/warrior_bt_trigger_state2.json")
    provider = DemoProvider()           # default _intraday ends with a breakout candle
    from warrior.demo import DEMO_NOW
    eng = TradingEngine(cfg, provider, broker, state=st, account=acct)
    st.start_session(DEMO_NOW.date())
    eng.maybe_enter(DEMO_NOW, approval_fn=lambda _p: True)
    assert st.open_count == 1           # triggered -> entered
