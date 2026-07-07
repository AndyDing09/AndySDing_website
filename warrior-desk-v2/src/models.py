"""Domain models — pydantic everywhere so bad shapes die at the boundary.

All timestamps are timezone-aware UTC (`datetime`), displayed in America/New_York
by the reporting layer. Every market-data record is stamped with its feed source
(`iex` | `sip`) because the two feeds genuinely disagree on low-float names.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


Feed = Literal["iex", "sip", "replay", "test"]


class Tick(BaseModel):
    symbol: str
    ts: datetime
    price: float
    size: int
    conditions: list[str] = []
    feed: Feed = "iex"


class Quote(BaseModel):
    symbol: str
    ts: datetime
    bid: float
    ask: float
    bid_size: int = 0
    ask_size: int = 0
    feed: Feed = "iex"

    @property
    def spread(self) -> float:
        return max(0.0, self.ask - self.bid)

    @property
    def spread_pct(self) -> float:
        mid = (self.ask + self.bid) / 2
        return (self.spread / mid) if mid > 0 else 1.0


class Bar(BaseModel):
    """One 1-minute (or N-minute) candle."""
    symbol: str
    ts: datetime                      # bar open time
    open: float
    high: float
    low: float
    close: float
    volume: int
    feed: Feed = "iex"

    @property
    def green(self) -> bool:
        return self.close > self.open

    @property
    def red(self) -> bool:
        return self.close < self.open

    @property
    def range(self) -> float:
        return self.high - self.low


class CatalystType(str, Enum):
    FDA_CLINICAL = "fda_clinical"
    EARNINGS = "earnings"
    CONTRACT_PARTNERSHIP = "contract_partnership"
    MA = "m&a"
    OFFERING_DILUTION = "offering_dilution"   # anti-catalyst: hard-exclude for the session
    OTHER = "other"


class NewsItem(BaseModel):
    symbol: str
    ts: datetime
    headline: str
    source: str = ""
    catalyst_type: CatalystType = CatalystType.OTHER


class FloatInfo(BaseModel):
    shares: Optional[float] = None       # None = unknown
    verified: bool = False               # two vendors agree within tolerance
    sources: dict[str, float] = {}       # vendor -> value, for the audit trail
    note: str = ""


class Candidate(BaseModel):
    """One watchlist row (§3.1 columns)."""
    symbol: str
    gap_pct: float = 0.0
    last: float = 0.0
    premkt_vol: int = 0
    rvol: float = 0.0
    float_shares: Optional[float] = None
    float_unverified: bool = False
    catalyst_headline: str = ""
    catalyst_type: CatalystType = CatalystType.OTHER
    dilution_flag: bool = False
    score: float = 0.0
    obviousness_rank: int = 0            # 1 = the obvious one (gap% x rvol leader)
    premkt_high: Optional[float] = None
    premkt_low: Optional[float] = None
    exchange: str = ""
    a_grade: bool = False


class Regime(str, Enum):
    TRENDING = "trending"
    MIXED = "mixed"
    CHOP = "chop"


class SetupName(str, Enum):
    GAP_AND_GO = "gap_and_go"
    BULL_FLAG = "bull_flag"
    VWAP_BREAKOUT = "vwap_breakout"
    HOD_CONTINUATION = "hod_continuation"


class SignalStatus(str, Enum):
    PROPOSED = "proposed"
    FILLED = "filled"
    SKIPPED = "skipped"      # skipped:<reason> — never became an order
    REJECTED = "rejected"    # rejected:<gate> — a risk gate said no


class Signal(BaseModel):
    """Everything the journal needs to measure the strategy honestly (§6)."""
    ts: datetime
    symbol: str
    setup: SetupName
    entry: float
    stop: float
    target: float
    planned_rr: float = 0.0
    score: float = 0.0
    regime: Regime = Regime.MIXED
    feed: Feed = "iex"
    spread_pct_at_signal: float = 0.0
    catalyst_type: CatalystType = CatalystType.OTHER
    float_band: str = "unknown"          # <10M | 10-20M | >20M | unknown
    obviousness_rank: int = 0
    shares: int = 0
    status: SignalStatus = SignalStatus.PROPOSED
    status_reason: str = ""              # insufficient_rr / spread / breaker:<name> / ...

    @property
    def risk_per_share(self) -> float:
        return max(0.0, self.entry - self.stop)

    @property
    def rr(self) -> float:
        r = self.risk_per_share
        return ((self.target - self.entry) / r) if r > 0 else 0.0


class Fill(BaseModel):
    ts: datetime
    symbol: str
    side: Literal["buy", "sell"]
    qty: int
    price: float                 # slippage-adjusted price actually recorded
    intended_price: float        # what the signal wanted
    order_id: str = ""

    @property
    def slippage(self) -> float:
        sign = 1 if self.side == "buy" else -1
        return sign * (self.price - self.intended_price)


class Position(BaseModel):
    symbol: str
    qty: int
    entry: float
    stop: float
    target: float
    opened_at: datetime
    signal_ts: datetime
    setup: SetupName
    breakeven_moved: bool = False
    trailing: bool = False
    mae: float = 0.0             # max adverse excursion, $/share (negative territory)
    mfe: float = 0.0             # max favorable excursion, $/share

    @property
    def risk_per_share(self) -> float:
        return max(1e-9, self.entry - self.stop)

    def r_at(self, price: float) -> float:
        return (price - self.entry) / self.risk_per_share


class TradeRecord(BaseModel):
    """A closed round-trip, the expectancy engine's raw material."""
    signal_ts: datetime
    closed_at: datetime
    symbol: str
    setup: SetupName
    entry_intended: float
    entry_fill: float
    exit_fill: float
    stop: float
    target: float
    qty: int
    realized_r: float
    pnl_usd: float
    mae: float
    mfe: float
    hold_seconds: float
    exit_reason: str             # stop / target / trail / time_stop / kill_switch
    slippage_usd: float = 0.0
    regime: Regime = Regime.MIXED
    catalyst_type: CatalystType = CatalystType.OTHER
    float_band: str = "unknown"
    feed: Feed = "iex"

    @property
    def win(self) -> bool:
        return self.pnl_usd > 0


class Incident(BaseModel):
    """Data-quality events: stale gaps, reconnects, float disagreements, halts…"""
    ts: datetime
    kind: str
    symbol: str = ""
    detail: str = ""
