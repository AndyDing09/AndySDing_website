"""Catalyst feed classification (§4.6).

Headlines are classified into catalyst types; an OFFERING IS AN ANTI-CATALYST —
the symbol is hard-excluded for the session and ``dilution_flag`` is set. A
momentum stock diluting into its own spike is the classic trap the filter set
exists to avoid.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..models import CatalystType, NewsItem

# Order matters: offering/dilution phrases are checked FIRST so "announces
# offering to fund Phase 3 trial" is treated as the anti-catalyst it is.
_RULES: list[tuple[CatalystType, tuple[str, ...]]] = [
    (CatalystType.OFFERING_DILUTION,
     ("offering", "dilut", "registered direct", "atm program", "at-the-market",
      "warrant", "s-3", "424b", "pricing of", "shelf", "private placement",
      "convertible note")),
    (CatalystType.FDA_CLINICAL,
     ("fda", "phase 1", "phase 2", "phase 3", "phase i", "phase ii", "phase iii",
      "clinical", "topline", "breakthrough therapy", "approval", "ind ", "nda",
      "orphan drug")),
    (CatalystType.MA,
     ("merger", "acquisition", "acquire", "to be acquired", "buyout", "takeover",
      "tender offer", "strategic alternatives")),
    (CatalystType.EARNINGS,
     ("earnings", "quarterly results", "beats", "misses", "guidance", "revenue",
      "eps", "raises outlook", "preliminary results")),
    (CatalystType.CONTRACT_PARTNERSHIP,
     ("contract", "partnership", "collaboration", "awarded", "agreement",
      "purchase order", "deal with", "launch", "patent")),
]


def classify_headline(headline: str) -> CatalystType:
    h = (headline or "").lower()
    for ctype, keywords in _RULES:
        if any(k in h for k in keywords):
            return ctype
    return CatalystType.OTHER


def classify(item: NewsItem) -> NewsItem:
    item.catalyst_type = classify_headline(item.headline)
    return item


def is_fresh(item: NewsItem, now: datetime, max_age_hours: float) -> bool:
    return (now - item.ts) <= timedelta(hours=max_age_hours)


def best_catalyst(items: list[NewsItem], now: datetime, max_age_hours: float
                  ) -> tuple[NewsItem | None, bool]:
    """Return (best fresh catalyst or None, dilution_flag).

    Dilution wins unconditionally: one offering headline poisons the session for
    that symbol regardless of how good the other news is.
    """
    fresh = [classify(i) for i in items if is_fresh(i, now, max_age_hours)]
    dilution = any(i.catalyst_type == CatalystType.OFFERING_DILUTION for i in fresh)
    if dilution:
        offender = next(i for i in fresh
                        if i.catalyst_type == CatalystType.OFFERING_DILUTION)
        return offender, True
    if not fresh:
        return None, False
    priority = {CatalystType.FDA_CLINICAL: 4, CatalystType.MA: 4,
                CatalystType.EARNINGS: 3, CatalystType.CONTRACT_PARTNERSHIP: 2,
                CatalystType.OTHER: 0}
    fresh.sort(key=lambda i: (priority.get(i.catalyst_type, 0), i.ts), reverse=True)
    return fresh[0], False


def catalyst_strength(ctype: CatalystType) -> float:
    """0..1 input to the quality score: FDA/M&A > earnings > PR > vague."""
    return {
        CatalystType.FDA_CLINICAL: 1.0,
        CatalystType.MA: 1.0,
        CatalystType.EARNINGS: 0.75,
        CatalystType.CONTRACT_PARTNERSHIP: 0.55,
        CatalystType.OTHER: 0.25,
        CatalystType.OFFERING_DILUTION: 0.0,
    }[ctype]
