"""Configuration — every threshold lives in config.yaml, validated here.

Hard constraint #1 is enforced at this layer: the trading base URL must be the
Alpaca PAPER host. Any other value fails validation and the process exits before
a single network call. There is deliberately no live-money toggle to validate.
"""

from __future__ import annotations

import sys
from datetime import time
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

PAPER_BASE_URL = "https://paper-api.alpaca.markets"


def _hhmm(v: str | time) -> time:
    if isinstance(v, time):
        return v
    h, m = str(v).split(":")
    return time(int(h), int(m))


class DataCfg(BaseModel):
    trading_base_url: str = PAPER_BASE_URL
    feed: Literal["iex", "sip"] = "iex"
    scrub_sigma: float = 10.0
    scrub_min_size: int = 1
    stale_symbol_seconds: float = 5.0
    stale_stream_seconds: float = 10.0
    clock_max_skew_seconds: float = 2.0
    reconcile_interval_seconds: int = 300
    float_disagreement_pct: float = 0.25
    db_path: str = "data/warrior.duckdb"
    replay_dir: str = "replay/data"

    @field_validator("trading_base_url")
    @classmethod
    def _paper_only(cls, v: str) -> str:
        if v.rstrip("/") != PAPER_BASE_URL:
            raise ValueError(
                f"Refusing to start: trading_base_url must be the Alpaca PAPER endpoint "
                f"({PAPER_BASE_URL}). Live trading is out of scope by design — see CLAUDE.md."
            )
        return v.rstrip("/")


class UniverseCfg(BaseModel):
    price_min: float = 2.00
    price_max: float = 20.00
    rvol_min: float = 5.0
    float_max: int = 20_000_000
    float_aplus: int = 10_000_000
    pct_change_min: float = 0.10
    catalyst_required: bool = True
    catalyst_max_age_hours: float = 18
    exchanges: list[str] = ["NASDAQ", "NYSE", "AMEX"]


class WindowCfg(BaseModel):
    window: tuple[time, time]

    @field_validator("window", mode="before")
    @classmethod
    def _parse(cls, v):
        a, b = v
        return (_hhmm(a), _hhmm(b))


class GapAndGoCfg(WindowCfg):
    window: tuple[time, time] = (time(9, 30), time(10, 15))
    min_gap_pct: float = 0.04
    a_grade_gap_pct: float = 0.10


class BullFlagCfg(WindowCfg):
    window: tuple[time, time] = (time(9, 30), time(11, 30))
    min_pole_candles: int = 3
    max_retrace: float = 0.50


class VwapBreakoutCfg(WindowCfg):
    window: tuple[time, time] = (time(9, 45), time(15, 30))
    min_consolidation_minutes: int = 10
    breakout_volume_mult: float = 2.0
    atr_period: int = 14


class HodContinuationCfg(WindowCfg):
    window: tuple[time, time] = (time(9, 30), time(15, 30))


class SetupsCfg(BaseModel):
    gap_and_go: GapAndGoCfg = GapAndGoCfg()
    bull_flag: BullFlagCfg = BullFlagCfg()
    vwap_breakout: VwapBreakoutCfg = VwapBreakoutCfg()
    hod_continuation: HodContinuationCfg = HodContinuationCfg()


class ScannersCfg(BaseModel):
    premarket_start: time = time(7, 0)
    premarket_refresh_seconds: int = 60
    watchlist_freeze: time = time(9, 15)
    freeze_top_n_min: int = 3
    freeze_top_n_max: int = 5
    gapper_min_gap_pct: float = 0.04
    top_table_rows: int = 20
    hod_realert_window_seconds: int = 180

    _t = field_validator("premarket_start", "watchlist_freeze", mode="before")(_hhmm)


class RiskCfg(BaseModel):
    account_equity_fallback: float = 5000.0
    risk_pct_of_equity: float = 0.01
    risk_per_trade_usd: float = 50.0
    min_reward_risk: float = 2.0
    max_position_pct: float = 0.25
    max_spread_pct: float = 0.01
    daily_max_loss_r: float = 3.0
    max_consecutive_losses: int = 3
    no_new_entries_after: time = time(11, 30)
    halt_resume_quiet_minutes: int = 2

    _t = field_validator("no_new_entries_after", mode="before")(_hhmm)

    @field_validator("min_reward_risk")
    @classmethod
    def _rr_floor(cls, v: float) -> float:
        # The 2:1 gate is unconditional; config may raise it, never lower it.
        if v < 2.0:
            raise ValueError("risk.min_reward_risk cannot be below 2.0 — the gate is unconditional.")
        return v


class ExitsCfg(BaseModel):
    breakeven_at_r: float = 1.0
    trail_ema_at_r: float = 2.0
    ema_period: int = 9
    time_stop: time = time(15, 55)

    _t = field_validator("time_stop", mode="before")(_hhmm)


class SlippageCfg(BaseModel):
    ticks: int = 1
    tick_size: float = 0.01
    wide_spread_extra_ticks: int = 1


class ScoreWeights(BaseModel):
    rvol_percentile: float = 0.22
    float_tightness: float = 0.18
    catalyst_strength: float = 0.20
    pullback_cleanliness: float = 0.15
    dist_to_9ema: float = 0.10
    spread: float = 0.05
    obviousness: float = 0.10


class ScoreCfg(BaseModel):
    skip_below: int = 60
    full_size_at: int = 80
    dilution_cap: int = 59
    weights: ScoreWeights = ScoreWeights()


class RegimeCfg(BaseModel):
    symbol: str = "SPY"
    timeframe_minutes: int = 5
    ema_period: int = 9
    chop_score_bump: int = 10


class JournalCfg(BaseModel):
    rolling_expectancy_trades: int = 20
    min_sample_n: int = 30


class AlertsCfg(BaseModel):
    terminal_bell: bool = True
    desktop: bool = True
    discord_webhook: str = ""
    ntfy_topic: str = ""


class ReportsCfg(BaseModel):
    dir: str = "reports"
    live_dir: str = "reports/live"
    eod_open_at: time = time(16, 5)
    morning_brief_at: time = time(9, 20)

    _t = field_validator("eod_open_at", "morning_brief_at", mode="before")(_hhmm)


class Config(BaseModel):
    data: DataCfg = DataCfg()
    universe: UniverseCfg = UniverseCfg()
    scanners: ScannersCfg = ScannersCfg()
    setups: SetupsCfg = SetupsCfg()
    risk: RiskCfg = RiskCfg()
    exits: ExitsCfg = ExitsCfg()
    slippage: SlippageCfg = SlippageCfg()
    score: ScoreCfg = ScoreCfg()
    regime: RegimeCfg = RegimeCfg()
    journal: JournalCfg = JournalCfg()
    alerts: AlertsCfg = AlertsCfg()
    reports: ReportsCfg = ReportsCfg()


def load_config(path: str | Path = "config.yaml") -> Config:
    p = Path(path)
    raw = yaml.safe_load(p.read_text()) if p.exists() else {}
    return Config.model_validate(raw or {})


def load_or_exit(path: str | Path = "config.yaml") -> Config:
    """Startup entry: invalid config (including a non-paper URL) is a hard exit."""
    try:
        return load_config(path)
    except Exception as exc:
        print(f"CONFIG ERROR — refusing to start:\n{exc}", file=sys.stderr)
        raise SystemExit(2)
