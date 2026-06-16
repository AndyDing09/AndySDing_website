"""Shared data models.

Plain dataclasses, standard-library only. These flow between the data layer, the
indicator/pattern layer, the gauntlet, the deterministic risk engine, execution,
and the journal. Keep them dumb: facts in, no behaviour that could hide a gate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ──────────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────────
class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


class StepStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INFO = "INFO"
    SKIP = "SKIP"


class Grade(str, Enum):
    A = "A"          # A+ setup — full size allowed
    B = "B"          # decent — auto-sized down
    C = "C"          # marginal — rejected
    REJECT = "REJECT"


class SessionWindow(str, Enum):
    PRIME = "prime"            # 09:30–11:30, most active, 1-min ok
    MIDDAY = "midday"          # 11:30–16:00, 5-min only, size down, A+ only
    PREMARKET = "premarket"    # watch/build watchlist only
    AFTERHOURS = "afterhours"  # watch only
    CLOSED = "closed"


class PatternKind(str, Enum):
    BULL_FLAG = "bull_flag"
    FLAT_TOP = "flat_top"
    NONE = "none"


# ──────────────────────────────────────────────────────────────────────────
# Market data
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Bar:
    """A single OHLCV candle."""
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def is_green(self) -> bool:
        return self.close > self.open

    @property
    def is_red(self) -> bool:
        return self.close < self.open

    @property
    def range(self) -> float:
        return self.high - self.low


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    bid_size: float = 0.0
    ask_size: float = 0.0
    ts: Optional[datetime] = None

    @property
    def spread(self) -> float:
        return round(self.ask - self.bid, 6)

    @property
    def mid(self) -> float:
        return round((self.ask + self.bid) / 2.0, 6)


@dataclass
class Catalyst:
    headline: str
    source: str
    ts: Optional[datetime] = None
    classification: str = "unclassified"   # earnings|fda|m&a|offering|pr|activist|technical|none
    material: bool = False

    @property
    def present(self) -> bool:
        return bool(self.headline) and self.classification != "none"


# ──────────────────────────────────────────────────────────────────────────
# Selection
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class Candidate:
    """A scan candidate evaluated against the four selection criteria (§2.1)."""
    symbol: str
    price: float = 0.0
    gap_pct: float = 0.0
    rvol: float = 0.0
    avg_dollar_volume: float = 0.0
    float_shares: Optional[float] = None      # None => unknown
    float_verified: bool = False              # False => approximated / unverified
    catalyst: Optional[Catalyst] = None
    # criteria scoring filled by the selector
    score: float = 0.0
    criteria: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────
# Patterns
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class PatternResult:
    kind: PatternKind = PatternKind.NONE
    valid: bool = False
    pole_low: Optional[float] = None
    pole_high: Optional[float] = None
    pullback_low: Optional[float] = None
    flat_top_price: Optional[float] = None
    retrace_pct: Optional[float] = None       # how much of the pole the pullback gave back
    pullback_len: int = 0
    holds_9ema: Optional[bool] = None
    holds_vwap: Optional[bool] = None
    trigger_price: Optional[float] = None      # break of prior-red-high / flat-top line
    confirm_volume: Optional[float] = None     # volume to confirm the breakout candle
    triggered: bool = False                    # has the breakout candle already fired?
    pole_volume: float = 0.0                   # avg volume across the pole
    pullback_volume: float = 0.0               # avg volume across the pullback
    reasons: list[str] = field(default_factory=list)

    @property
    def low_volume_pullback(self) -> bool:
        return self.pole_volume > 0 and self.pullback_volume <= self.pole_volume


# ──────────────────────────────────────────────────────────────────────────
# Gauntlet + proposal
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class GauntletStep:
    number: int
    name: str
    status: StepStatus
    detail: str = ""
    score: Optional[float] = None
    metrics: dict = field(default_factory=dict)

    @property
    def is_fail(self) -> bool:
        return self.status == StepStatus.FAIL


@dataclass
class GateResult:
    """One hard risk gate's verdict. ``passed`` is authoritative."""
    name: str
    passed: bool
    value: object = None
    threshold: object = None
    detail: str = ""


@dataclass
class RiskDecision:
    """The deterministic verdict. ``approved`` is the single source of truth.

    The LLM reasoning layer may read this but can never change it.
    """
    approved: bool
    gates: list[GateResult] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def failed_gates(self) -> list[GateResult]:
        return [g for g in self.gates if not g.passed]


@dataclass
class TradeProposal:
    """Everything the decision used — every number is a real computed fact."""
    symbol: str
    side: Side = Side.LONG
    pattern: PatternKind = PatternKind.NONE
    session_window: SessionWindow = SessionWindow.CLOSED

    entry: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    stop_distance: float = 0.0
    reward_risk: float = 0.0

    shares: int = 0
    risk_dollars: float = 0.0
    position_notional: float = 0.0
    position_pct: float = 0.0

    grade: Grade = Grade.REJECT
    grade_score: float = 0.0

    catalyst: Optional[Catalyst] = None
    metrics: dict = field(default_factory=dict)          # the full metric table (§ glossary)
    steps: list[GauntletStep] = field(default_factory=list)
    decision: Optional[RiskDecision] = None
    thesis: str = ""
    mode: str = "paper"
    created_at: Optional[datetime] = None

    # outcome of approval flow: "approved" | "rejected" | "approved-skipped" | None
    approval: Optional[str] = None

    @property
    def tradeable(self) -> bool:
        return bool(self.decision and self.decision.approved)


# ──────────────────────────────────────────────────────────────────────────
# Positions / fills
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class Position:
    symbol: str
    qty: int
    avg_entry: float
    stop: float
    target: float
    side: Side = Side.LONG
    initial_qty: int = 0
    initial_risk: float = 0.0           # entry-stop at open, per share
    scaled: bool = False                # has the first-target half-out happened?
    breakeven_moved: bool = False
    opened_at: Optional[datetime] = None
    realized_pnl: float = 0.0           # locked-in profit from partial exits
    order_ids: dict = field(default_factory=dict)
    events: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.initial_qty:
            self.initial_qty = self.qty
        if not self.initial_risk and self.side == Side.LONG:
            self.initial_risk = round(self.avg_entry - self.stop, 6)


@dataclass
class ClosedTrade:
    """A fully closed round-trip, used for stats and the graduation gate."""
    symbol: str
    side: Side
    entry: float
    exit: float
    qty: int
    gross_pnl: float
    r_multiple: float
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    hold_seconds: float = 0.0
    grade: Grade = Grade.REJECT
    pattern: PatternKind = PatternKind.NONE
    mode: str = "paper"
    exit_reason: str = ""

    @property
    def is_win(self) -> bool:
        return self.gross_pnl > 0


@dataclass
class ManageAction:
    """A position-management decision (Section 2.7)."""
    kind: str               # scale_half | move_stop_breakeven | exit_all | hold
    qty: int = 0
    price: float = 0.0
    reason: str = ""


@dataclass
class OrderResult:
    id: Optional[str] = None
    symbol: str = ""
    qty: int = 0
    side: str = "buy"
    status: str = "new"
    filled_avg_price: Optional[float] = None
    order_class: str = "simple"
    raw: dict = field(default_factory=dict)


def floor_int(x: float) -> int:
    """Floor that never returns a negative share count."""
    return max(0, int(math.floor(x)))
