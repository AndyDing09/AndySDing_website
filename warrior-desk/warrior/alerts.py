"""Live, actionable trade alerts (for the 'tell me when to enter/exit' workflow).

Prints a loud, timestamped banner for every actionable moment — ENTER, SCALE,
MOVE-STOP, EXIT — framed so you can mirror it by hand in a broker without an API
(e.g. Firstrade). Best-effort terminal bell + desktop notification on top, all
guarded so an alert can never crash or block the trading loop.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from datetime import datetime

from .logging_setup import get_logger
from .models import ManageAction, Position, TradeProposal

log = get_logger("alerts")

_ICON = {"ENTER": "🟢", "EXIT": "🔴", "SCALE": "🟡", "STOP": "🟠", "WATCH": "👀", "INFO": "🔔"}


class Alerter:
    def __init__(self, sound: bool = True, desktop: bool = True, broker_name: str = "your broker"):
        self.sound = sound
        self.desktop = desktop
        self.broker_name = broker_name
        self.history: list[str] = []

    # ── public events ──
    def entry(self, p: TradeProposal, pos: Position) -> None:
        self._banner("ENTER", p.symbol, [
            f"BUY {pos.qty:,} shares {p.symbol}  @ limit {pos.avg_entry:.2f}",
            f"STOP (protective)    @ {pos.stop:.2f}   (risk ${p.risk_dollars:.0f})",
            f"TARGET (first)       @ {pos.target:.2f}   (R:R {p.reward_risk:.1f}, grade {p.grade.value})",
        ], headline=f"place this in {self.broker_name} now")

    def action(self, symbol: str, a: ManageAction, pos: Position) -> None:
        if a.kind == "scale_half":
            self._banner("SCALE", symbol, [
                f"SELL {a.qty:,} shares {symbol} @ {a.price:.2f}   ({a.reason})",
                f"then MOVE STOP to break-even {pos.avg_entry:.2f} on the rest",
            ], headline=f"adjust in {self.broker_name}")
        elif a.kind == "exit_all":
            self._banner("EXIT", symbol, [
                f"SELL {a.qty:,} shares {symbol} @ {a.price:.2f}",
                f"reason: {a.reason}",
            ], headline=f"close in {self.broker_name} now")
        elif a.kind == "move_stop_breakeven":
            self._banner("STOP", symbol, [
                f"MOVE STOP on {symbol} to break-even {a.price:.2f} — the trade is now free",
            ], headline=f"adjust stop in {self.broker_name}")

    def watch(self, p: TradeProposal) -> None:
        """Heads-up that a setup cleared the gauntlet but hasn't broken out yet —
        so you can pre-stage the order instead of staring at silence."""
        self._banner("WATCH", p.symbol, [
            f"{p.pattern.value} forming (grade {p.grade.value}) — coiling under {p.entry:.2f}",
            f"pre-stage: BUY {p.shares:,} over {p.entry:.2f}, stop {p.stop:.2f}, "
            f"target {p.target:.2f} (R:R {p.reward_risk:.1f})",
        ], headline="watching for the breakout — get ready")

    def info(self, title: str, lines: list[str]) -> None:
        self._banner("INFO", title, lines)

    # ── rendering ──
    def _banner(self, kind: str, symbol: str, lines: list[str], headline: str = "") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        icon = _ICON.get(kind, "🔔")
        bar = "━" * 60
        out = ["", bar, f"{icon}  {kind} — {symbol}   [{ts}]"]
        if headline:
            out.append(f"   → {headline.upper()}:")
        out += [f"     {ln}" for ln in lines]
        out.append(bar)
        text = "\n".join(out)
        print(text)
        self.history.append(f"{ts} {kind} {symbol}: {'; '.join(lines)}")
        self._ring()
        if kind in ("ENTER", "EXIT"):
            self._desktop(f"Warrior Desk: {kind} {symbol}", lines[0] if lines else kind)

    def _ring(self) -> None:
        if not self.sound:
            return
        try:
            sys.stdout.write("\a")
            sys.stdout.flush()
        except Exception:
            pass

    def _desktop(self, title: str, message: str) -> None:
        if not self.desktop:
            return
        try:
            sysname = platform.system()
            if sysname == "Darwin":
                subprocess.Popen(
                    ["osascript", "-e", f'display notification {message!r} with title {title!r}'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sysname == "Linux" and shutil.which("notify-send"):
                subprocess.Popen(["notify-send", title, message],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # Windows: the terminal bell above is the portable fallback.
        except Exception as exc:  # never let a notification break trading
            log.debug("desktop notification failed: %s", exc)
