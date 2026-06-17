"""Configuration loading + validation.

Loads ``config.yaml`` merged over built-in defaults (Section 7), and ``.env`` for
secrets and the live lock. The hard floors that protect the Operator (e.g. the
2:1 reward:risk minimum) are enforced *in code* — config can make them stricter
but never looser.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path
from typing import Any

import yaml

from .logging_setup import get_logger

log = get_logger("config")

# The reward:risk floor is a law of the system, not a setting. config may raise
# it but the code clamps anything below this back up to it.
HARD_MIN_REWARD_RISK = 2.0
# The consecutive-loss halt can be made stricter (1) but never disabled.
HARD_MAX_CONSECUTIVE_LOSS_HALT = 2

LIVE_ENV_TOKEN = "I_UNDERSTAND_THE_RISK"
LIVE_CONFIRM_PHRASE = "I understand the risk and accept full responsibility"


@dataclass
class RiskConfig:
    max_risk_per_trade: float = 100.0
    max_position_notional: float = 5000.0
    max_pct_account_per_trade: float = 0.20
    max_daily_loss: float = 300.0
    min_reward_risk: float = 2.0
    max_concurrent_positions: int = 1
    max_trades_per_day: int = 5
    consecutive_loss_halt: int = 2
    loss_cooldown_minutes: int = 10
    max_spread: float = 0.10
    max_chase: float = 0.05
    # B-grade setups are auto-sized down by this factor (§3.1 "no oversized
    # positions without A+ setups"). A=full, B=scaled, C=rejected.
    b_grade_size_factor: float = 0.5
    # stop-too-wide policy (§2.4): "reject" or "mechanical"
    wide_stop_policy: str = "reject"
    mechanical_stop_distance: float = 0.20
    max_stop_pct: float = 0.05      # a stop wider than this % of price is "too wide"
    # exit logic (§2.7): scale at the first target (~2R), sell into an extension
    # bar (a parabolic spike up ~4R), and never widen a stop.
    first_target_r: float = 2.0
    extension_r: float = 4.0
    extension_atr_mult: float = 2.0

    def normalized(self) -> "RiskConfig":
        """Clamp values to their hard floors. Never loosen a protective rule."""
        out = RiskConfig(**asdict(self))
        if out.min_reward_risk < HARD_MIN_REWARD_RISK:
            log.warning(
                "min_reward_risk=%.2f is below the hard floor; clamping to %.2f.",
                out.min_reward_risk, HARD_MIN_REWARD_RISK,
            )
            out.min_reward_risk = HARD_MIN_REWARD_RISK
        if out.consecutive_loss_halt > HARD_MAX_CONSECUTIVE_LOSS_HALT:
            log.warning(
                "consecutive_loss_halt=%d exceeds the hard cap; clamping to %d.",
                out.consecutive_loss_halt, HARD_MAX_CONSECUTIVE_LOSS_HALT,
            )
            out.consecutive_loss_halt = HARD_MAX_CONSECUTIVE_LOSS_HALT
        out.consecutive_loss_halt = max(1, out.consecutive_loss_halt)
        out.max_concurrent_positions = max(1, out.max_concurrent_positions)
        return out


@dataclass
class SelectionConfig:
    max_float: float = 100_000_000
    ideal_float: float = 20_000_000
    min_rvol: float = 2.0
    min_avg_dollar_volume: float = 2_000_000     # liquidity floor (no thin names)
    min_share_volume: float = 500_000            # real participation today
    min_price: float = 2.0           # no sub-$2 penny stocks (raise to 5 for strict)
    max_price: float = 20.0          # small-cap focus; momentum names are cheap
    major_exchanges_only: bool = True            # drop OTC / pink-sheet names
    pullback_max_retrace: float = 0.50   # reject pullbacks deeper than 50% of pole


@dataclass
class SessionsConfig:
    prime_start: str = "09:30"
    prime_end: str = "11:30"
    market_close: str = "16:00"
    hard_flat_time: str = "15:55"
    trade_premarket: bool = False
    trade_afterhours: bool = False
    timezone: str = "America/New_York"


@dataclass
class GraduationGateConfig:
    min_closed_trades: int = 50
    require_positive_expectancy: bool = True
    max_drawdown_pct: float = 0.15


@dataclass
class Secrets:
    """Loaded from environment / .env. Never logged, never journaled."""
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    anthropic_api_key: str = ""
    allow_live_token: str = ""          # WARRIOR_ALLOW_LIVE
    google_credentials_path: str = ""
    google_token_path: str = ""
    google_doc_id: str = ""
    publish_url: str = ""               # WARRIOR_PUBLISH_URL -> your site's warrior.php
    publish_token: str = ""             # WARRIOR_PUBLISH_TOKEN (matches the server token file)

    @property
    def has_alpaca(self) -> bool:
        return bool(self.alpaca_api_key and self.alpaca_secret_key)

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)


@dataclass
class Config:
    trading_mode: str = "paper"            # paper | live
    paper_auto_approve: bool = False
    shorting_enabled: bool = False
    allow_overnight: bool = False
    account_profile: str = "cash_under_25k"   # cash_under_25k | margin_under_25k | over_25k
    timeframe_prime: str = "1Min"
    timeframe_midday: str = "5Min"
    poll_seconds: int = 30
    max_evaluate_per_pass: int = 10     # how many top movers to deep-analyze per cycle
    scan_cache_seconds: int = 25        # reuse the market scan within a cycle
    log_level: str = "INFO"
    use_llm_reasoning: bool = True         # uses anthropic if a key is present
    llm_model: str = "claude-sonnet-4-6"
    manual_broker_name: str = "your broker"  # shown in advisory alerts, e.g. "Firstrade"
    scanner: str = "yahoo"                    # market scanner: yahoo | alpaca | none
    state_path: str = "state/state.json"
    journal_dir: str = "journal"
    log_dir: str = "logs"
    live_ack_path: str = "live_account_acknowledgement.md"

    risk: RiskConfig = field(default_factory=RiskConfig)
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    sessions: SessionsConfig = field(default_factory=SessionsConfig)
    graduation_gate: GraduationGateConfig = field(default_factory=GraduationGateConfig)
    secrets: Secrets = field(default_factory=Secrets)

    @property
    def is_live(self) -> bool:
        return str(self.trading_mode).lower() == "live"

    def normalized(self) -> "Config":
        self.risk = self.risk.normalized()
        if self.trading_mode not in ("paper", "live"):
            log.warning("Unknown trading_mode=%r; defaulting to paper.", self.trading_mode)
            self.trading_mode = "paper"
        return self


# ──────────────────────────────────────────────────────────────────────────
# Loading
# ──────────────────────────────────────────────────────────────────────────
def _build_nested(cls, data: dict[str, Any]):
    """Instantiate a dataclass from a dict, ignoring unknown keys (with a warn)."""
    known = {f.name for f in fields(cls)}
    kwargs = {}
    for k, v in (data or {}).items():
        if k in known:
            kwargs[k] = v
        else:
            log.warning("Ignoring unknown config key %r under %s.", k, cls.__name__)
    return cls(**kwargs)


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader (no external dependency). Does not overwrite existing
    environment variables, so real env always wins over a committed file."""
    p = Path(path)
    if not p.exists():
        return
    try:
        for raw in p.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)
    except Exception as exc:
        log.warning("Could not read %s: %s", path, exc)


