"""Trading-session windows (Section 1), in America/New_York.

    prime    09:30–11:30   most active; 1-minute chart allowed
    midday   11:30–16:00   5-minute chart only; size down; A+ only
    pre/post                watch & build the watchlist only (no trading by default)
    closed                  outside any window / weekends

Holidays are not modelled here (an honest approximation; the broker would reject
orders on a closed day regardless).
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from .config import Config
from .models import SessionWindow

MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
PREMARKET_OPEN = time(4, 0)
AFTERHOURS_CLOSE = time(20, 0)


def _tz(cfg: Config) -> ZoneInfo:
    try:
        return ZoneInfo(cfg.sessions.timezone)
    except Exception:
        return ZoneInfo("America/New_York")


def now_et(cfg: Config) -> datetime:
    return datetime.now(_tz(cfg))


def _hhmm(s: str, fallback: time) -> time:
    try:
        h, m = s.split(":")
        return time(int(h), int(m))
    except Exception:
        return fallback


def classify_window(now: datetime, cfg: Config) -> SessionWindow:
    """Classify a timezone-aware (ET) datetime into a session window."""
    if now.weekday() >= 5:  # Sat/Sun
        return SessionWindow.CLOSED

    t = now.timetz().replace(tzinfo=None)
    prime_start = _hhmm(cfg.sessions.prime_start, MARKET_OPEN)
    prime_end = _hhmm(cfg.sessions.prime_end, time(11, 30))
    close = _hhmm(cfg.sessions.market_close, MARKET_CLOSE)

    if PREMARKET_OPEN <= t < prime_start:
        return SessionWindow.PREMARKET
    if prime_start <= t < prime_end:
        return SessionWindow.PRIME
    if prime_end <= t < close:
        return SessionWindow.MIDDAY
    if close <= t < AFTERHOURS_CLOSE:
        return SessionWindow.AFTERHOURS
    return SessionWindow.CLOSED


def in_allowed_session(window: SessionWindow, cfg: Config) -> bool:
    """Whether trading (not just watching) is allowed in this window."""
    if window in (SessionWindow.PRIME, SessionWindow.MIDDAY):
        return True
    if window == SessionWindow.PREMARKET:
        return cfg.sessions.trade_premarket
    if window == SessionWindow.AFTERHOURS:
        return cfg.sessions.trade_afterhours
    return False


def chart_timeframe(window: SessionWindow, cfg: Config) -> str:
    """Midday is too choppy for the 1-min — use the 5-min off-prime."""
    if window == SessionWindow.PRIME:
        return cfg.timeframe_prime
    return cfg.timeframe_midday


def past_hard_flat_time(now: datetime, cfg: Config) -> bool:
    """True once we've reached the end-of-day flatten time (no overnight holds)."""
    flat = _hhmm(cfg.sessions.hard_flat_time, time(15, 55))
    t = now.timetz().replace(tzinfo=None)
    return t >= flat and now.weekday() < 5
