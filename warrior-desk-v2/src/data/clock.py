"""Clock discipline (§4.7).

All comparisons happen in exchange time (America/New_York); storage is UTC.
At startup the local clock is compared to Alpaca's /v2/clock — skew beyond the
configured limit aborts, because a skewed clock silently breaks session windows,
time stops, and rvol's time-of-day matching.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Callable
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


class ClockSkewError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ny(dt: datetime) -> datetime:
    """Any aware datetime -> exchange time."""
    return dt.astimezone(NY)


def ny_time(dt: datetime) -> time:
    return ny(dt).timetz().replace(tzinfo=None)


def in_window(dt: datetime, window: tuple[time, time]) -> bool:
    t = ny_time(dt)
    return window[0] <= t < window[1]


def is_rth(dt: datetime) -> bool:
    return in_window(dt, (time(9, 30), time(16, 0))) and ny(dt).weekday() < 5


def minute_of_session(dt: datetime) -> int:
    """Minutes since 9:30 ET (negative pre-market). Used for time-of-day rvol."""
    t = ny(dt)
    return (t.hour - 9) * 60 + (t.minute - 30)


def check_skew(
    fetch_server_utc: Callable[[], datetime],
    max_skew_seconds: float,
    local_now: Callable[[], datetime] = utc_now,
) -> float:
    """Return the measured skew in seconds; raise ClockSkewError beyond the limit.

    ``fetch_server_utc`` is injected (the Alpaca /v2/clock call in production,
    a stub in tests) so this is testable without network.
    """
    server = fetch_server_utc()
    if server.tzinfo is None:
        server = server.replace(tzinfo=timezone.utc)
    skew = abs((local_now() - server).total_seconds())
    if skew > max_skew_seconds:
        raise ClockSkewError(
            f"Local clock is {skew:.2f}s off the exchange clock (limit "
            f"{max_skew_seconds}s). Fix the system clock; refusing to run."
        )
    return skew
