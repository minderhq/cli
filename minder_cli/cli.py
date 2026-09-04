"""``minder`` — the CLI entrypoint (argparse).

Commands wrap the documented api-gateway endpoints:
  minder login            # authenticate, cache a JWT
  minder health           # api-gateway /health
  minder status           # every service's health (fan-out)
  minder plugins          # list registered plugins

Global flags go AFTER the subcommand (git/docker style): --api-url, --token
(override the cached/env config), --json (raw JSON instead of the human view).
"""

import argparse
import getpass
import sys
from typing import Any, List, Optional

from . import __version__, config, output
from .client import MinderClient, MinderError


def _client(args: argparse.Namespace) -> MinderClient:
    return MinderClient(
        config.resolve_api_url(args.api_url), token=config.resolve_token(args.token)
    )


def _emit(data: Any, as_json: bool = False) -> None:
    print(output.render(data, as_json))


def cmd_login(args: argparse.Namespace) -> Any:
    username = args.username or input("Username: ")
    password = args.password or getpass.getpass("Password: ")
    api_url = config.resolve_api_url(args.api_url)
    resp = MinderClient(api_url).login(username, password)
    token = resp.get("access_token") if isinstance(resp, dict) else None
    if not token:
        raise MinderError("login response had no access_token")
    config.save_token(token, api_url)
    return {"status": "logged in", "api_url": api_url}


def cmd_health(args: argparse.Namespace) -> Any:
    return _client(args).health()


def cmd_status(args: argparse.Namespace) -> Any:
    return _client(args).status()


def cmd_plugins_list(args: argparse.Namespace) -> Any:
    return _client(args).plugins()


def _parse_set(pairs: List[str]) -> dict:
    updates = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise MinderError(f"--set expects KEY=VALUE, got {pair!r}")
        key, value = pair.split("=", 1)
        updates[key] = value
    return updates


def cmd_plugins_config(args: argparse.Namespace) -> Any:
    client = _client(args)
    updates = _parse_set(args.set)
    if updates:
        return client.set_plugin_config(args.name, updates)
    return client.plugin_config(args.name)


def cmd_rag_kbs(args: argparse.Namespace) -> Any:
    return _client(args).rag_kbs(limit=args.limit)


def cmd_rag_create_kb(args: argparse.Namespace) -> Any:
    return _client(args).create_kb(args.name, args.description)


def cmd_rag_pipelines(args: argparse.Namespace) -> Any:
    return _client(args).rag_pipelines(limit=args.limit)


def cmd_rag_query(args: argparse.Namespace) -> Any:
    return _client(args).rag_query(args.pipeline_id, args.question, top_k=args.top_k)


def cmd_models_list(args: argparse.Namespace) -> Any:
    return _client(args).models_list()


def cmd_models_pull(args: argparse.Namespace) -> Any:
    return _client(args).models_pull(args.model_id)


def _assistant_reply(resp: Any) -> Any:
    """Pull the assistant text out of an OpenAI-shaped chat response; fall back to
    the raw payload if the shape is unexpected (so nothing is silently swallowed)."""
    try:
        return resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return resp


def cmd_billing_subscription(args: argparse.Namespace) -> Any:
    return _client(args).billing_subscription()


def cmd_billing_checkout(args: argparse.Namespace) -> Any:
    return _client(args).billing_checkout(args.tier)


def cmd_billing_portal(args: argparse.Namespace) -> Any:
    return _client(args).billing_portal()


def cmd_org_list(args: argparse.Namespace) -> Any:
    return _client(args).orgs_mine()


def cmd_org_switch(args: argparse.Namespace) -> Any:
    # Switching re-mints the JWT with the new active_tenant_id -- persist it so the
    # NEXT command acts in the switched org (mirrors how `login` caches its token).
    resp = _client(args).org_switch(args.organization_id)
    token = resp.get("access_token") if isinstance(resp, dict) else None
    if token:
        config.save_token(token, config.resolve_api_url(args.api_url))
    return resp


def cmd_graph_correlations(args: argparse.Namespace) -> Any:
    return _client(args).graph_correlations(args.entity, limit=args.limit)


def cmd_ai_tools(args: argparse.Namespace) -> Any:
    return _client(args).ai_tools()


def cmd_ai_chat(args: argparse.Namespace) -> Any:
    resp = _client(args).ai_chat(args.message, model=args.model, tools=args.tools)
    return _assistant_reply(resp)


def _common() -> argparse.ArgumentParser:
    # Global flags live on a parent parser applied to every leaf command, so they
    # go AFTER the subcommand (the git/docker convention): `minder health --json`,
    # `minder plugins config x --api-url URL`. Putting them only on the leaves
    # (not the top parser) sidesteps argparse's subparser-default-overwrite gotcha.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api-url", default=None, help="api-gateway base URL")
    common.add_argument("--token", default=None, help="JWT (overrides cached/env)")
    common.add_argument(
        "--json",
        action="store_true",
        help="raw JSON output (default is a human view)",
    )
    return common


