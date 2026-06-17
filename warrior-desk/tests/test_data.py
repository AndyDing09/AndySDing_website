"""Alpaca parsing (canned JSON), the float source, and the synthetic provider."""
from datetime import datetime

from warrior.data import StaticFloatSource, SyntheticProvider, UnknownFloatSource
from warrior.data.alpaca_provider import (
    parse_account, parse_bars, parse_movers, parse_news, parse_quote, parse_ts,
)
from warrior.models import Bar, Catalyst


def test_parse_ts_handles_z_and_nanoseconds():
    assert parse_ts("2026-06-16T09:30:00Z").hour == 9
    # nanoseconds shouldn't crash
    assert parse_ts("2026-06-16T09:30:00.123456789Z") is not None
    assert parse_ts(None) is None
    assert parse_ts("garbage") is None


def test_parse_bars():
    payload = {"bars": [
        {"t": "2026-06-16T09:30:00Z", "o": 5.0, "h": 5.5, "l": 4.9, "c": 5.4, "v": 1000},
        {"t": "2026-06-16T09:31:00Z", "o": 5.4, "h": 5.6, "l": 5.3, "c": 5.5, "v": 800},
    ]}
    bars = parse_bars(payload)
    assert len(bars) == 2
    assert bars[0].close == 5.4 and bars[1].volume == 800
    assert bars[0].is_green


def test_parse_quote_spread():
    q = parse_quote({"quote": {"bp": 4.98, "ap": 5.02, "bs": 100, "as": 200}})
    assert q is not None
    assert q.spread == 0.04
    assert q.mid == 5.0


def test_parse_news_classifies():
    payload = {"news": [
        {"headline": "Tiny Pharma announces positive Phase 3 trial results",
         "source": "pr", "created_at": "2026-06-16T08:00:00Z"},
        {"headline": "", "source": "x"},  # empty headline dropped
    ]}
    items = parse_news(payload)
    assert len(items) == 1
    assert items[0].classification == "fda"
    assert items[0].material is True


def test_parse_movers():
    payload = {"gainers": [
        {"symbol": "abcd", "percent_change": 45.2, "price": 6.1},
        {"symbol": "wxyz", "percent_change": 30.0, "price": 3.3},
    ]}
    cands = parse_movers(payload)
    assert cands[0].symbol == "ABCD"
    assert abs(cands[0].gap_pct - 0.452) < 1e-9


def test_parse_account():
    acct = parse_account({"equity": "25000", "cash": "10000", "buying_power": "40000",
                          "status": "ACTIVE", "pattern_day_trader": False}, "paper")
    assert acct.equity == 25000.0
    assert acct.buying_power == 40000.0
    assert acct.mode == "paper"


def test_unknown_float_is_flagged():
    fi = UnknownFloatSource().get_float("ABCD")
    assert fi.known is False
    assert fi.verified is False


def test_static_float_source():
    fs = StaticFloatSource({"ABCD": 8_000_000})
    fi = fs.get_float("abcd")
    assert fi.known and fi.verified and fi.shares == 8_000_000
    assert fs.get_float("NOPE").known is False


def test_caching_float_source_memoizes():
    from warrior.data.float_source import CachingFloatSource, FloatSource
    from warrior.data.provider import FloatInfo
    calls = {"n": 0}

    class Counting(FloatSource):
        def get_float(self, s):
            calls["n"] += 1
            return FloatInfo(8_000_000, True, "x")

    c = CachingFloatSource(Counting())
    c.get_float("ABCD"); c.get_float("abcd"); c.get_float("ABCD")
    assert calls["n"] == 1          # one underlying fetch despite 3 (case-insensitive) calls


def test_synthetic_provider_cursor_replay():
    bars = [Bar(ts=datetime(2026, 6, 16, 9, 30 + i), open=5, high=5.5, low=4.9,
                close=5.0 + i * 0.1, volume=100) for i in range(5)]
    sp = SyntheticProvider(bars={"ABCD": bars}, baselines={"ABCD": 50.0})
    assert len(sp.get_bars("ABCD", "1Min")) == 5
    sp.set_cursor("ABCD", 2)
    visible = sp.get_bars("ABCD", "1Min")
    assert len(visible) == 3
    assert visible[-1].close == 5.2
    # derived quote when none set
    q = sp.get_quote("ABCD")
    assert q is not None and q.bid < q.ask
    assert sp.baseline_volume("ABCD", "1Min") == 50.0