def load_secrets() -> Secrets:
    return Secrets(
        alpaca_api_key=os.environ.get("ALPACA_API_KEY", ""),
        alpaca_secret_key=os.environ.get("ALPACA_SECRET_KEY", ""),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        allow_live_token=os.environ.get("WARRIOR_ALLOW_LIVE", ""),
        google_credentials_path=os.environ.get("GOOGLE_CREDENTIALS_PATH", ""),
        google_token_path=os.environ.get("GOOGLE_TOKEN_PATH", ""),
        google_doc_id=os.environ.get("WARRIOR_GOOGLE_DOC_ID", ""),
        publish_url=os.environ.get("WARRIOR_PUBLISH_URL", ""),
        publish_token=os.environ.get("WARRIOR_PUBLISH_TOKEN", ""),
    )


def load_config(path: str | Path = "config.yaml", load_env: bool = True) -> Config:
    """Load config from YAML over defaults, then secrets from env, then normalize."""
    if load_env:
        load_dotenv()

    raw: dict[str, Any] = {}
    p = Path(path)
    if p.exists():
        try:
            raw = yaml.safe_load(p.read_text()) or {}
        except Exception as exc:
            log.error("Failed to parse %s (%s); using defaults.", path, exc)
            raw = {}
    else:
        log.info("No config file at %s; using built-in defaults.", path)

    cfg = Config()
    top_known = {f.name for f in fields(Config)}
    nested = {"risk", "selection", "sessions", "graduation_gate", "secrets"}
    for k, v in raw.items():
        if k in nested:
            continue
        if k in top_known:
            setattr(cfg, k, v)
        else:
            log.warning("Ignoring unknown top-level config key %r.", k)

    if "risk" in raw:
        cfg.risk = _build_nested(RiskConfig, raw["risk"])
    if "selection" in raw:
        cfg.selection = _build_nested(SelectionConfig, raw["selection"])
    if "sessions" in raw:
        cfg.sessions = _build_nested(SessionsConfig, raw["sessions"])
    if "graduation_gate" in raw:
        cfg.graduation_gate = _build_nested(GraduationGateConfig, raw["graduation_gate"])

    cfg.secrets = load_secrets()
    return cfg.normalized()
