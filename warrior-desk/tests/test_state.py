"""State persistence + daily roll + restart safety."""
from datetime import date, datetime

from warrior.models import Position, Side
from warrior.state import State


def _state(tmp_path):
    return State(path=str(tmp_path / "state.json"))


def test_save_load_round_trip(tmp_path):
    st = _state(tmp_path)
    st.day_pnl = -42.5
    st.trades_today = 3
    st.consecutive_losses = 1
    pos = Position(symbol="ABCD", qty=500, avg_entry=5.0, stop=4.8, target=5.5, side=Side.LONG)
    st.open_positions["ABCD"] = pos
    st.save()

    st2 = State.load(str(tmp_path / "state.json"))
    assert st2.day_pnl == -42.5
    assert st2.trades_today == 3
    assert st2.open_positions["ABCD"].qty == 500
    assert st2.open_positions["ABCD"].side == Side.LONG


def test_start_session_resets_daily_counters_but_keeps_day_trades(tmp_path):
    st = _state(tmp_path)
    st.session_date = "2026-06-15"
    st.day_pnl = -100
    st.trades_today = 4
    st.consecutive_losses = 2
    st.session_halted = True
    st.day_trade_dates = ["2026-06-15", "2026-06-12"]
    st.start_session(date(2026, 6, 16))
    assert st.day_pnl == 0
    assert st.trades_today == 0
    assert st.consecutive_losses == 0
    assert st.session_halted is False
    # rolling day-trade history is preserved across days
    assert "2026-06-15" in st.day_trade_dates


def test_record_entry_counts_day_trade(tmp_path):
    st = _state(tmp_path)
    now = datetime(2026, 6, 16, 9, 40)
    pos = Position(symbol="ABCD", qty=500, avg_entry=5.0, stop=4.8, target=5.5)
    st.record_entry(pos, now)
    assert st.trades_today == 1
    assert st.day_trade_dates == ["2026-06-16"]
    assert st.symbol_last_dt("ABCD") == now


def test_record_close_tracks_loss_streak(tmp_path):
    st = _state(tmp_path)
    now = datetime(2026, 6, 16, 10, 0)
    st.record_close("ABCD", realized_pnl=-50, is_loss=True, now=now)
    assert st.consecutive_losses == 1
    assert st.day_pnl == -50
    assert st.last_loss_dt() == now
    # a win resets the streak
    st.record_close("WXYZ", realized_pnl=80, is_loss=False, now=now)
    assert st.consecutive_losses == 0
    assert st.day_pnl == 30


def test_corrupt_state_does_not_crash(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not valid json")
    st = State.load(str(p))
    assert st.day_pnl == 0.0  # fresh, no crash