def build_parser() -> argparse.ArgumentParser:
    common = _common()
    parser = argparse.ArgumentParser(prog="minder", description="Minder CLI")
    parser.add_argument("--version", action="version", version=f"minder {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", parents=[common], help="authenticate + cache")
    p_login.add_argument("-u", "--username")
    p_login.add_argument("-p", "--password")
    p_login.set_defaults(func=cmd_login)

    sub.add_parser("health", parents=[common], help="api-gateway /health").set_defaults(
        func=cmd_health
    )
    sub.add_parser(
        "status", parents=[common], help="every service's health"
    ).set_defaults(func=cmd_status)

    p_plugins = sub.add_parser("plugins", help="list + configure plugins")
    plugins_sub = p_plugins.add_subparsers(dest="plugins_command", required=True)
    plugins_sub.add_parser(
        "list", parents=[common], help="list registered plugins"
    ).set_defaults(func=cmd_plugins_list)
    p_cfg = plugins_sub.add_parser(
        "config",
        parents=[common],
        help="show a plugin's config, or --set KEY=VALUE to update it",
    )
    p_cfg.add_argument("name")
    p_cfg.add_argument(
        "--set",
        action="append",
        metavar="KEY=VALUE",
        help="update a config key (repeatable)",
    )
    p_cfg.set_defaults(func=cmd_plugins_config)

    # ── rag <kbs|create-kb|pipelines|query> ───────────────────────────────────
    p_rag = sub.add_parser("rag", help="knowledge bases, pipelines, and queries")
    rag_sub = p_rag.add_subparsers(dest="rag_command", required=True)
    r_kbs = rag_sub.add_parser("kbs", parents=[common], help="list knowledge bases")
    r_kbs.add_argument("--limit", type=int, default=100)
    r_kbs.set_defaults(func=cmd_rag_kbs)
    r_new = rag_sub.add_parser(
        "create-kb", parents=[common], help="create a knowledge base"
    )
    r_new.add_argument("name")
    r_new.add_argument(
        "description",
        nargs="?",
        default="",
        help="optional (the API allows an empty one)",
    )
    r_new.set_defaults(func=cmd_rag_create_kb)
    r_pipes = rag_sub.add_parser("pipelines", parents=[common], help="list pipelines")
    r_pipes.add_argument("--limit", type=int, default=100)
    r_pipes.set_defaults(func=cmd_rag_pipelines)
    r_q = rag_sub.add_parser("query", parents=[common], help="ask a pipeline")
    r_q.add_argument("pipeline_id")
    r_q.add_argument("question")
    r_q.add_argument("--top-k", dest="top_k", type=int, default=3)
    r_q.set_defaults(func=cmd_rag_query)

    # ── models <list|pull> ────────────────────────────────────────────────────
    p_models = sub.add_parser("models", help="Ollama model management")
    models_sub = p_models.add_subparsers(dest="models_command", required=True)
    models_sub.add_parser("list", parents=[common], help="list models").set_defaults(
        func=cmd_models_list
    )
    m_pull = models_sub.add_parser(
        "pull", parents=[common], help="pull a model (admin)"
    )
    m_pull.add_argument("model_id", help="e.g. llama3.2:latest")
    m_pull.set_defaults(func=cmd_models_pull)

    # ── ai <tools|chat> ───────────────────────────────────────────────────────
    p_ai = sub.add_parser("ai", help="function-calling tools + chat")
    ai_sub = p_ai.add_subparsers(dest="ai_command", required=True)
    ai_sub.add_parser(
        "tools", parents=[common], help="list the LLM's callable tools"
    ).set_defaults(func=cmd_ai_tools)
    a_chat = ai_sub.add_parser("chat", parents=[common], help="one-shot chat (JWT)")
    a_chat.add_argument("message")
    a_chat.add_argument("--model", default="llama3.2")
    a_chat.add_argument(
        "--tools", action="store_true", help="enable the multi-turn tool loop"
    )
    a_chat.set_defaults(func=cmd_ai_chat)

    # ── billing <subscription|checkout|portal> ────────────────────────────────
    p_billing = sub.add_parser("billing", help="subscription, checkout, portal (SaaS)")
    billing_sub = p_billing.add_subparsers(dest="billing_command", required=True)
    billing_sub.add_parser(
        "subscription", parents=[common], help="show the org's current plan"
    ).set_defaults(func=cmd_billing_subscription)
    b_checkout = billing_sub.add_parser(
        "checkout", parents=[common], help="start a hosted checkout for a tier"
    )
    b_checkout.add_argument("tier", help="e.g. pro, enterprise")
    b_checkout.set_defaults(func=cmd_billing_checkout)
    billing_sub.add_parser(
        "portal", parents=[common], help="get the customer-portal URL"
    ).set_defaults(func=cmd_billing_portal)

    # ── org <list|switch> ─────────────────────────────────────────────────────
    p_org = sub.add_parser("org", help="your organizations (multi-tenant)")
    org_sub = p_org.add_subparsers(dest="org_command", required=True)
    org_sub.add_parser(
        "list", parents=[common], help="list the orgs you belong to"
    ).set_defaults(func=cmd_org_list)
    o_switch = org_sub.add_parser(
        "switch",
        parents=[common],
        help="switch active org (re-mints + caches your JWT)",
    )
    o_switch.add_argument("organization_id", type=int)
    o_switch.set_defaults(func=cmd_org_switch)

    # ── graph <correlations> ──────────────────────────────────────────────────
    p_graph = sub.add_parser("graph", help="knowledge-graph correlation discovery")
    graph_sub = p_graph.add_subparsers(dest="graph_command", required=True)
    g_corr = graph_sub.add_parser(
        "correlations",
        parents=[common],
        help="an entity's correlated entities/signals",
    )
    g_corr.add_argument("entity")
    g_corr.add_argument("--limit", type=int, default=10)
    g_corr.set_defaults(func=cmd_graph_correlations)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    # Emit UTF-8 regardless of the terminal's codepage. Windows consoles default
    # to a legacy codepage (e.g. cp1254), which mangles non-ASCII output — plugin
    # names/descriptions, bullets, em-dashes — into "?"/replacement chars or, on a
    # strict stream, raises. errors="replace" never crashes. Guarded because a
    # captured/redirected stream (pytest capsys, a pipe) may not be reconfigurable.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except MinderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _emit(result, as_json=args.json)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
