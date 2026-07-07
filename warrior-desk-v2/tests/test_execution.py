"""Phase 4: slippage honesty, bracket structure, trailing, time stop, kill, reconcile."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.config import Config
from src.execution.broker import SimBroker
from src.execution.kill_switch import KillSwitch
from src.execution.slippage import entry_fill_price, stop_fill_price, target_fill_price
from src.execution.trailing import PositionManager
from src.models import Bar, Position, Quote, SetupName, Signal
from src.risk.circuit_breakers import CircuitBreakers
from src.risk.reconciliation import Reconciler, reconcile

CFG = Config()
NOW = datetime(2026, 7, 6, 14, 0, tzinfo=timezone.utc)      # 10:00 ET
LATE = datetime(2026, 7, 6, 19, 56, tzinfo=timezone.utc)    # 15:56 ET


def sig(entry=5.00, stop=4.80, target=5.50, shares=250):
    return Signal(ts=NOW, symbol="ABCD", setup=SetupName.BULL_FLAG, entry=entry,
                  stop=stop, target=target, shares=shares)


def quote(bid=4.99, ask=5.01):
    return Quote(symbol="ABCD", ts=NOW, bid=bid, ask=ask, feed="test")


def bar(o, h, l, c, i=0, v=10_000):
    return Bar(symbol="ABCD", ts=NOW + timedelta(minutes=i), open=o, high=h, low=l,
               close=c, volume=v, feed="test")


# ── slippage (§7.2) ──
def test_entry_pays_the_ask_plus_ticks():
    px = entry_fill_price(ask=5.01, spread_pct=0.002, cfg=CFG.slippage,
                          max_spread_pct=CFG.risk.max_spread_pct)
    assert px == 5.02                                     # ask + 1 tick


def test_stop_out_gets_bid_minus_tick():
    px = stop_fill_price(bid=4.79, spread_pct=0.002, cfg=CFG.slippage,
                         max_spread_pct=CFG.risk.max_spread_pct)
    assert px == 4.78


def test_wide_spread_scales_slippage_up():
    # spread 2.5% with a 1% cap -> 2 extra ticks on top of the base tick
    px = entry_fill_price(ask=5.01, spread_pct=0.025, cfg=CFG.slippage,
                          max_spread_pct=CFG.risk.max_spread_pct)
    assert px == pytest.approx(5.04)


def test_target_never_gets_positive_slippage():
    assert target_fill_price(5.50) == 5.50


# ── SimBroker brackets ──
def test_sim_bracket_fills_with_slippage_and_long_only_structure():
    b = SimBroker(CFG)
    pos = b.submit_bracket(sig(), NOW, quote())
    assert pos.entry == 5.02                              # slipped entry recorded
    assert b.fills[0].intended_price == 5.00
    assert b.fills[0].slippage == pytest.approx(0.02)
    with pytest.raises(AssertionError):                   # short-shaped bracket impossible
        b.submit_bracket(sig(entry=5.0, stop=5.2, target=4.5), NOW, quote())


def test_stop_never_widens():
    b = SimBroker(CFG)
    pos = b.submit_bracket(sig(), NOW, quote())
    b.replace_stop(pos, 4.70)                             # widening ignored
    assert pos.stop == 4.80
    b.replace_stop(pos, 5.00)                             # ratchet up allowed
    assert pos.stop == 5.00


# ── trailing / exits (§2.3) ──
def _pos(b=None):
    b = b or SimBroker(CFG)
    return b, b.submit_bracket(sig(), NOW, quote())       # entry 5.02, stop 4.80


def test_stop_hit_exits():
    b, pos = _pos()
    d = PositionManager(CFG.exits).on_bar(pos, bar(4.95, 4.96, 4.75, 4.78), [4.9], NOW)
    assert d.action == "exit" and d.reason == "stop"


def test_target_hit_exits():
    b, pos = _pos()
    d = PositionManager(CFG.exits).on_bar(pos, bar(5.4, 5.55, 5.38, 5.5), [5.4], NOW)
    assert d.action == "exit" and d.reason == "target"


def test_same_bar_stop_and_target_resolves_pessimistically():
    b, pos = _pos()
    d = PositionManager(CFG.exits).on_bar(pos, bar(5.0, 5.60, 4.70, 5.2), [5.0], NOW)
    assert d.reason == "stop"                             # honest assumption


def test_breakeven_at_plus_1r():
    b, pos = _pos()                                       # risk/share = 0.22
    r1_price = pos.entry + pos.risk_per_share             # +1R
    d = PositionManager(CFG.exits).on_bar(
        pos, bar(5.1, r1_price + 0.01, 5.08, r1_price), [5.1, r1_price], NOW)
    assert d.action == "hold"
    assert pos.breakeven_moved and pos.stop == pos.entry


def test_trails_9ema_after_plus_2r_and_only_ratchets():
    b, pos = _pos()
    r2 = pos.entry + 2 * pos.risk_per_share
    closes = [pos.entry + i * 0.05 for i in range(12)]    # rising tape -> rising EMA
    pm = PositionManager(CFG.exits)
    pm.on_bar(pos, bar(r2 - 0.02, r2 + 0.02, r2 - 0.05, r2, i=1), closes, NOW)
    assert pos.trailing
    stop_after = pos.stop
    assert stop_after > pos.entry                         # EMA above breakeven by now
    # a falling EMA must NOT pull the stop back down
    falling = closes + [pos.entry - 1.0] * 12
    pm.on_bar(pos, bar(r2, r2 + 0.01, r2 - 0.03, r2, i=2), falling, NOW)
    assert pos.stop >= stop_after


def test_time_stop_flattens_at_1555():
    b, pos = _pos()
    d = PositionManager(CFG.exits).on_bar(pos, bar(5.1, 5.12, 5.08, 5.1), [5.1], LATE)
    assert d.action == "exit" and d.reason == "time_stop"


def test_mae_mfe_tracked():
    b, pos = _pos()
    pm = PositionManager(CFG.exits)
    pm.on_bar(pos, bar(5.0, 5.10, 4.85, 5.05), [5.0], NOW)
    assert pos.mae == pytest.approx(4.85 - pos.entry)
    assert pos.mfe == pytest.approx(5.10 - pos.entry)


# ── kill switch (§7.7) ──
def test_kill_switch_flattens_locks_and_survives_restart(tmp_path):
    b = SimBroker(CFG)
    b.submit_bracket(sig(), NOW, quote())
    breakers = CircuitBreakers(CFG.risk)
    ks = KillSwitch(b, breakers, lock_path=tmp_path / "HALTED")
    report = ks.halt("test")
    assert report["flattened"] == ["ABCD"] and not b.open_positions()
    assert not breakers.entries_allowed(NOW)[0]
    # a fresh process sees the same lock file
    ks2 = KillSwitch(SimBroker(CFG), CircuitBreakers(CFG.risk), lock_path=tmp_path / "HALTED")
    assert ks2.is_halted()
    ks.resume()
    assert not ks.is_halted() and breakers.entries_allowed(NOW)[0]


def test_kill_switch_locks_even_if_broker_fails(tmp_path):
    class Broken:
        def cancel_all_orders(self):   raise RuntimeError("api down")
        def close_all_positions(self): raise RuntimeError("api down")
    breakers = CircuitBreakers(CFG.risk)
    ks = KillSwitch(Broken(), breakers, lock_path=tmp_path / "HALTED")
    report = ks.halt("broker outage")
    assert len(report["errors"]) == 2
    assert ks.is_halted() and not breakers.entries_allowed(NOW)[0]


# ── reconciliation (§4.8) ──
def _p(sym, qty):
    return Position(symbol=sym, qty=qty, entry=5.0, stop=4.8, target=5.5,
                    opened_at=NOW, signal_ts=NOW, setup=SetupName.BULL_FLAG)


def test_reconcile_clean():
    res = reconcile([_p("ABCD", 100)], [_p("ABCD", 100)], 5000, 5010)
    assert res.ok


def test_reconcile_detects_all_mismatch_shapes():
    res = reconcile([_p("ABCD", 100), _p("WXYZ", 50)], [_p("ABCD", 90)], 5000, 6000)
    kinds = " ".join(res.mismatches)
    assert "qty drift" in kinds and "local state holds WXYZ" in kinds and "equity drift" in kinds


def test_reconciler_freezes_entries_on_mismatch():
    breakers = CircuitBreakers(CFG.risk)
    alerts = []
    r = Reconciler(breakers, store=None, alert=lambda k, m: alerts.append((k, m)))
    res = r.run([_p("ABCD", 100)], [], 5000, 5000, NOW)
    assert not res.ok
    ok, reason = breakers.entries_allowed(NOW)
    assert not ok and "reconciliation" in reason
    assert alerts and alerts[0][0] == "RECONCILE"
