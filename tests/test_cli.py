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
    assert cli.main(["health", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "healthy"}


def test_status_and_plugins_wire_to_client(monkeypatch, capsys):
    monkeypatch.setattr(cli.MinderClient, "status", lambda self: ["a"])
    assert cli.main(["status"]) == 0
    monkeypatch.setattr(cli.MinderClient, "plugins", lambda self: {"items": []})
    assert cli.main(["plugins", "list"]) == 0


def test_login_caches_token(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.MinderClient, "login", lambda self, u, p: {"access_token": "T"}
    )
    rc = cli.main(["login", "-u", "a", "-p", "b", "--api-url", "http://h:8000"])
    assert rc == 0
    assert config.resolve_token() == "T"
    assert config.resolve_api_url() == "http://h:8000"


def test_login_without_token_in_response_errors(monkeypatch, capsys):
    monkeypatch.setattr(cli.MinderClient, "login", lambda self, u, p: {"nope": 1})
    assert cli.main(["login", "-u", "a", "-p", "b"]) == 1
    assert "no access_token" in capsys.readouterr().err


def test_billing_and_org_list_dispatch(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.MinderClient, "billing_subscription", lambda self: {"tier": "pro"}
    )
    assert cli.main(["billing", "subscription", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"tier": "pro"}

    monkeypatch.setattr(
        cli.MinderClient, "billing_checkout", lambda self, tier: {"tier": tier}
    )
    assert cli.main(["billing", "checkout", "enterprise"]) == 0

    monkeypatch.setattr(
        cli.MinderClient, "orgs_mine", lambda self: {"organizations": []}
    )
    assert cli.main(["org", "list"]) == 0


def test_org_switch_caches_new_token(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(
        cli.MinderClient,
        "org_switch",
        lambda self, organization_id: seen.update(org=organization_id)
        or {"access_token": "T2", "active_tenant_id": str(organization_id)},
    )
    rc = cli.main(["org", "switch", "42", "--api-url", "http://h:8000"])
    assert rc == 0
    assert seen == {"org": 42}  # arg parsed as int
    # the re-minted token is persisted so the next command acts in the new org
    assert config.resolve_token() == "T2"


def test_client_error_becomes_exit_1(monkeypatch, capsys):
    def boom(self):
        raise MinderError("Not authenticated", status=401)

    monkeypatch.setattr(cli.MinderClient, "plugins", boom)
    assert cli.main(["plugins", "list"]) == 1
    assert "error: Not authenticated" in capsys.readouterr().err


def test_flag_token_overrides(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        cli, "_client", lambda args: captured.update(token=args.token) or _Dummy()
    )

    class _Dummy:
        def status(self):
            return {}

    cli.main(["status", "--token", "flagtok"])
    assert captured["token"] == "flagtok"


def test_rag_kbs_and_query_dispatch(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(
        cli.MinderClient, "rag_kbs", lambda self, limit: seen.update(limit=limit) or []
    )
    assert cli.main(["rag", "kbs", "--limit", "7"]) == 0
    assert seen["limit"] == 7

    q_seen = {}
    monkeypatch.setattr(
        cli.MinderClient,
        "rag_query",
        lambda self, pid, q, top_k: q_seen.update(pid=pid, q=q, k=top_k) or {"ok": 1},
    )
    capsys.readouterr()  # clear the accumulated output from the kbs call above
    assert cli.main(["rag", "query", "p1", "hello?", "--top-k", "2"]) == 0
    assert q_seen == {"pid": "p1", "q": "hello?", "k": 2}
    assert capsys.readouterr().out.strip() == "ok: 1"  # human render of {"ok": 1}


def test_models_list_and_pull_dispatch(monkeypatch):
    monkeypatch.setattr(cli.MinderClient, "models_list", lambda self: {"items": []})
    assert cli.main(["models", "list"]) == 0
    seen = {}
    monkeypatch.setattr(
        cli.MinderClient, "models_pull", lambda self, mid: seen.update(mid=mid) or {}
    )
    assert cli.main(["models", "pull", "llama3.2:latest"]) == 0
    assert seen["mid"] == "llama3.2:latest"


def test_rag_requires_a_subcommand(capsys):
    with __import__("pytest").raises(SystemExit):
        cli.main(["rag"])  # required=True → argparse exits


def test_ai_chat_extracts_assistant_content(monkeypatch, capsys):
    resp = {"choices": [{"message": {"content": "the answer"}}]}
    monkeypatch.setattr(cli.MinderClient, "ai_chat", lambda self, m, model, tools: resp)
    assert cli.main(["ai", "chat", "question?"]) == 0
    assert capsys.readouterr().out.strip() == "the answer"  # plain text, not quoted


def test_ai_chat_falls_back_to_raw_on_odd_shape(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.MinderClient, "ai_chat", lambda self, m, model, tools: {"unexpected": 1}
    )
    assert cli.main(["ai", "chat", "q"]) == 0
    assert "unexpected" in capsys.readouterr().out


def test_ai_chat_passes_model_and_tools_flag(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        cli.MinderClient,
        "ai_chat",
        lambda self, m, model, tools: seen.update(m=m, model=model, tools=tools) or {},
    )
    cli.main(["ai", "chat", "hello", "--model", "qwen", "--tools"])
    assert seen == {"m": "hello", "model": "qwen", "tools": True}


def test_ai_tools_dispatch(monkeypatch):
    monkeypatch.setattr(cli.MinderClient, "ai_tools", lambda self: [{"name": "t"}])
    assert cli.main(["ai", "tools"]) == 0


def test_json_flag_switches_to_raw(monkeypatch, capsys):
    monkeypatch.setattr(cli.MinderClient, "health", lambda self: {"healthy": True})
    cli.main(["health", "--json"])
    assert capsys.readouterr().out.strip() == '{\n  "healthy": true\n}'


def test_default_output_is_human(monkeypatch, capsys):
    monkeypatch.setattr(cli.MinderClient, "health", lambda self: {"healthy": True})
    cli.main(["health"])
    assert capsys.readouterr().out.strip() == "healthy: True"


def test_plugins_config_get(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.MinderClient,
        "plugin_config",
        lambda self, name: {"schema": [], "values": {}},
    )
    assert cli.main(["plugins", "config", "crypto"]) == 0


def test_plugins_config_set_parses_pairs(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        cli.MinderClient,
        "set_plugin_config",
        lambda self, name, updates: seen.update(name=name, updates=updates) or {},
    )
    assert (
        cli.main(
            [
                "plugins",
                "config",
                "crypto",
                "--set",
                "CRYPTO_SYMBOLS=BTC-USD",
                "--set",
                "X=1",
            ]
        )
        == 0
    )
    assert seen == {
        "name": "crypto",
        "updates": {"CRYPTO_SYMBOLS": "BTC-USD", "X": "1"},
    }


def test_plugins_config_bad_set_is_an_error(monkeypatch, capsys):
    assert cli.main(["plugins", "config", "crypto", "--set", "noequals"]) == 1
    assert "KEY=VALUE" in capsys.readouterr().err


def test_parse_set_splits_on_first_equals():
    assert cli._parse_set(["A=b=c"]) == {"A": "b=c"}
    assert cli._parse_set([]) == {}
