"""The kill switch flattens, cancels, and halts — even when the broker misbehaves."""
from warrior.kill import kill_switch
from warrior.state import State


class FakeBroker:
    def __init__(self, fail=False):
        self.fail = fail
        self.cancelled = False
        self.closed = False

    def cancel_all_orders(self):
        self.cancelled = True
        return 3

    def close_all_positions(self):
        self.closed = True
        return ["ABCD", "WXYZ"]


class BrokenBroker:
    def cancel_all_orders(self):
        raise RuntimeError("api down")

    def close_all_positions(self):
        raise RuntimeError("api down")


def test_kill_flattens_cancels_and_halts(tmp_path):
    st = State(path=str(tmp_path / "s.json"))
    b = FakeBroker()
    rep = kill_switch(st, b, reason="test")
    assert b.cancelled and b.closed
    assert rep["orders_cancelled"] == 3
    assert rep["positions_closed"] == ["ABCD", "WXYZ"]
    assert st.session_halted is True


def test_kill_halts_even_if_broker_fails(tmp_path):
    st = State(path=str(tmp_path / "s.json"))
    rep = kill_switch(st, BrokenBroker(), reason="test")
    assert st.session_halted is True          # halted despite errors
    assert len(rep["errors"]) == 2


def test_kill_without_broker_still_halts(tmp_path):
    st = State(path=str(tmp_path / "s.json"))
    rep = kill_switch(st, None)
    assert st.session_halted is True
    assert any("no broker" in e for e in rep["errors"])
