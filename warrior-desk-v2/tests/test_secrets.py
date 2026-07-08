"""Key loading: one secrets file works for scheduled AND manual runs.

Regression for the operator's live failure: `python scripts/run_session.py` in a
fresh shell had no env vars (only the Task Scheduler wrapper loaded
secrets.local.ps1), so alpaca-py raised its cryptic
'You must supply a method of authentication'. Python now reads the same files
directly and fails fast with instructions when keys are truly absent.
"""
import pytest

from src.data.secrets import (_parse_env_file, _parse_ps1, load_secrets_into_env,
                              require_alpaca_keys)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY", "FMP_API_KEY", "FINNHUB_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_parse_env_file():
    text = '# comment\nALPACA_API_KEY=PKAAA\nALPACA_SECRET_KEY="s3cret"\n\nBAD LINE\n'
    d = _parse_env_file(text)
    assert d["ALPACA_API_KEY"] == "PKAAA"
    assert d["ALPACA_SECRET_KEY"] == "s3cret"        # quotes stripped


def test_parse_ps1():
    text = ('# Warrior Desk secrets\n'
            '$env:ALPACA_API_KEY    = "PKBBB"\n'
            '$env:ALPACA_SECRET_KEY = "topsecret"\n'
            '# $env:FMP_API_KEY = "disabled"\n')
    d = _parse_ps1(text)
    assert d["ALPACA_API_KEY"] == "PKBBB"
    assert d["ALPACA_SECRET_KEY"] == "topsecret"


def test_parse_ps1_tolerates_single_quotes_and_bare_values():
    # Operators hand-edit this file; accept the quoting they actually type.
    text = ("$env:ALPACA_API_KEY = 'PKSINGLE'\n"
            "$env:ALPACA_SECRET_KEY = barevalue123\n")
    d = _parse_ps1(text)
    assert d["ALPACA_API_KEY"] == "PKSINGLE"
    assert d["ALPACA_SECRET_KEY"] == "barevalue123"


def test_manual_run_reads_secrets_local_ps1(tmp_path):
    (tmp_path / "secrets.local.ps1").write_text(
        '$env:ALPACA_API_KEY = "PKCCC"\n$env:ALPACA_SECRET_KEY = "sss"\n',
        encoding="utf-8")
    key, secret = require_alpaca_keys(root=tmp_path)
    assert (key, secret) == ("PKCCC", "sss")


def test_env_file_also_works(tmp_path):
    (tmp_path / ".env").write_text("ALPACA_API_KEY=PKDDD\nALPACA_SECRET_KEY=ddd\n",
                                   encoding="utf-8")
    key, secret = require_alpaca_keys(root=tmp_path)
    assert (key, secret) == ("PKDDD", "ddd")


def test_real_environment_always_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "PKREAL")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "real")
    (tmp_path / "secrets.local.ps1").write_text(
        '$env:ALPACA_API_KEY = "PKFILE"\n$env:ALPACA_SECRET_KEY = "file"\n',
        encoding="utf-8")
    key, _ = require_alpaca_keys(root=tmp_path)
    assert key == "PKREAL"


def test_untouched_template_values_are_ignored(tmp_path):
    (tmp_path / "secrets.local.ps1").write_text(
        '$env:ALPACA_API_KEY = "PK_your_paper_key_here"\n'
        '$env:ALPACA_SECRET_KEY = "your_paper_secret_here"\n', encoding="utf-8")
    load_secrets_into_env(root=tmp_path)
    import os
    assert os.environ.get("ALPACA_API_KEY") is None   # template ≠ credentials


def test_missing_keys_fail_fast_with_instructions(tmp_path):
    with pytest.raises(SystemExit) as e:
        require_alpaca_keys(root=tmp_path)
    msg = str(e.value)
    assert "secrets.local.ps1" in msg and "PAPER" in msg


def test_arbitrary_keys_propagate_to_env(tmp_path):
    # Float vendors read straight from os.environ; the loader must carry ANY key
    # in the secrets file, not only the Alpaca pair — otherwise floats stay
    # unverified and the quality score is stuck ~12 points low.
    import os
    (tmp_path / "secrets.local.ps1").write_text(
        '$env:ALPACA_API_KEY = "PKZZZ"\n$env:ALPACA_SECRET_KEY = "zzz"\n'
        '$env:FMP_API_KEY = "fmp123"\n$env:FINNHUB_API_KEY = "fh456"\n',
        encoding="utf-8")
    try:
        load_secrets_into_env(root=tmp_path)
        assert os.environ.get("FMP_API_KEY") == "fmp123"
        assert os.environ.get("FINNHUB_API_KEY") == "fh456"
    finally:                                     # don't leak into other tests
        os.environ.pop("FMP_API_KEY", None)
        os.environ.pop("FINNHUB_API_KEY", None)


def test_available_float_sources_reflects_env(monkeypatch):
    from src.data.floats import available_float_sources, float_sources_banner
    # keys absent (fixture cleared them): fmp/finnhub must not appear.
    assert "fmp" not in available_float_sources()
    assert "finnhub" not in available_float_sources()
    monkeypatch.setenv("FMP_API_KEY", "x")
    monkeypatch.setenv("FINNHUB_API_KEY", "y")
    active = available_float_sources()
    assert "fmp" in active and "finnhub" in active
    assert "cross-validation ON" in float_sources_banner()   # >=2 sources
