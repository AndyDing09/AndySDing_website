"""Yahoo scanner parsing + prefilter (no network — canned JSON)."""
from warrior.config import Config
from warrior.data.yahoo import (
    YahooScanner, _num, parse_float_quote_summary, parse_screener,
)

SCREENER = {"finance": {"result": [{"quotes": [
    {"symbol": "abcd", "regularMarketPrice": {"raw": 3.5},
     "regularMarketChangePercent": {"raw": 42.0}, "regularMarketVolume": {"raw": 5_000_000},
     "averageDailyVolume3Month": {"raw": 1_000_000}, "sharesOutstanding": {"raw": 8_000_000}},
    {"symbol": "BIG", "regularMarketPrice": 500, "regularMarketChangePercent": 1.0,
     "regularMarketVolume": 100, "averageDailyVolume3Month": 1000},
]}]}}


def test_num_handles_both_shapes():
    assert _num({"raw": 3.5}) == 3.5
    assert _num(7) == 7.0
    assert _num(None) is None
    assert _num({"raw": None}) is None


def test_parse_screener():
    cands = parse_screener(SCREENER)
    assert len(cands) == 2
    abcd = cands[0]
    assert abcd.symbol == "ABCD" and abcd.price == 3.5
    assert abs(abcd.gap_pct - 0.42) < 1e-9
    assert abcd.rvol == 5.0                       # 5M / 1M
    assert abcd.float_shares == 8_000_000 and abcd.float_verified is False


def test_parse_float_quote_summary():
    fl = parse_float_quote_summary(
        {"quoteSummary": {"result": [{"defaultKeyStatistics": {"floatShares": {"raw": 8_000_000}}}]}})
    assert fl.shares == 8_000_000 and fl.verified is True

    so = parse_float_quote_summary(
        {"quoteSummary": {"result": [{"defaultKeyStatistics": {"sharesOutstanding": {"raw": 5e7}}}]}})
    assert so.shares == 5e7 and so.verified is False    # proxy, flagged approximate

    assert parse_float_quote_summary({}).known is False


def test_scanner_prefilter():
    sc = YahooScanner(Config())          # default price range 1..20, min $vol 1M
    cands = {c.symbol: c for c in parse_screener(SCREENER)}
    assert sc._prefilter(cands["ABCD"]) is True       # $3.50, +42%, $3.5M vol
    assert sc._prefilter(cands["BIG"]) is False        # $500 is out of the small-cap range
