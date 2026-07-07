"""Scrubber vs synthetic bad ticks (§9 phase-1 acceptance)."""
from datetime import datetime, timedelta, timezone

from src.data.scrub import TickScrubber
from src.models import Tick

T0 = datetime(2026, 7, 6, 14, 0, tzinfo=timezone.utc)


def tick(price, size=100, cond=None, offset=0.0, symbol="ABCD"):
    return Tick(symbol=symbol, ts=T0 + timedelta(seconds=offset), price=price,
                size=size, conditions=cond or [], feed="test")


def test_irregular_condition_dropped():
    s = TickScrubber()
    ok, reason = s.accept(tick(5.0, cond=["T"]))
    assert not ok and reason == "irregular_condition"


def test_zero_size_dropped():
    s = TickScrubber()
    ok, reason = s.accept(tick(5.0, size=0))
    assert not ok and reason == "zero_size"


def test_price_outlier_dropped_after_warmup():
    s = TickScrubber(sigma=10.0)
    # warm the 1-min window with a tight tape around $5
    for i in range(30):
        ok, _ = s.accept(tick(5.0 + (0.01 if i % 2 else -0.01), offset=i))
        assert ok
    # a fat-finger print far outside 10 sigma must be dropped...
    ok, reason = s.accept(tick(50.0, offset=31))
    assert not ok and reason == "price_outlier"
    # ...and must not poison the window: normal prints continue to pass
    ok, _ = s.accept(tick(5.01, offset=32))
    assert ok


def test_no_sigma_filter_before_enough_samples():
    s = TickScrubber(sigma=10.0)
    # first print at any price is accepted (no window yet)
    ok, _ = s.accept(tick(500.0))
    assert ok


def test_windows_are_per_symbol():
    s = TickScrubber()
    for i in range(30):
        s.accept(tick(5.0, offset=i, symbol="AAAA"))
    # a different symbol at a wildly different price is fine
    ok, _ = s.accept(tick(400.0, symbol="BBBB", offset=31))
    assert ok


def test_old_prints_age_out_of_window():
    s = TickScrubber(sigma=3.0)
    for i in range(20):
        s.accept(tick(5.0, offset=i))
    # 10 minutes later the window is empty; a re-priced tape is accepted
    ok, _ = s.accept(tick(9.0, offset=600))
    assert ok
