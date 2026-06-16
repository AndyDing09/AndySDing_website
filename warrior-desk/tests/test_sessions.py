"""Session-window classification in America/New_York."""
from datetime import datetime
from zoneinfo import ZoneInfo

from warrior.config import Config
from warrior.models import SessionWindow
from warrior.sessions import (
    classify_window, in_allowed_session, chart_timeframe, past_hard_flat_time,
)

ET = ZoneInfo("America/New_York")


def at(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=ET)


def test_prime_window():
    w = classify_window(at(2026, 6, 16, 9, 45), Config())  # Tue
    assert w == SessionWindow.PRIME
    assert in_allowed_session(w, Config())
    assert chart_timeframe(w, Config()) == "1Min"


def test_midday_window():
    w = classify_window(at(2026, 6, 16, 13, 0), Config())
    assert w == SessionWindow.MIDDAY
    assert in_allowed_session(w, Config())
    assert chart_timeframe(w, Config()) == "5Min"


def test_premarket_not_traded_by_default():
    w = classify_window(at(2026, 6, 16, 8, 0), Config())
    assert w == SessionWindow.PREMARKET
    assert in_allowed_session(w, Config()) is False


def test_afterhours_not_traded_by_default():
    w = classify_window(at(2026, 6, 16, 17, 0), Config())
    assert w == SessionWindow.AFTERHOURS
    assert in_allowed_session(w, Config()) is False


def test_weekend_is_closed():
    w = classify_window(at(2026, 6, 20, 10, 0), Config())  # Saturday
    assert w == SessionWindow.CLOSED
    assert in_allowed_session(w, Config()) is False


def test_hard_flat_time():
    cfg = Config()
    assert past_hard_flat_time(at(2026, 6, 16, 15, 56), cfg) is True
    assert past_hard_flat_time(at(2026, 6, 16, 15, 50), cfg) is False
