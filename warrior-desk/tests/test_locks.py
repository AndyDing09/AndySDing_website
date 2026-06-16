"""Acceptance: a LIVE launch is provably impossible unless every §0 lock holds."""
import pytest

from warrior.config import Config, LIVE_ENV_TOKEN, LIVE_CONFIRM_PHRASE
from warrior.locks import LiveLockError, auto_approve_allowed, enforce_mode_locks, ACK_TEMPLATE


def _signed_ack(tmp_path):
    p = tmp_path / "ack.md"
    p.write_text(
        "# Live Account Acknowledgement\n"
        "SIGNED: YES\n"
        "Operator: Andy Ding\n"
        "Date: 2026-06-16\n"
        "Signature: Andy Ding\n"
    )
    return str(p)


def _unsigned_ack(tmp_path):
    p = tmp_path / "ack_template.md"
    p.write_text(ACK_TEMPLATE)
    return str(p)


def _live_config(tmp_path, *, token=True, ack="signed"):
    cfg = Config(trading_mode="live")
    cfg.secrets.allow_live_token = LIVE_ENV_TOKEN if token else ""
    if ack == "signed":
        cfg.live_ack_path = _signed_ack(tmp_path)
    elif ack == "unsigned":
        cfg.live_ack_path = _unsigned_ack(tmp_path)
    else:  # missing
        cfg.live_ack_path = str(tmp_path / "does_not_exist.md")
    return cfg


def test_paper_mode_needs_no_locks():
    assert enforce_mode_locks(Config(trading_mode="paper")) == "paper"


def test_live_all_locks_satisfied(tmp_path):
    cfg = _live_config(tmp_path)
    mode = enforce_mode_locks(cfg, input_fn=lambda _: LIVE_CONFIRM_PHRASE, interactive=True)
    assert mode == "live"


def test_live_blocked_without_env_token(tmp_path):
    cfg = _live_config(tmp_path, token=False)
    with pytest.raises(LiveLockError):
        enforce_mode_locks(cfg, input_fn=lambda _: LIVE_CONFIRM_PHRASE)


def test_live_blocked_without_signed_ack(tmp_path):
    cfg = _live_config(tmp_path, ack="missing")
    with pytest.raises(LiveLockError):
        enforce_mode_locks(cfg, input_fn=lambda _: LIVE_CONFIRM_PHRASE)


def test_live_blocked_with_unsigned_template_ack(tmp_path):
    cfg = _live_config(tmp_path, ack="unsigned")
    with pytest.raises(LiveLockError):
        enforce_mode_locks(cfg, input_fn=lambda _: LIVE_CONFIRM_PHRASE)


def test_live_blocked_with_wrong_typed_confirmation(tmp_path):
    cfg = _live_config(tmp_path)
    with pytest.raises(LiveLockError):
        enforce_mode_locks(cfg, input_fn=lambda _: "yes")


def test_live_blocked_when_non_interactive(tmp_path):
    cfg = _live_config(tmp_path)
    with pytest.raises(LiveLockError):
        enforce_mode_locks(cfg, input_fn=lambda _: LIVE_CONFIRM_PHRASE, interactive=False)


def test_approval_gate_cannot_be_disabled_in_live():
    live = Config(trading_mode="live", paper_auto_approve=True)
    assert auto_approve_allowed(live) is False


def test_paper_auto_approve_toggle():
    assert auto_approve_allowed(Config(trading_mode="paper", paper_auto_approve=False)) is False
    assert auto_approve_allowed(Config(trading_mode="paper", paper_auto_approve=True)) is True
