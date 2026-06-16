"""The paper->live graduation gate declines live until the bar is cleared."""
import csv

import pytest

from warrior.config import Config
from warrior.engine import require_graduation
from warrior.journal.local import CLOSED_FIELDS
from warrior.locks import LiveLockError
from warrior.stats import compute_stats, graduation_status, read_closed_trades


def _write_closed(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CLOSED_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_live_declined_with_no_track_record(tmp_path):
    cfg = Config(trading_mode="live")
    cfg.journal_dir = str(tmp_path / "journal")     # no closed trades yet
    with pytest.raises(LiveLockError) as e:
        require_graduation(cfg)
    assert "graduation gate" in str(e.value)
    assert "closed paper trades" in str(e.value)


def test_live_declined_with_too_few_trades(tmp_path):
    cfg = Config(trading_mode="live")
    cfg.journal_dir = str(tmp_path / "journal")
    rows = [{"symbol": "X", "gross_pnl": 50, "r_multiple": 2} for _ in range(10)]
    _write_closed(tmp_path / "journal" / "closed_trades.csv", rows)
    with pytest.raises(LiveLockError):
        require_graduation(cfg)


def test_graduation_eligible_with_solid_record(tmp_path):
    cfg = Config(trading_mode="live")
    cfg.journal_dir = str(tmp_path / "journal")
    rows = ([{"symbol": "W", "gross_pnl": 60, "r_multiple": 2.0} for _ in range(45)]
            + [{"symbol": "L", "gross_pnl": -30, "r_multiple": -1.0} for _ in range(5)])
    _write_closed(tmp_path / "journal" / "closed_trades.csv", rows)
    closed = read_closed_trades(str(tmp_path / "journal" / "closed_trades.csv"))
    s = compute_stats(closed)
    grad = graduation_status(cfg, s)
    assert grad.eligible, grad.missing
    # and require_graduation does not raise
    require_graduation(cfg)


def test_perfect_record_passes_profit_factor(tmp_path):
    cfg = Config(trading_mode="live")
    s = compute_stats([{"symbol": "W", "gross_pnl": 60, "r_multiple": 2.0} for _ in range(50)])
    grad = graduation_status(cfg, s)
    pf_crit = [c for c in grad.criteria if c[0] == "profit_factor>=1"][0]
    assert pf_crit[1] is True     # no losses -> infinite PF passes
