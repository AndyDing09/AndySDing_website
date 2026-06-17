"""Pattern detector: forgiving on real-world shapes, still rejects junk."""
from datetime import datetime, timedelta

from warrior.config import Config
from warrior.models import Bar, PatternKind
from warrior.patterns import detect_pattern

CFG = Config()


def _bars(specs):
    return [Bar(ts=datetime(2026, 6, 17, 9, 30) + timedelta(minutes=i),
                open=o, high=h, low=l, close=c, volume=10_000)
            for i, (o, h, l, c) in enumerate(specs)]


def test_messy_pullback_still_detected():
    # pole 3.98 -> 5.00, then a pullback that includes a small GREEN candle.
    # The old "consecutive red candles" rule rejected this; the new one accepts it.
    specs = [(4.0, 4.1, 3.98, 4.08), (4.08, 4.3, 4.05, 4.27), (4.27, 4.6, 4.25, 4.55),
             (4.55, 5.0, 4.5, 4.95),
             (4.95, 4.98, 4.82, 4.85), (4.85, 4.9, 4.84, 4.88), (4.88, 4.9, 4.80, 4.83)]
    r = detect_pattern(_bars(specs), CFG)
    assert r.valid is True
    assert r.kind in (PatternKind.BULL_FLAG, PatternKind.FLAT_TOP)
    assert r.retrace_pct <= 0.5


def test_deep_pullback_rejected():
    specs = [(4.0, 4.1, 3.98, 4.08), (4.08, 4.3, 4.05, 4.27), (4.27, 4.6, 4.25, 4.55),
             (4.55, 5.0, 4.5, 4.95), (4.95, 4.98, 4.40, 4.45)]   # ~55% give-back
    assert detect_pattern(_bars(specs), CFG).valid is False


def test_flat_noise_rejected():
    assert detect_pattern(_bars([(3.0, 3.02, 2.98, 3.0)] * 12), CFG).valid is False


def test_breakout_is_triggered():
    specs = [(4.0, 4.5, 3.98, 4.45), (4.45, 5.0, 4.4, 4.95), (4.95, 4.98, 4.82, 4.85),
             (4.85, 4.9, 4.8, 4.83), (4.83, 5.15, 4.82, 5.10)]   # green bar breaks the 5.00 high
    r = detect_pattern(_bars(specs), CFG)
    assert r.valid is True and r.triggered is True
