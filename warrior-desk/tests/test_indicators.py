"""Indicators checked against hand-computed values (Section 2.8)."""
from datetime import datetime

import pytest

from warrior.indicators import (
    atr, ema, macd, pct_from, rsi, rvol, sma, true_range, vwap,
)
from warrior.models import Bar


def _bar(h, l, c, v=100, o=None):
    return Bar(ts=datetime(2026, 6, 16, 9, 30), open=o if o is not None else c,
               high=h, low=l, close=c, volume=v)


def test_sma_basic():
    assert sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


def test_ema_seeded_with_sma():
    # seed = mean(1,2,3)=2 ; k=0.5 ; then 4*.5+2*.5=3 ; 5*.5+3*.5=4
    assert ema([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


def test_ema_too_short_is_all_none():
    assert ema([1, 2], 3) == [None, None]


def test_rsi_monotonic_up_is_100():
    assert rsi([1, 2, 3, 4, 5, 6], 3)[-1] == 100.0


def test_rsi_monotonic_down_is_0():
    assert rsi([6, 5, 4, 3, 2, 1], 3)[-1] == 0.0


def test_rsi_known_values_period_3():
    out = rsi([10, 11, 12, 11, 12], 3)
    # idx3: gains 2/3, losses 1/3 -> RS 2 -> RSI 66.6667
    assert out[3] == pytest.approx(66.6667, abs=1e-3)
    # idx4 via Wilder smoothing -> 77.7778
    assert out[4] == pytest.approx(77.7778, abs=1e-3)


def test_true_range_and_atr():
    bars = [_bar(10, 9, 9.5), _bar(11, 10, 10.5), _bar(12, 11, 11.5), _bar(13, 12, 12.5)]
    tr = true_range(bars)
    assert tr == [1.0, 1.5, 1.5, 1.5]
    a = atr(bars, 3)
    assert a[2] == pytest.approx(4 / 3, abs=1e-6)        # seed
    assert a[3] == pytest.approx((4 / 3 * 2 + 1.5) / 3, abs=1e-6)


def test_vwap():
    bars = [_bar(10, 10, 10, 100), _bar(20, 20, 20, 100)]
    assert vwap(bars) == [10.0, 15.0]


def test_macd_constant_series_is_zero():
    vals = [5.0] * 40
    line, signal, hist = macd(vals)
    assert hist[-1] == pytest.approx(0.0, abs=1e-9)
    assert line[-1] == pytest.approx(0.0, abs=1e-9)
    assert len(line) == len(vals) == len(signal) == len(hist)


def test_rvol():
    assert rvol(200, 100) == 2.0
    assert rvol(50, 0) == 0.0


def test_pct_from():
    assert pct_from(11, 10) == pytest.approx(0.1)
    assert pct_from(5, 0) is None
