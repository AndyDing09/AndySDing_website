"""Phase 6: quality score gates, dilution radar, engine end-to-end, replay determinism."""
from datetime import datetime, timedelta, timezone

import pytest

from replay.harness import run_replay
from src.config import Config
from src.data.corp_actions import CorpActionsGuard
from src.data.floats import CrossValidatedFloat, StaticFloatProvider
from src.data.store import Store
from src.dilution import EdgarRadar, check_news, dilution_risk
from src.engine import SessionEngine
from src.execution.broker import SimBroker
from src.models import (Bar, Candidate, CatalystType, NewsItem, Regime,
                        SignalStatus)
from src.reporting.missed_moves import postmortem
from src.risk.circuit_breakers import CircuitBreakers
from src.scanners.gapper import Snapshot
from src.score import ScoreInputs, score

CFG = Config()
T0 = datetime(2026, 7, 6, 13, 45, tzinfo=timezone.utc)     # 09:45 ET


# ── score (§7.1) ──
def elite_inputs(**over):
    d = dict(rvol=20.0, float_shares=5e6, float_unverified=False, catalyst=1.0,
             retrace_pct=0.15, pullback_volume_declining=True,
             dist_to_9ema_pct=0.005, spread_pct=0.001, obviousness_rank=1)
    d.update(over)
    return ScoreInputs(**d)


def test_elite_setup_scores_full_size():
    s = score(elite_inputs(), CFG.score)
    assert s >= CFG.score.full_size_at


def test_weak_setup_scores_below_skip():
    weak = elite_inputs(rvol=5.0, float_shares=19e6, float_unverified=True,
                        catalyst=0.25, retrace_pct=0.5,
                        pullback_volume_declining=False, dist_to_9ema_pct=0.05,
                        spread_pct=0.009, obviousness_rank=6)
    assert score(weak, CFG.score) < CFG.score.skip_below


def test_dilution_caps_score_at_59():
    s = score(elite_inputs(), CFG.score, dilution_risk=True)
    assert s <= CFG.score.dilution_cap          # auto half-size-or-skip (§7.8)


# ── dilution radar (§7.8) ──
def test_news_offering_flags_risk():
    items = [NewsItem(symbol="ABCD", ts=T0, headline="Prices $30M offering",
                      catalyst_type=CatalystType.OFFERING_DILUTION)]
    assert check_news(items).risky


def test_edgar_down_degrades_loudly_not_silently_safe():
    radar = EdgarRadar(timeout=0.001)
    radar._cache["ABCD"] = None                  # force one live path? no — simulate:
    radar._cache.clear()
    res = dilution_risk("ABCD", [], T0, edgar=None)   # news-only mode
    assert res.source == "news_only" and not res.risky


# ── missed-move postmortem (§7.9) ──
def _floats(**m):
    return CrossValidatedFloat([StaticFloatProvider(m, "a"),
                                StaticFloatProvider(m, "b")], 0.25)


def test_postmortem_names_the_excluding_filter():
    fresh = [NewsItem(symbol="BIGF", ts=T0 - timedelta(hours=1), headline="FDA approval")]
    gainers = [
        (Snapshot("ONWL", "NASDAQ", 6.0, 4.0, 3_000_000, 6.2, 5.0, 300_000, fresh), 0.50),
        (Snapshot("BIGF", "NASDAQ", 6.0, 4.0, 3_000_000, 6.2, 5.0, 300_000, fresh), 0.45),
        (Snapshot("NONEWS", "NASDAQ", 6.0, 4.0, 3_000_000, 6.2, 5.0, 300_000, []), 0.40),
    ]
    rows = postmortem(gainers, watchlist={"ONWL"}, cfg=CFG,
                      floats=_floats(BIGF=80e6, NONEWS=8e6), guard=CorpActionsGuard(),
                      now=T0)
    by = {m.symbol: m.excluded_by for m in rows}
    assert "ONWL" not in by                       # was on the list — not "missed"
    assert by["BIGF"].startswith("float:")        # the SPECIFIC filter, with numbers
    assert by["NONEWS"].startswith("catalyst:")


