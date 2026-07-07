"""Phase 3a: each setup detects its textbook shape and rejects the near-miss."""
from datetime import datetime, timedelta, timezone

from src.config import Config
from src.models import Bar, Candidate, Quote, SetupName
from src.strategies.base import MarketView
from src.strategies.bull_flag import BullFlag
from src.strategies.gap_and_go import GapAndGo
from src.strategies.hod_continuation import HodContinuation
from src.strategies.vwap_breakout import VwapBreakout

CFG = Config()
T_0945 = datetime(2026, 7, 6, 13, 45, tzinfo=timezone.utc)   # 09:45 ET
T_1030 = datetime(2026, 7, 6, 14, 30, tzinfo=timezone.utc)   # 10:30 ET
T_1100 = datetime(2026, 7, 6, 15, 0, tzinfo=timezone.utc)    # 11:00 ET
T_1300 = datetime(2026, 7, 6, 17, 0, tzinfo=timezone.utc)    # 13:00 ET


def bar(o, h, l, c, v=100_000, i=0):
    return Bar(symbol="ABCD", ts=T_0945 + timedelta(minutes=i), open=o, high=h,
               low=l, close=c, volume=v, feed="test")


def cand(**kw):
    d = dict(symbol="ABCD", gap_pct=0.25, last=5.45, rvol=8.0, obviousness_rank=1)
    d.update(kw)
    return Candidate(**d)


def view(bars, now, hod=0.0, pm_high=None, pm_low=None, c=None):
    return MarketView(now=now, candidate=c or cand(), bars_1m=bars,
                      quote=Quote(symbol="ABCD", ts=now, bid=5.44, ask=5.46, feed="test"),
                      hod=hod or max((b.high for b in bars), default=0.0),
                      premkt_high=pm_high, premkt_low=pm_low, feed="test")


# ── Gap & Go ──
def _gg_bars(break_vol=200_000):
    return [bar(5.40, 5.48, 5.30, 5.45, v=100_000, i=0),
            bar(5.45, 5.60, 5.44, 5.58, v=break_vol, i=1)]   # takes out PM high 5.50


def test_gap_and_go_fires_on_pm_high_break_with_volume():
    sig = GapAndGo(CFG).detect(view(_gg_bars(), T_0945, pm_high=5.50, pm_low=5.10))
    assert sig is not None and sig.setup == SetupName.GAP_AND_GO
    assert sig.entry == 5.51                     # break of the pre-market high
    assert sig.stop == 5.30                      # tighter of pullback low vs PM low
    assert sig.planned_rr >= 2.0


def test_gap_and_go_needs_above_average_volume():
    assert GapAndGo(CFG).detect(view(_gg_bars(break_vol=90_000), T_0945,
                                     pm_high=5.50, pm_low=5.10)) is None


def test_gap_and_go_respects_window():
    assert GapAndGo(CFG).detect(view(_gg_bars(), T_1100, pm_high=5.50, pm_low=5.10)) is None


# ── Bull flag ──
def _flag_bars():
    return [bar(5.00, 5.30, 4.98, 5.28, i=0),            # pole: 3 wide greens
            bar(5.28, 5.60, 5.26, 5.58, i=1),
            bar(5.58, 5.90, 5.55, 5.88, i=2),
            bar(5.88, 5.89, 5.70, 5.72, v=40_000, i=3),  # pullback reds
            bar(5.72, 5.74, 5.62, 5.64, v=30_000, i=4),
            bar(5.64, 5.80, 5.63, 5.78, i=5)]            # green breaks prev red high


def test_bull_flag_fires_and_prices_off_the_prior_red():
    sig = BullFlag(CFG).detect(view(_flag_bars(), T_1030, hod=6.10))
    assert sig is not None
    assert sig.entry == 5.75                     # prev red high 5.74 + 0.01
    assert sig.stop == 5.62                      # pullback low
    assert sig.target == 6.10                    # new high of day
    assert sig.planned_rr >= 2.0


def test_bull_flag_rejects_deep_retrace():
    bars = _flag_bars()
    bars[4] = bar(5.72, 5.74, 5.30, 5.35, i=4)   # gives back ~65% of the pole
    assert BullFlag(CFG).detect(view(bars, T_1030, hod=6.10)) is None


def test_bull_flag_requires_green_entry_candle():
    bars = _flag_bars()
    bars[-1] = bar(5.64, 5.80, 5.55, 5.60, i=5)  # red candle poking the high
    assert BullFlag(CFG).detect(view(bars, T_1030, hod=6.10)) is None


def test_bull_flag_window_closes_at_1130():
    assert BullFlag(CFG).detect(view(_flag_bars(), T_1300, hod=6.10)) is None


# ── VWAP breakout ──
def _vwap_bars():
    consol = []
    for i in range(10):
        v = 1000 if i < 5 else 600                        # declining volume
        consol.append(bar(9.99, 10.02, 9.98, 9.99, v=v, i=i))
    breakout = bar(9.99, 10.06, 9.98, 10.05, v=2000, i=10)  # close > vwap, 2x vol
    return consol + [breakout]


def test_vwap_breakout_fires():
    sig = VwapBreakout(CFG).detect(view(_vwap_bars(), T_1100, hod=10.0))
    assert sig is not None
    assert sig.entry == 10.05
    assert sig.stop == 9.98                       # consolidation low (no ATR yet)
    assert sig.planned_rr >= 2.0 - 1e-9           # target sits exactly at 2R


def test_vwap_breakout_needs_volume_expansion():
    bars = _vwap_bars()
    bars[-1] = bar(9.99, 10.06, 9.98, 10.05, v=900, i=10)   # no 2x expansion
    assert VwapBreakout(CFG).detect(view(bars, T_1100, hod=10.0)) is None


def test_vwap_breakout_needs_declining_consolidation_volume():
    bars = [bar(9.99, 10.02, 9.98, 9.99, v=600 if i < 5 else 1000, i=i) for i in range(10)]
    bars.append(bar(9.99, 10.06, 9.98, 10.05, v=2000, i=10))
    assert VwapBreakout(CFG).detect(view(bars, T_1100, hod=10.0)) is None


# ── HOD continuation ──
def _hodc_bars():
    return [bar(5.00, 5.20, 4.98, 5.18, i=0),
            bar(5.18, 5.60, 5.16, 5.55, i=1),             # spike prints the HOD
            bar(5.55, 5.56, 5.40, 5.44, v=50_000, i=2),   # micro-pullback
            bar(5.44, 5.60, 5.43, 5.58, i=3)]             # reclaim


def test_hod_continuation_enters_micro_pullback_not_the_spike():
    sig = HodContinuation(CFG).detect(view(_hodc_bars(), T_1030, hod=5.60))
    assert sig is not None
    assert sig.entry == 5.57                     # prev red high + 0.01, never the spike
    assert sig.stop == 5.40
    assert sig.planned_rr >= 2.0


def test_hod_continuation_never_chases_the_spike_candle():
    bars = _hodc_bars()[:2]                       # spike just printed, no pullback yet
    assert HodContinuation(CFG).detect(view(bars, T_1030, hod=5.60)) is None
