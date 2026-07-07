"""A tiny asyncio pub/sub event bus.

The data layer publishes ticks/bars/news; scanners, strategies, and risk
subscribe. No polling loops where a stream exists (§8). Handlers may be sync or
async; a failing handler is logged and never takes the bus down.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

log = logging.getLogger("wd.bus")

Handler = Callable[[Any], None] | Callable[[Any], Awaitable[None]]

# Canonical topics
TICKS = "ticks"
QUOTES = "quotes"
BARS_1M = "bars_1m"
NEWS = "news"
HALTS = "halts"
SIGNALS = "signals"
FILLS = "fills"
INCIDENTS = "incidents"
ALERTS = "alerts"


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)

    async def publish(self, topic: str, payload: Any) -> None:
        for handler in list(self._subs.get(topic, [])):
            try:
                result = handler(payload)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                log.exception("handler for %r failed on %r", topic, type(payload).__name__)

    def publish_sync(self, topic: str, payload: Any) -> None:
        """Convenience for non-async call sites (replay, tests)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.publish(topic, payload))
        else:
            loop.create_task(self.publish(topic, payload))
