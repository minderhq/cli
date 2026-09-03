"""CLI dispatch: argument parsing, command wiring, login token caching, and
error → exit code. The client is stubbed; no network."""

import json

import pytest

from minder_cli import cli, config
from minder_cli.client import MinderError


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("MINDER_API_URL", raising=False)
    monkeypatch.delenv("MINDER_TOKEN", raising=False)


def test_health_dispatches_and_prints(monkeypatch, capsys):
    monkeypatch.setattr(cli.MinderClient, "health", lambda self: {"status": "healthy"})
    assert cli.main(["health"]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "healthy"}


def test_status_and_plugins_wire_to_client(monkeypatch, capsys):
    monkeypatch.setattr(cli.MinderClient, "status", lambda self: ["a"])
    assert cli.main(["status"]) == 0
    monkeypatch.setattr(cli.MinderClient, "plugins", lambda self: {"items": []})
    assert cli.main(["plugins"]) == 0


def test_login_caches_token(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.MinderClient, "login", lambda self, u, p: {"access_token": "T"}
    )
    rc = cli.main(["--api-url", "http://h:8000", "login", "-u", "a", "-p", "b"])
    assert rc == 0
    assert config.resolve_token() == "T"
    assert config.resolve_api_url() == "http://h:8000"


def test_login_without_token_in_response_errors(monkeypatch, capsys):
    monkeypatch.setattr(cli.MinderClient, "login", lambda self, u, p: {"nope": 1})
    assert cli.main(["login", "-u", "a", "-p", "b"]) == 1
    assert "no access_token" in capsys.readouterr().err


def test_client_error_becomes_exit_1(monkeypatch, capsys):
    def boom(self):
        raise MinderError("Not authenticated", status=401)

    monkeypatch.setattr(cli.MinderClient, "plugins", boom)
    assert cli.main(["plugins"]) == 1
    assert "error: Not authenticated" in capsys.readouterr().err


def test_flag_token_overrides(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        cli, "_client", lambda args: captured.update(token=args.token) or _Dummy()
    )

    class _Dummy:
        def status(self):
            return {}

    cli.main(["--token", "flagtok", "status"])
    assert captured["token"] == "flagtok"
