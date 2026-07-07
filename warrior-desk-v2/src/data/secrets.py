"""Key loading — one source of truth, however the program is launched.

Search order (first hit wins, real environment always wins over files):
  1. real environment variables (what the Task Scheduler wrapper sets),
  2. ``.env`` in the repo root (KEY=value lines),
  3. ``secrets.local.ps1`` in the repo root (the $env:KEY = "value" lines the
     scheduled-task wrapper dot-sources) — parsed here too, so a manual
     ``python scripts/run_session.py`` works off the SAME file.

Missing keys fail fast with instructions instead of alpaca-py's cryptic
"You must supply a method of authentication".
"""

from __future__ import annotations

import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_PS1_LINE = re.compile(r'^\s*\$env:([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"([^"]*)"', re.MULTILINE)


def _parse_env_file(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def _parse_ps1(text: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in _PS1_LINE.finditer(text)}


def load_secrets_into_env(root: Path = REPO_ROOT) -> None:
    """Populate os.environ from the secrets files WITHOUT overriding real env."""
    found: dict[str, str] = {}
    env_file = root / ".env"
    ps1_file = root / "secrets.local.ps1"
    try:
        if env_file.exists():
            found.update(_parse_env_file(env_file.read_text(encoding="utf-8")))
        if ps1_file.exists():
            found.update(_parse_ps1(ps1_file.read_text(encoding="utf-8")))
    except OSError:
        pass
    for key, val in found.items():
        if val and not val.startswith("PK_your"):     # ignore untouched template values
            os.environ.setdefault(key, val)


def require_alpaca_keys(root: Path = REPO_ROOT) -> tuple[str, str]:
    """Return (key, secret) or exit with a message a human can act on."""
    load_secrets_into_env(root)
    key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        raise SystemExit(
            "Alpaca PAPER keys not found.\n\n"
            f"Put them in {root / 'secrets.local.ps1'}\n"
            "  (copy secrets.local.ps1.example and fill in both lines)\n"
            f"or in {root / '.env'} as ALPACA_API_KEY=... / ALPACA_SECRET_KEY=...\n"
            "or set them as environment variables in this window.\n"
            "Paper key IDs start with PK. This system only accepts the paper endpoint."
        )
    return key, secret
