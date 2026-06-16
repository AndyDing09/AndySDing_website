"""Lightweight news/catalyst classification (Section 4, step 4).

A keyword classifier good enough to flag the *kind* of catalyst and whether it is
plausibly material. It never invents a catalyst — no news in means classification
"none". A clean technical breakout with no news is allowed downstream but scored
lower and flagged.
"""

from __future__ import annotations

from typing import Optional

from .models import Catalyst

# Ordered: first match wins. (keywords, classification, material)
_RULES = [
    (("fda", "phase 1", "phase 2", "phase 3", "phase i", "phase ii", "phase iii",
      "approval", "clinical", "trial", "breakthrough therapy", "topline"), "fda", True),
    (("earnings", "quarterly results", "beats", "guidance", "raises outlook",
      "revenue", "eps"), "earnings", True),
    (("merger", "acquisition", "acquire", "buyout", "to be acquired", "takeover",
      "tender offer"), "m&a", True),
    (("activist", "stake", "13d", "13-d"), "activist", True),
    (("offering", "dilution", "pricing of", "registered direct", "atm offering",
      "shelf", "warrants"), "offering", True),  # material but typically bearish
    (("partnership", "contract", "awarded", "collaboration", "agreement",
      "launch", "patent", "approval to list"), "pr", True),
    (("uplisting", "nasdaq", "short squeeze", "halt"), "pr", False),
]


def classify_text(headline: str) -> tuple[str, bool]:
    h = (headline or "").lower()
    if not h.strip():
        return "none", False
    for keywords, kind, material in _RULES:
        if any(k in h for k in keywords):
            return kind, material
    return "technical", False


def classify_catalyst(headline: str, source: str = "", ts=None) -> Catalyst:
    kind, material = classify_text(headline)
    return Catalyst(headline=headline, source=source, ts=ts,
                    classification=kind, material=material)


def best_catalyst(items: list[Catalyst]) -> Optional[Catalyst]:
    """Pick the most material/recent catalyst from a list."""
    if not items:
        return None
    # Material first, then most recent (None timestamps sort last).
    def key(c: Catalyst):
        return (1 if c.material else 0, c.ts.timestamp() if c.ts else 0)
    return sorted(items, key=key, reverse=True)[0]
