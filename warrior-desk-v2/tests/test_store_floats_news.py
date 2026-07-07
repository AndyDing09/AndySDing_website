"""Store round-trips + feed stamping, float cross-validation, catalyst rules."""
from datetime import datetime, timedelta, timezone

from src.data.corp_actions import CorpActionsGuard, SplitEvent
from src.data.floats import CrossValidatedFloat, StaticFloatProvider, float_band
from src.data.news import best_catalyst, classify_headline
from src.data.store import Store
from src.models import Bar, CatalystType, NewsItem, Signal, SetupName, Tick, TradeRecord

T0 = datetime(2026, 7, 6, 13, 30, tzinfo=timezone.utc)


# ── store ──
def test_store_stamps_feed_and_round_trips():
    st = Store(":memory:")
    st.write_tick(Tick(symbol="ABCD", ts=T0, price=5.0, size=100, feed="iex"))
    st.write_bar(Bar(symbol="ABCD", ts=T0, open=5, high=5.2, low=4.9, close=5.1,
                     volume=1000, feed="iex"))
    rows = st.bars("ABCD")
    assert len(rows) == 1
    assert rows[0][-1] == "iex"          # feed source stamped on every stored row


def test_store_signal_and_trade_round_trip():
    st = Store(":memory:")
    sig = Signal(ts=T0, symbol="ABCD", setup=SetupName.BULL_FLAG,
                 entry=5.0, stop=4.8, target=5.5, planned_rr=2.5)
    st.write_signal(sig)
    day = st.signals_between(T0 - timedelta(hours=1), T0 + timedelta(hours=1))
    assert day[0]["symbol"] == "ABCD" and day[0]["planned_rr"] == 2.5

    tr = TradeRecord(signal_ts=T0, closed_at=T0 + timedelta(minutes=9), symbol="ABCD",
                     setup=SetupName.BULL_FLAG, entry_intended=5.0, entry_fill=5.01,
                     exit_fill=5.5, stop=4.8, target=5.5, qty=250, realized_r=2.33,
                     pnl_usd=122.5, mae=-0.05, mfe=0.52, hold_seconds=540,
                     exit_reason="target")
    st.write_trade(tr)
    assert st.last_trades(5)[0]["pnl_usd"] == 122.5


def test_store_parquet_export(tmp_path):
    st = Store(":memory:")
    st.write_tick(Tick(symbol="ABCD", ts=T0, price=5.0, size=100, feed="iex"))
    files = st.export_day_parquet("2026-07-06", tmp_path)
    assert any(f.name == "ticks.parquet" and f.exists() for f in files)


# ── floats ──
def test_floats_agree_verified():
    cv = CrossValidatedFloat([StaticFloatProvider({"ABCD": 9_000_000}, "a"),
                              StaticFloatProvider({"ABCD": 10_000_000}, "b")], 0.25)
    fi = cv.get("ABCD")
    assert fi.verified and fi.shares == 10_000_000     # conservative larger value


def test_floats_disagree_flagged_unverified_and_conservative():
    cv = CrossValidatedFloat([StaticFloatProvider({"ABCD": 5_000_000}, "a"),
                              StaticFloatProvider({"ABCD": 12_000_000}, "b")], 0.25)
    fi = cv.get("ABCD")
    assert not fi.verified
    assert fi.shares == 12_000_000                     # larger value kills the A+ tag
    assert "disagree" in fi.note


def test_float_single_source_is_unverified():
    cv = CrossValidatedFloat([StaticFloatProvider({"ABCD": 8_000_000}, "a"),
                              StaticFloatProvider({}, "b")], 0.25)
    fi = cv.get("ABCD")
    assert not fi.verified and fi.shares == 8_000_000


def test_float_bands():
    assert float_band(9e6, 10e6, 20e6) == "<10M"
    assert float_band(15e6, 10e6, 20e6) == "10-20M"
    assert float_band(30e6, 10e6, 20e6) == ">20M"
    assert float_band(None, 10e6, 20e6) == "unknown"


# ── news / catalysts ──
def test_offering_is_anti_catalyst_even_with_good_news():
    items = [
        NewsItem(symbol="ABCD", ts=T0, headline="ABCD announces positive Phase 3 topline"),
        NewsItem(symbol="ABCD", ts=T0, headline="ABCD prices $50M registered direct offering"),
    ]
    best, dilution = best_catalyst(items, T0 + timedelta(hours=1), 18)
    assert dilution is True
    assert best.catalyst_type == CatalystType.OFFERING_DILUTION


def test_stale_news_is_not_a_catalyst():
    items = [NewsItem(symbol="ABCD", ts=T0 - timedelta(hours=30),
                      headline="FDA approval for ABCD")]
    best, dilution = best_catalyst(items, T0, 18)
    assert best is None and not dilution


def test_classification_priority():
    assert classify_headline("Offering to fund Phase 3 trial") == CatalystType.OFFERING_DILUTION
    assert classify_headline("FDA grants breakthrough therapy") == CatalystType.FDA_CLINICAL
    assert classify_headline("Q2 earnings beat, raises outlook") == CatalystType.EARNINGS
    assert classify_headline("Awarded $12M defense contract") == CatalystType.CONTRACT_PARTNERSHIP
    assert classify_headline("Company to be acquired for $9/share") == CatalystType.MA
    assert classify_headline("CEO to speak at conference") == CatalystType.OTHER


# ── corporate actions ──
def test_reverse_split_adjusts_prior_close():
    g = CorpActionsGuard([SplitEvent("ABCD", T0.date(), ratio=0.1)])   # 1-for-10
    assert g.adjusted_prior_close("ABCD", 0.50, T0.date()) == 5.0
    assert not g.excluded("ABCD", T0.date())


def test_unknown_ratio_excludes_symbol_for_the_day():
    g = CorpActionsGuard([SplitEvent("ABCD", T0.date(), ratio=0.0)])
    assert g.adjusted_prior_close("ABCD", 0.50, T0.date()) is None
    assert g.excluded("ABCD", T0.date())


def test_untouched_symbol_passes_through():
    g = CorpActionsGuard([])
    assert g.adjusted_prior_close("WXYZ", 3.30, T0.date()) == 3.30
