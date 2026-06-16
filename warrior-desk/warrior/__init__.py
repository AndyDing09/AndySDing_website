"""Warrior Desk — a disciplined, paper-first momentum day-trading agent.

This package implements the Ross Cameron / Warrior Trading momentum strategy as
an autonomous agent that runs a strict 12-step pre-trade gauntlet, enforces hard
deterministic risk rules it cannot override, and writes a plain-English learning
journal.

Safety first: the default mode is *paper*. Live trading requires a deliberate,
multi-lock action (see ``warrior.locks``). This is an educational tool and is not
investment advice. Most day traders lose money.
"""

__version__ = "0.1.0"
