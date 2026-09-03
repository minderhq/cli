"""Config resolution: flag > env > file > default, and token caching."""

import json

import pytest

from minder_cli import config


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    # point the config at a temp dir + clear env so tests never touch the real one
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("MINDER_API_URL", raising=False)
    monkeypatch.delenv("MINDER_TOKEN", raising=False)
    return tmp_path


def test_api_url_precedence(monkeypatch):
    assert config.resolve_api_url() == config.DEFAULT_API_URL
    config.save_token("t", api_url="http://from-file:8000")
    assert config.resolve_api_url() == "http://from-file:8000"
    monkeypatch.setenv("MINDER_API_URL", "http://from-env:8000")
    assert config.resolve_api_url() == "http://from-env:8000"
    assert config.resolve_api_url("http://from-flag:8000") == "http://from-flag:8000"


def test_token_precedence(monkeypatch):
    assert config.resolve_token() is None
    config.save_token("file-token")
    assert config.resolve_token() == "file-token"
    monkeypatch.setenv("MINDER_TOKEN", "env-token")
    assert config.resolve_token() == "env-token"
    assert config.resolve_token("flag-token") == "flag-token"


def test_save_token_writes_json(_isolate):
    config.save_token("abc", api_url="http://x:8000")
    data = json.loads(config.config_path().read_text(encoding="utf-8"))
    assert data == {"token": "abc", "api_url": "http://x:8000"}


def test_load_file_tolerates_missing_and_garbage(_isolate):
    assert config.load_file() == {}  # missing
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    config.config_path().write_text("not json", encoding="utf-8")
    assert config.load_file() == {}  # garbage → {}
