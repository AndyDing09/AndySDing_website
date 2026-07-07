"""Stale-data detection (§4.3) and clock discipline (§4.7)."""
from datetime import datetime, timedelta, timezone

import pytest

from src.data.clock import ClockSkewError, check_skew, in_window, minute_of_session, ny
from src.data.stale import StaleMonitor

T0 = datetime(2026, 7, 6, 14, 0, tzinfo=timezone.utc)  # 10:00 ET


def test_symbol_goes_stale_while_spy_ticks():
    m = StaleMonitor(symbol_timeout=5.0, stream_timeout=10.0)
    m.on_tick("SPY", T0)
    m.on_tick("ABCD", T0)
    # 6s later SPY has ticked again, ABCD hasn't
    m.on_tick("SPY", T0 + timedelta(seconds=6))
    stale, gap = m.sweep(T0 + timedelta(seconds=6))
    assert "ABCD" in stale and m.is_stale("ABCD")
    assert not gap
    # ABCD prints again -> no longer stale
    m.on_tick("ABCD", T0 + timedelta(seconds=7))
    assert not m.is_stale("ABCD")


def test_symbol_not_stale_when_reference_also_quiet():
    m = StaleMonitor()
    m.on_tick("SPY", T0)
    m.on_tick("ABCD", T0)
    stale, gap = m.sweep(T0 + timedelta(seconds=8))
    assert stale == set()          # can't blame the symbol if the whole pipe is quiet


def test_stream_gap_detected_and_incident_logged():
    m = StaleMonitor(stream_timeout=10.0)
    m.on_tick("SPY", T0)
    _, gap = m.sweep(T0 + timedelta(seconds=11))
    assert gap
    assert any(i.kind == "stream_gap" for i in m.incidents)


def test_backoff_ladder():
    m = StaleMonitor()
    assert m.next_backoff() == 1.0
    assert m.next_backoff() == 2.0
    assert m.next_backoff() == 4.0
    m.on_tick("SPY", T0)               # healthy stream resets
    assert m.next_backoff() == 1.0


def test_clock_skew_aborts():
    server = lambda: T0
    local = lambda: T0 + timedelta(seconds=5)
    with pytest.raises(ClockSkewError):
        check_skew(server, max_skew_seconds=2.0, local_now=local)


def test_clock_skew_ok_within_limit():
    server = lambda: T0
    local = lambda: T0 + timedelta(seconds=1)
    assert check_skew(server, 2.0, local_now=local) == pytest.approx(1.0)


def test_exchange_time_windows():
    # 14:00 UTC on Jul 6 2026 = 10:00 ET (EDT)
    assert ny(T0).hour == 10
    from datetime import time
    assert in_window(T0, (time(9, 30), time(11, 30)))
    assert not in_window(T0, (time(11, 30), time(16, 0)))
    assert minute_of_session(T0) == 30