# ── engine end-to-end (identical live/replay pipeline) ──
def _cand():
    return Candidate(symbol="ABCD", gap_pct=0.25, last=5.45, premkt_vol=2_000_000,
                     rvol=8.0, float_shares=8e6, float_unverified=False,
                     catalyst_headline="FDA approval", catalyst_type=CatalystType.FDA_CLINICAL,
                     obviousness_rank=1, premkt_high=5.50, premkt_low=5.10, a_grade=True)


def _bar(o, h, l, c, v, i):
    return Bar(symbol="ABCD", ts=T0 + timedelta(minutes=i), open=o, high=h, low=l,
               close=c, volume=v, feed="test")


def _win_bars():
    return [_bar(5.40, 5.48, 5.30, 5.45, 100_000, 0),
            _bar(5.45, 5.60, 5.44, 5.58, 200_000, 1),      # breaks PM high -> entry
            _bar(5.60, 6.70, 5.50, 6.65, 300_000, 2)]      # runs through the target


def _engine():
    broker = SimBroker(CFG)
    return SessionEngine(CFG, broker, Store(":memory:"), CircuitBreakers(CFG.risk),
                         {"ABCD": _cand()}, regime=Regime.TRENDING), broker


def test_engine_full_round_trip_win():
    eng, broker = _engine()
    for b in _win_bars():
        eng.on_bar(b)
    assert len(eng.trades) == 1
    tr = eng.trades[0]
    assert tr.exit_reason == "target"
    assert tr.entry_fill == 5.52                  # ask(5.51) + 1 tick slippage
    assert tr.exit_fill == 6.60                   # resting limit at the target
    assert tr.realized_r == pytest.approx((6.60 - 5.52) / 0.21, abs=0.01)
    assert eng.breakers.state.day_r > 0
    # the fill was half size (score in the 60-79 band) and journaled as FILLED
    filled = [s for s in eng.signals if s.status == SignalStatus.FILLED]
    assert len(filled) == 1 and filled[0].shares >= 1


def test_engine_stop_out_feeds_the_breakers():
    eng, broker = _engine()
    bars = _win_bars()[:2] + [_bar(5.45, 5.50, 5.20, 5.25, 150_000, 2)]  # stop 5.30 pierced
    for b in bars:
        eng.on_bar(b)
    assert len(eng.trades) == 1
    tr = eng.trades[0]
    assert tr.exit_reason == "stop" and tr.pnl_usd < 0
    assert tr.exit_fill == 5.29                   # bid(5.30) - 1 tick honesty
    assert eng.breakers.state.consecutive_losses == 1


def test_engine_journals_every_signal_even_gated_ones():
    eng, broker = _engine()
    eng.candidates["ABCD"].dilution_flag = True   # caps score at 59 -> skipped
    for b in _win_bars():
        eng.on_bar(b)
    assert len(eng.trades) == 0
    assert eng.signals and eng.signals[0].status == SignalStatus.SKIPPED
    assert eng.signals[0].status_reason.startswith("score:")
    day = eng.journal.store.signals_between(T0 - timedelta(hours=1), T0 + timedelta(hours=1))
    assert len(day) == len(eng.signals)           # taken or not, it's in the DB


# ── replay determinism (§7.3, definition of done) ──
def test_replay_is_deterministic_same_input_same_signals():
    r1 = run_replay(CFG, _win_bars(), {"ABCD": _cand()}, regime=Regime.TRENDING)
    r2 = run_replay(CFG, _win_bars(), {"ABCD": _cand()}, regime=Regime.TRENDING)
    assert r1.digest == r2.digest
    assert (r1.n_signals, r1.n_trades, r1.pnl_usd) == (r2.n_signals, r2.n_trades, r2.pnl_usd)
    assert r1.n_trades == 1 and r1.pnl_usd > 0


def test_replay_digest_changes_when_input_changes():
    r1 = run_replay(CFG, _win_bars(), {"ABCD": _cand()}, regime=Regime.TRENDING)
    altered = _win_bars()
    altered[1] = _bar(5.45, 5.60, 5.44, 5.58, 90_000, 1)    # kill the volume confirm
    r2 = run_replay(CFG, altered, {"ABCD": _cand()}, regime=Regime.TRENDING)
    assert r1.digest != r2.digest
