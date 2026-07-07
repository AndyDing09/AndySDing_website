"""Mode locks (Section 0) — the multi-lock that makes live trading deliberate.

Live mode is never a default and never auto-enabled. To run live, ALL of the
following must hold, checked at startup, or the app refuses to start:

  1. config ``trading_mode: live``
  2. env ``WARRIOR_ALLOW_LIVE=I_UNDERSTAND_THE_RISK``
  3. an interactive typed confirmation at launch
  4. a populated, signed & dated ``live_account_acknowledgement.md``

Any missing lock raises :class:`LiveLockError` — the caller hard-exits with a
clear message. There is intentionally no code path that "helpfully" enables live.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Callable

from .config import Config, LIVE_ENV_TOKEN, LIVE_CONFIRM_PHRASE
from .logging_setup import get_logger

log = get_logger("locks")


class LiveLockError(RuntimeError):
    """Raised when live mode is requested but a lock is not satisfied."""


def _ack_is_signed(path: str | Path) -> tuple[bool, str]:
    """Return (ok, reason). The ack file must exist and be explicitly signed/dated."""
    p = Path(path)
    if not p.exists():
        return False, f"acknowledgement file {p} does not exist"
    try:
        text = p.read_text(encoding="utf-8")
    except Exception as exc:
        return False, f"could not read acknowledgement file: {exc}"

    if not text.strip():
        return False, "acknowledgement file is empty"

    def field(name: str) -> str:
        m = re.search(rf"^{name}\s*:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
        return m.group(1).strip() if m else ""

    signed = field("SIGNED").upper()
    if signed != "YES":
        return False, "acknowledgement is not marked 'SIGNED: YES'"

    signature = field("Signature")
    placeholders = {"", "<name>", "<your name>", "__________", "tbd", "none"}
    if signature.lower() in placeholders:
        return False, "acknowledgement has no real signature"

    raw_date = field("Date")
    if not raw_date:
        return False, "acknowledgement has no date"
    if not re.search(r"\d{4}-\d{2}-\d{2}", raw_date):
        return False, "acknowledgement date is not a real YYYY-MM-DD date"

    return True, "ok"


def enforce_mode_locks(
    config: Config,
    input_fn: Callable[[str], str] = input,
    interactive: bool = True,
) -> str:
    """Resolve and authorise the trading mode.

    Returns the authorised mode string ("paper" or "live"). Raises
    :class:`LiveLockError` if live is requested without every lock satisfied.

    ``interactive`` may be set False for non-interactive sims, but then live mode
    can NEVER be authorised (the typed confirmation cannot be obtained).
    """
    if not config.is_live:
        return "paper"

    failures: list[str] = []

    # Lock 1: config says live (we are here because it does).
    # Lock 2: env token.
    if config.secrets.allow_live_token != LIVE_ENV_TOKEN:
        failures.append(
            f"env WARRIOR_ALLOW_LIVE must equal '{LIVE_ENV_TOKEN}' "
            f"(got: {'<empty>' if not config.secrets.allow_live_token else 'a different value'})"
        )

    # Lock 4: signed acknowledgement file.
    ok, reason = _ack_is_signed(config.live_ack_path)
    if not ok:
        failures.append(f"signed acknowledgement missing/invalid: {reason}")

    # Lock 3: interactive typed confirmation (checked last so the Operator only
    # types it after the cheaper checks pass).
    if not interactive:
        failures.append("interactive confirmation unavailable in non-interactive mode")
    elif not failures:
        log.warning("LIVE mode requested. Real capital is at risk.")
        print(
            "\n*** LIVE TRADING REQUESTED — REAL MONEY ***\n"
            f'To proceed, type exactly:\n  {LIVE_CONFIRM_PHRASE}\n'
        )
        typed = input_fn("Confirmation> ").strip()
        if typed != LIVE_CONFIRM_PHRASE:
            failures.append("typed confirmation did not match the required phrase")

    if failures:
        msg = "Refusing to start in LIVE mode. Unsatisfied locks:\n" + "\n".join(
            f"  - {f}" for f in failures
        )
        log.error(msg)
        raise LiveLockError(msg)

    log.warning("All live locks satisfied. Proceeding in LIVE mode.")
    return "live"


def auto_approve_allowed(config: Config) -> bool:
    """The human-approval gate policy.

    In live mode the approval gate is MANDATORY and cannot be disabled — there is
    no config flag that turns it off. In paper mode it may be auto-approved for
    unattended sim runs (but every proposal is still logged).
    """
    if config.is_live:
        return False
    return bool(config.paper_auto_approve)


ACK_TEMPLATE = f"""\
# Live Account Acknowledgement

Fill this in honestly and set `SIGNED: YES` ONLY when you mean it. Live mode will
refuse to start until this file is signed and dated with a real date.

SIGNED: NO
Operator: <your name>
Date: <YYYY-MM-DD>
Signature: <your name>

I acknowledge that:
- Live mode trades REAL money and can lose REAL money.
- Most day traders lose money; this tool cannot guarantee profit or prevent loss.
- I have run a meaningful paper track record and cleared the graduation gate.
- Enabling live mode is my sole responsibility. The env token to enable it is
  `WARRIOR_ALLOW_LIVE={LIVE_ENV_TOKEN}` and I will type the launch confirmation
  knowingly.
"""
