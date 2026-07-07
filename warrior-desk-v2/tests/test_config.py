"""Hard constraint #1: no code path to a live endpoint. Plus config integrity."""
import pytest
from pydantic import ValidationError

from src.config import PAPER_BASE_URL, Config, load_config, load_or_exit


def test_defaults_are_paper_and_spec_values():
    c = Config()
    assert c.data.trading_base_url == PAPER_BASE_URL
    assert c.universe.rvol_min == 5.0
    assert c.universe.float_max == 20_000_000
    assert c.risk.min_reward_risk == 2.0
    assert c.risk.max_position_pct == 0.25
    assert c.risk.no_new_entries_after.hour == 11


def test_live_url_refused():
    with pytest.raises(ValidationError, match="PAPER"):
        Config.model_validate({"data": {"trading_base_url": "https://api.alpaca.markets"}})


def test_any_non_paper_url_refused():
    for url in ("https://api.alpaca.markets/", "http://paper-api.alpaca.markets",
                "https://example.com"):
        with pytest.raises(ValidationError):
            Config.model_validate({"data": {"trading_base_url": url}})


def test_no_live_toggle_exists():
    """No field anywhere in the schema may act as a live-trading switch.

    `reports.live_dir` (the dashboard's JSON export folder) is the one sanctioned
    use of the word; anything else containing live/real-money is a regression.
    """
    def walk(model, prefix=""):
        out = []
        for name, f in model.model_fields.items():
            path = f"{prefix}{name}"
            out.append((path, f.annotation))
            ann = f.annotation
            if hasattr(ann, "model_fields"):
                out.extend(walk(ann, path + "."))
        return out

    allowed = {"reports.live_dir"}
    offenders = [p for p, ann in walk(Config)
                 if p not in allowed
                 and ("live" in p.lower() or "real_money" in p.lower() or ann is bool
                      and "paper" in p.lower())]
    assert offenders == [], f"live-trading-shaped config fields found: {offenders}"


def test_rr_gate_floor_cannot_be_lowered():
    with pytest.raises(ValidationError):
        Config.model_validate({"risk": {"min_reward_risk": 1.5}})


def test_load_or_exit_exits_on_live_url(tmp_path):
    bad = tmp_path / "config.yaml"
    bad.write_text('data:\n  trading_base_url: "https://api.alpaca.markets"\n')
    with pytest.raises(SystemExit):
        load_or_exit(bad)


def test_yaml_round_trip(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("universe:\n  rvol_min: 7.5\nrisk:\n  risk_per_trade_usd: 25\n")
    c = load_config(p)
    assert c.universe.rvol_min == 7.5
    assert c.risk.risk_per_trade_usd == 25
    assert c.data.trading_base_url == PAPER_BASE_URL   # untouched default stays paper
