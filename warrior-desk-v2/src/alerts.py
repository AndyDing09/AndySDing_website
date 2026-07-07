"""Alert routing (§7.6): pluggable sinks, distinct prefixes per event class.

Sinks: terminal bell, desktop notification (macOS/Linux best-effort), Discord
webhook, ntfy.sh phone push. An alert failure is logged and never propagates —
alerting must not be able to take down trading.
"""

from __future__ import annotations

import json
import logging
import platform
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from .config import AlertsCfg

log = logging.getLogger("wd.alerts")

# Event classes and their distinct prefixes/sounds (§7.6).
PREFIX = {
    "HOD": "🔔 HOD",
    "FILL": "🟢 FILL",
    "EXIT": "🔴 EXIT",
    "BREAKER": "🛑 BREAKER",
    "DATA": "⚠️ DATA",
    "RECONCILE": "🛑 RECONCILE",
    "INFO": "ℹ️",
}

Sink = Callable[[str, str], None]     # (kind, message)


def terminal_sink(kind: str, message: str) -> None:
    print(f"{PREFIX.get(kind, kind)}  {message}")
    sys.stdout.write("\a")
    sys.stdout.flush()


def desktop_sink(kind: str, message: str) -> None:
    title = f"Warrior Desk — {kind}"
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(
                ["osascript", "-e",
                 f'display notification {json.dumps(message)} with title {json.dumps(title)}'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif system == "Linux" and shutil.which("notify-send"):
            subprocess.Popen(["notify-send", title, message],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Windows: terminal bell is the portable fallback.
    except Exception as exc:
        log.debug("desktop notification failed: %s", exc)


def _post(url: str, payload: bytes, headers: dict) -> None:
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=5)


def discord_sink(webhook: str) -> Sink:
    def sink(kind: str, message: str) -> None:
        _post(webhook, json.dumps(
            {"content": f"**{PREFIX.get(kind, kind)}** {message}"}).encode(),
            {"Content-Type": "application/json"})
    return sink


def ntfy_sink(topic: str) -> Sink:
    def sink(kind: str, message: str) -> None:
        _post(f"https://ntfy.sh/{topic}", message.encode(),
              {"Title": f"Warrior Desk {kind}", "Tags": kind.lower()})
    return sink


@dataclass
class AlertRouter:
    sinks: list[Sink] = field(default_factory=list)

    @classmethod
    def from_config(cls, cfg: AlertsCfg) -> "AlertRouter":
        sinks: list[Sink] = []
        if cfg.terminal_bell:
            sinks.append(terminal_sink)
        if cfg.desktop:
            sinks.append(desktop_sink)
        if cfg.discord_webhook:
            sinks.append(discord_sink(cfg.discord_webhook))
        if cfg.ntfy_topic:
            sinks.append(ntfy_sink(cfg.ntfy_topic))
        return cls(sinks)

    def send(self, kind: str, message: str) -> None:
        for sink in self.sinks:
            try:
                sink(kind, message)
            except Exception as exc:      # alerting never takes down trading
                log.warning("alert sink %s failed: %s", getattr(sink, "__name__", sink), exc)
