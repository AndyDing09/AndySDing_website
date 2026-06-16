"""Yahoo scanner parsing + prefilter (no network — canned JSON)."""
from warrior.config import Config
from warrior.data.yahoo import (
    YahooScanner, _num, parse_float_quote_summary, parse_screener,
)

SCREENER = {"finance": {"result": [{"quotes": [
    {"symbol": "abcd", "regularMarketPrice": {"raw": 3.5}, "exchange": "NMS",
     "regularMarketChangePercent": {"raw": 42.0}, "regularMarketVolume": {"raw": 5_000_000},
     "averageDailyVolume3Month": {"raw": 1_000_000}, "sharesOutstanding": {"raw": 8_000_000}},
    {"symbol": "BIG", "regularMarketPrice": 500, "exchange": "NYQ",
     "regularMarketChangePercent": 1.0, "regularMarketVolume": 1_000_000,
     "averageDailyVolume3Month": 1_000_000},
    {"symbol": "PENNY", "regularMarketPrice": {"raw": 0.80}, "exchange": "NMS",
     "regularMarketChangePercent": {"raw": 60.0}, "regularMarketVolume": {"raw": 9_000_000},
     "averageDailyVolume3Month": {"raw": 9_000_000}},
    {"symbol": "OTCJUNK", "regularMarketPrice": {"raw": 6.0}, "exchange": "PNK",
     "regularMarketChangePercent": {"raw": 80.0}, "regularMarketVolume": {"raw": 9_000_000},
     "averageDailyVolume3Month": {"raw": 9_000_000}},
    {"symbol": "THIN", "regularMarketPrice": {"raw": 7.0}, "exchange": "NMS",
     "regularMarketChangePercent": {"raw": 30.0}, "regularMarketVolume": {"raw": 50_000},
     "averageDailyVolume3Month": {"raw": 60_000}},
]}]}}


def test_num_handles_both_shapes():
    assert _num({"raw": 3.5}) == 3.5
    assert _num(7) == 7.0
    assert _num(None) is None
    assert _num({"raw": None}) is None


def test_parse_screener():
    cands = parse_screener(SCREENER)
    assert len(cands) == 5
    abcd = cands[0]
    assert abcd.symbol == "ABCD" and abcd.price == 3.5
    assert abs(abcd.gap_pct - 0.42) < 1e-9
    assert abcd.rvol == 5.0                       # 5M / 1M
    assert abcd.exchange == "NMS" and abcd.day_volume == 5_000_000
    assert abcd.float_shares == 8_000_000 and abcd.float_verified is False


def test_parse_float_quote_summary():
    fl = parse_float_quote_summary(
        {"quoteSummary": {"result": [{"defaultKeyStatistics": {"floatShares": {"raw": 8_000_000}}}]}})
    assert fl.shares == 8_000_000 and fl.verified is True

    so = parse_float_quote_summary(
        {"quoteSummary": {"result": [{"defaultKeyStatistics": {"sharesOutstanding": {"raw": 5e7}}}]}})
    assert so.shares == 5e7 and so.verified is False    # proxy, flagged approximate

    assert parse_float_quote_summary({}).known is False


def test_scanner_prefilter_drops_penny_and_illiquid():
    sc = YahooScanner(Config())
    cands = {c.symbol: c for c in parse_screener(SCREENER)}
    assert sc._prefilter(cands["ABCD"]) is True        # $3.50 NMS, +42%, liquid
    assert sc._prefilter(cands["BIG"]) is False         # $500 — out of small-cap range
    assert sc._prefilter(cands["PENNY"]) is False       # $0.80 — sub-$2 penny
    assert sc._prefilter(cands["OTCJUNK"]) is False     # PNK / OTC venue
    assert sc._prefilter(cands["THIN"]) is False        # only 50k shares — illiquid


def test_scanner_get_candidates_filters(monkeypatch):
    sc = YahooScanner(Config())
    monkeypatch.setattr(sc.http, "get_json", lambda *a, **k: SCREENER)
    out = sc.get_candidates(limit=10)
    syms = {c.symbol for c in out}
    assert syms == {"ABCD"}                              # only the clean, liquid name survives
