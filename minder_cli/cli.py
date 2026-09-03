"""``minder`` — the CLI entrypoint (argparse).

Commands wrap the documented api-gateway endpoints:
  minder login            # authenticate, cache a JWT
  minder health           # api-gateway /health
  minder status           # every service's health (fan-out)
  minder plugins          # list registered plugins

Global flags: --api-url, --token (override the cached/env config), --json (raw).
Output defaults to pretty JSON; a richer human view is a follow-up.
"""

import argparse
import getpass
import json
import sys
from typing import Any, List, Optional

from . import __version__, config
from .client import MinderClient, MinderError


def _client(args: argparse.Namespace) -> MinderClient:
    return MinderClient(
        config.resolve_api_url(args.api_url), token=config.resolve_token(args.token)
    )


def _emit(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


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


def cmd_plugins(args: argparse.Namespace) -> Any:
    return _client(args).plugins()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="minder", description="Minder CLI")
    parser.add_argument("--version", action="version", version=f"minder {__version__}")
    parser.add_argument(
        "--api-url", help="api-gateway base URL (default localhost:8000)"
    )
    parser.add_argument("--token", help="JWT to use (overrides cached/env)")
    parser.add_argument(
        "--json", action="store_true", help="raw JSON output (default is pretty JSON)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="authenticate and cache a token")
    p_login.add_argument("-u", "--username")
    p_login.add_argument("-p", "--password")
    p_login.set_defaults(func=cmd_login)

    sub.add_parser("health", help="api-gateway /health").set_defaults(func=cmd_health)
    sub.add_parser("status", help="every service's health").set_defaults(
        func=cmd_status
    )
    sub.add_parser("plugins", help="list registered plugins").set_defaults(
        func=cmd_plugins
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except MinderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _emit(result)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
