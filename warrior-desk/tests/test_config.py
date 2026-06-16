"""Config defaults + the hard 2:1 floor that code enforces regardless of YAML."""
from warrior.config import Config, HARD_MIN_REWARD_RISK, load_config


def test_defaults_match_spec():
    c = Config()
    assert c.trading_mode == "paper"
    assert c.paper_auto_approve is False
    assert c.shorting_enabled is False
    assert c.allow_overnight is False
    assert c.risk.max_risk_per_trade == 100
    assert c.risk.max_daily_loss == 300
    assert c.risk.min_reward_risk == 2.0
    assert c.selection.max_float == 100_000_000
    assert c.selection.min_rvol == 2.0


def test_rr_floor_cannot_be_lowered():
    c = Config()
    c.risk.min_reward_risk = 1.2   # try to cheat
    c = c.normalized()
    assert c.risk.min_reward_risk == HARD_MIN_REWARD_RISK


def test_consecutive_loss_halt_cannot_be_loosened():
    c = Config()
    c.risk.consecutive_loss_halt = 9
    c = c.normalized()
    assert c.risk.consecutive_loss_halt == 2


def test_load_config_from_yaml(tmp_path):
    y = tmp_path / "config.yaml"
    y.write_text(
        "trading_mode: paper\n"
        "shorting_enabled: true\n"
        "risk:\n"
        "  max_risk_per_trade: 250\n"
        "  min_reward_risk: 1.0\n"   # should be clamped up to 2.0
        "selection:\n"
        "  min_rvol: 3.0\n"
    )
    c = load_config(str(y), load_env=False)
    assert c.shorting_enabled is True
    assert c.risk.max_risk_per_trade == 250
    assert c.risk.min_reward_risk == 2.0       # floor enforced
    assert c.selection.min_rvol == 3.0


def test_unknown_mode_falls_back_to_paper():
    c = Config(trading_mode="banana").normalized()
    assert c.trading_mode == "paper"
