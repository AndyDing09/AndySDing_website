"""The standing disclaimer (Section 13).

Printed on startup and written into the journal header. Keep it blunt and honest.
"""

DISCLAIMER = """\
================================================================================
WARRIOR DESK — STANDING DISCLAIMER (read every time)
================================================================================
Educational tool. NOT investment advice or a recommendation to buy or sell
anything. Most day traders lose money. (In one study ~3% of Taiwanese day
traders were reliably profitable; in another, ~97% of a Brazilian futures cohort
lost money.) Past or simulated performance does not predict future results.

Running in PAPER mode risks nothing. Enabling LIVE mode risks real capital and is
the Operator's sole responsibility. The agent enforces risk rules but cannot
guarantee profit or prevent loss. This is disciplined execution and honest
record-keeping — not a money printer.
================================================================================
"""

# A shorter one-liner suitable for log lines / journal entry footers.
DISCLAIMER_SHORT = (
    "Educational only — not investment advice. Most day traders lose money. "
    "Simulated/past performance does not predict future results."
)


def print_disclaimer() -> None:
    print(DISCLAIMER)
