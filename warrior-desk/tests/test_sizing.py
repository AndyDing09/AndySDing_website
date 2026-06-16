"""Position-sizing math (§2.6) including the spec's worked example."""
from warrior.config import Config
from warrior.models import Grade
from warrior.sizing import size_position


def cfg(**risk_over):
    c = Config()
    for k, v in risk_over.items():
        setattr(c.risk, k, v)
    return c


def test_spec_example_500_risk_20c_stop_gives_2500_shares():
    # $500 max risk, $0.20 stop -> 2,500 shares (2,500 * 0.20 = $500 at risk)
    c = cfg(max_risk_per_trade=500, max_position_notional=1_000_000,
            max_pct_account_per_trade=1.0)
    r = size_position(c, entry=5.0, stop_distance=0.20, account_equity=1_000_000,
                      buying_power=1_000_000, grade=Grade.A)
    assert r.shares == 2500
    assert r.risk_dollars == 500.0
    assert r.binding_constraint == "risk_per_trade"


def test_b_grade_is_sized_down():
    c = cfg(max_risk_per_trade=500, max_position_notional=1_000_000,
            max_pct_account_per_trade=1.0, b_grade_size_factor=0.5)
    r = size_position(c, entry=5.0, stop_distance=0.20, account_equity=1_000_000,
                      buying_power=1_000_000, grade=Grade.B)
    assert r.shares == 1250


def test_c_grade_gets_zero_shares():
    r = size_position(cfg(), entry=5.0, stop_distance=0.20, account_equity=100_000,
                      buying_power=100_000, grade=Grade.C)
    assert r.shares == 0


def test_notional_cap_binds():
    c = cfg(max_risk_per_trade=10_000, max_position_notional=2000,
            max_pct_account_per_trade=1.0)
    r = size_position(c, entry=5.0, stop_distance=0.10, account_equity=1_000_000,
                      buying_power=1_000_000, grade=Grade.A)
    assert r.shares == 400  # 2000 / 5
    assert r.binding_constraint == "max_position_notional"


def test_buying_power_cap_binds():
    c = cfg(max_risk_per_trade=10_000, max_position_notional=1_000_000,
            max_pct_account_per_trade=1.0)
    r = size_position(c, entry=10.0, stop_distance=0.10, account_equity=1_000_000,
                      buying_power=1000, grade=Grade.A)
    assert r.shares == 100  # 1000 / 10
    assert r.binding_constraint == "buying_power"


def test_pct_cap_binds():
    c = cfg(max_risk_per_trade=10_000, max_position_notional=1_000_000,
            max_pct_account_per_trade=0.10)
    r = size_position(c, entry=10.0, stop_distance=0.10, account_equity=10_000,
                      buying_power=1_000_000, grade=Grade.A)
    assert r.shares == 100  # 0.10 * 10000 / 10
    assert r.binding_constraint == "max_pct_account"


def test_zero_stop_distance_is_safe():
    r = size_position(cfg(), entry=5.0, stop_distance=0.0, account_equity=100_000,
                      buying_power=100_000, grade=Grade.A)
    assert r.shares == 0
