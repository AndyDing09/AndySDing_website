"""The 3-tier exit logic (§2.7)."""
from datetime import datetime, timedelta

from warrior.broker import SimBroker
from warrior.config import Config
from warrior.data.provider import AccountInfo
from warrior.models import Bar, Position, Side
from warrior.position_manager import PositionManager
from warrior.state import State

T0 = datetime(2026, 6, 16, 9, 50)


def _bar(o, h, l, c, v=10_000, i=0):
    return Bar(ts=T0 + timedelta(minutes=i), open=o, high=h, low=l, close=c, volume=v)


def setup(qty=100, entry=5.0, stop=4.8, target=5.6):
    cfg = Config()
    broker = SimBroker(AccountInfo(equity=30_000, buying_power=30_000))
    pm = PositionManager(cfg, broker)
    st = State(path="/tmp/warrior_pm_state.json")
    # The broker keeps its own ledger (via the bracket order); the engine/state
    # holds a SEPARATE Position object that the PM manages — mirroring real flow.
    broker.submit_bracket("ABCD", qty, entry, stop, target)
    pos = Position(symbol="ABCD", qty=qty, avg_entry=entry, stop=stop, target=target,
                   side=Side.LONG, opened_at=T0)
    st.open_positions["ABCD"] = pos
    return cfg, broker, pm, st, pos


def test_protective_stop_exit_is_a_loss():
    cfg, broker, pm, st, pos = setup()
    bar = _bar(4.95, 4.98, 4.70, 4.85)   # low pierces the 4.80 stop
    closed = pm.apply(pos, pm.decide(pos, bar), st, T0)
    assert closed is not None
    assert closed.gross_pnl < 0
    assert st.consecutive_losses == 1
    assert broker.get_position("ABCD") is None


def test_first_target_scales_half_and_moves_stop_to_breakeven():
    cfg, broker, pm, st, pos = setup()
    # risk 0.20 -> first target 2R = 5.40. atr=None so no extension.
    bar = _bar(5.30, 5.45, 5.28, 5.42, i=1)
    actions = pm.decide(pos, bar, atr=None)
    kinds = [a.kind for a in actions]
    assert "scale_half" in kinds and "move_stop_breakeven" in kinds
    pm.apply(pos, actions, st, bar.ts)
    assert pos.qty == 50
    assert pos.scaled is True
    assert pos.stop == 5.0                 # moved to break-even
    assert st.day_pnl == 20.0               # 50 sh * $0.40 locked


def test_after_scale_breakeven_stop_keeps_trade_free():
    cfg, broker, pm, st, pos = setup()
    pm.apply(pos, pm.decide(pos, _bar(5.30, 5.45, 5.28, 5.42, i=1), atr=None), st, T0)
    # later bar dips to break-even
    closed = pm.apply(pos, pm.decide(pos, _bar(5.05, 5.10, 4.95, 5.0, i=5)), st, T0)
    assert closed is not None
    assert closed.gross_pnl >= 0           # worst case flat — the trade was free
    assert st.consecutive_losses == 0


def test_first_red_candle_exit_before_scaling():
    cfg, broker, pm, st, pos = setup()
    bar = _bar(5.05, 5.10, 4.90, 4.95, i=1)   # red, above stop, below first target
    closed = pm.apply(pos, pm.decide(pos, bar), st, bar.ts)
    assert closed is not None
    assert "first red candle" in closed.exit_reason


def test_extension_bar_sells_into_the_spike():
    cfg, broker, pm, st, pos = setup()
    # ext level = 5.0 + 4*0.2 = 5.80 ; parabolic if (close-open) >= 2*atr
    bar = _bar(5.40, 5.95, 5.39, 5.88, i=2)
    closed = pm.apply(pos, pm.decide(pos, bar, atr=0.10), st, bar.ts)
    assert closed is not None
    assert "extension" in closed.exit_reason
    assert closed.exit <= 5.80 + 1e-9       # sold into the spike near the ~4R level


def test_hold_when_nothing_triggers():
    cfg, broker, pm, st, pos = setup()
    bar = _bar(5.05, 5.20, 5.02, 5.15, i=1)   # green, below first target, above stop
    actions = pm.decide(pos, bar, atr=None)
    assert actions[0].kind == "hold"


def test_flatten_closes_position():
    cfg, broker, pm, st, pos = setup()
    closed = pm.flatten(pos, 5.10, st, T0, reason="EOD flatten")
    assert closed is not None
    assert broker.get_position("ABCD") is None
    assert "EOD" in closed.exit_reason
