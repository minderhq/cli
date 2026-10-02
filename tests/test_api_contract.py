"""API contract: every (method, path) the CLI calls must exist in the API
Gateway's published OpenAPI spec, so a call to a route the gateway doesn't
serve fails CI instead of 404ing for a user.

The spec is the copy published on the docs site. In CI, ``MINDER_OPENAPI_URL``
is set to its raw URL and the spec is fetched at test time (a failed fetch
fails the test -- CI must check the live contract). Without it (local/offline
runs) the committed fallback ``tests/fixtures/openapi/api-gateway.json`` is
used; refresh it with the command in README "API contract".

Calls are collected statically: every ``<x>.request("METHOD", "/path")`` in
``minder_cli`` (f-string fields become path params). A ``request`` call whose
method/path isn't a literal fails, so nothing slips past the check.

Note: a gateway catch-all proxy (``/v1/rag/{path}``, ...) only proves the
prefix is routed, not that the upstream service has the rest of the path.
"""

import ast
import json
import os
import warnings
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
FALLBACK_SPEC = ROOT / "tests" / "fixtures" / "openapi" / "api-gateway.json"
HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
PARAM = "{}"

# Calls known to be missing from the spec: "METHOD /path" -> reason. A stale
# entry (the call now resolves, or is gone) fails, so delete it once fixed.
KNOWN_MISSING: dict = {}


def load_spec() -> dict:
    url = os.environ.get("MINDER_OPENAPI_URL")
    if not url:
        return json.loads(FALLBACK_SPEC.read_text(encoding="utf-8"))
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    spec = resp.json()
    if spec != json.loads(FALLBACK_SPEC.read_text(encoding="utf-8")):
        warnings.warn(
            f"{FALLBACK_SPEC.relative_to(ROOT)} is stale vs {url}; refresh it "
            "(README 'API contract')",
            stacklevel=1,
        )
    return spec


def spec_routes(spec: dict) -> list:
    routes = []
    for path, item in spec["paths"].items():
        segments = path.split("/")[1:]
        methods = {m.upper() for m in item if m in HTTP_METHODS}
        # FastAPI's {path:path} catch-all is published as a trailing {path}.
        routes.append((segments, segments[-1] == "{path}", methods))
    return routes


def check_call(routes: list, method: str, path: str):
    """None when ``method path`` is served by the spec, else the reason."""
    client = path.split("?")[0].split("/")[1:]
    hits = []
    for segments, catch_all, methods in routes:
        n = len(segments)
        if len(client) < n if catch_all else len(client) != n:
            continue
        if all(
            (s.startswith("{") and c != "") or s == c for s, c in zip(segments, client)
        ):
            hits.append(methods)
    if not hits:
        return "no such path in the gateway spec"
    if not any(method in m for m in hits):
        return (
            f"method not served (spec allows {', '.join(sorted(set().union(*hits)))})"
        )
    return None


def _path_text(node: ast.expr):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            else:
                parts.append(PARAM)
        text = "".join(parts)
        return "/".join(PARAM if PARAM in s else s for s in text.split("/"))
    return None


def collect_calls(source: str, filename: str) -> list:
    """(method, path, location) per ``<x>.request(...)`` call; method/path
    ``None`` when not a literal. ``httpx.request`` (the transport) is skipped."""
    calls = []
    for node in ast.walk(ast.parse(source, filename)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "request"
            and not (
                isinstance(node.func.value, ast.Name) and node.func.value.id == "httpx"
            )
        ):
            continue
        method = path = None
        if len(node.args) >= 2:
            m = node.args[0]
            if isinstance(m, ast.Constant) and isinstance(m.value, str):
                method = m.value.upper()
            path = _path_text(node.args[1])
        calls.append((method, path, f"{filename}:{node.lineno}"))
    return calls


def cli_calls() -> list:
    calls = []
    for py in sorted((ROOT / "minder_cli").rglob("*.py")):
        rel = py.relative_to(ROOT).as_posix()
        calls += collect_calls(py.read_text(encoding="utf-8"), rel)
    return calls


@pytest.fixture(scope="module")
def routes():
    return spec_routes(load_spec())


def test_collects_the_cli_calls():
    calls = cli_calls()
    assert len(calls) >= 15
    assert ("POST", "/v1/auth/login") in {(m, p) for m, p, _ in calls}
    assert ("GET", "/v1/plugins/{}/config") in {(m, p) for m, p, _ in calls}


def test_every_cli_call_exists_in_the_gateway_spec(routes):
    missing = {}
    for method, path, where in cli_calls():
        if method is None or path is None:
            missing.setdefault(f"<non-literal> {where}", []).append(
                "make the method/path a literal so it can be checked"
            )
            continue
        why = check_call(routes, method, path)
        if why:
            missing.setdefault(f"{method} {path}", []).append(f"{where} ({why})")
    unexpected = {k: v for k, v in missing.items() if k not in KNOWN_MISSING}
    assert not unexpected, (
        "the CLI calls routes the gateway doesn't serve (fix the call, or "
        f"refresh the spec if the gateway changed): {unexpected}"
    )
    stale = sorted(set(KNOWN_MISSING) - set(missing))
    assert not stale, f"KNOWN_MISSING entries that now resolve, delete them: {stale}"


_TOY = spec_routes(
    {
        "paths": {
            "/v1/teams/{team_id}": {"get": {}, "patch": {}},
            "/v1/rag/{path}": {"get": {}, "post": {}},
            "/v1/organizations/mine": {"get": {}},
        }
    }
)


@pytest.mark.parametrize(
    "method,path,expected",
    [
        ("GET", "/v1/teams/{}", None),
        ("POST", "/v1/rag/pipeline/{}/query", None),
        ("GET", "/v1/organizations/mine?x=1", None),
        ("GET", "/v1/rag", "no such path"),
        ("GET", "/v1/nope", "no such path"),
        ("DELETE", "/v1/teams/{}", "GET, PATCH"),
        ("GET", "/v1/organizations/{}", "no such path"),
    ],
)
def test_matcher(method, path, expected):
    got = check_call(_TOY, method, path)
    assert got is None if expected is None else expected in got


def test_collector_handles_fstrings_and_non_literals():
    src = (
        "def f(self, n, p):\n"
        "    self.request('get', f'/v1/plugins/{n}/config')\n"
        "    self.request('POST', p)\n"
        "    httpx.request(method, url)\n"
    )
    assert collect_calls(src, "x.py") == [
        ("GET", "/v1/plugins/{}/config", "x.py:2"),
        ("POST", None, "x.py:3"),
    ]
