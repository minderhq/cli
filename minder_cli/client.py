"""A thin, synchronous httpx client over the Minder api-gateway.

Every call returns parsed JSON or raises :class:`MinderError` with a friendly
message (an unreachable gateway, or the API's own ``detail`` on a 4xx/5xx). The
gateway is JWT-gated for writes; reads like ``/health`` and ``/v1/status`` are
open, so a token is optional.

Access tokens are short-lived (the gateway's ``JWT_EXPIRATION_MINUTES``), so the
client renews them via ``POST /v1/auth/refresh``: proactively when the token is
about to expire, and once on a 401. The gateway accepts a recently expired token
there (``JWT_REFRESH_GRACE_MINUTES``) until the session's absolute cap
(``JWT_SESSION_MAX_HOURS``); past that, or after a revocation, the caller is
told to run ``minder login`` again. Tokens are never printed or logged.
"""

import base64
import json
import time
from typing import Any, Callable, Optional

import httpx

# Refresh proactively when the cached token expires within this many seconds.
REFRESH_LEEWAY_SECONDS = 60

RELOGIN_HINT = "please run `minder login` again"


class MinderError(Exception):
    """A failed CLI request — carries the HTTP status when there was a response."""

    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


def _detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return f"HTTP {resp.status_code}"
    if isinstance(body, dict):
        return str(body.get("detail") or body.get("message") or body)
    return f"HTTP {resp.status_code}: {body}"


def token_expiry(token: str) -> Optional[float]:
    """The ``exp`` claim of a JWT (unverified -- only used to decide when to
    refresh; the gateway does the real verification), or None if unreadable."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except (IndexError, ValueError, UnicodeError):
        return None
    exp = claims.get("exp") if isinstance(claims, dict) else None
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        return None
    return float(exp)


class MinderClient:
    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        timeout: float = 15.0,
        on_token_refresh: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        # Called with the new token after a successful refresh (e.g. to update
        # the cached config). At most one refresh is attempted per client.
        self.on_token_refresh = on_token_refresh
        self._refresh_attempted = False
        self._refresh_error: Optional[MinderError] = None

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict] = None,
        params: Optional[dict] = None,
        auto_refresh: bool = True,
    ) -> Any:
        if auto_refresh and self._near_expiry():
            # Best effort: on failure the current token is still sent, and a
            # 401 then surfaces with the re-login hint below.
            try:
                self.refresh()
            except MinderError:
                pass
        try:
            return self._send(method, path, json_body=json_body, params=params)
        except MinderError as exc:
            if not (auto_refresh and exc.status == 401 and self.token):
                raise
            if self._refresh_attempted:
                # Already tried: report why the refresh failed when it was the
                # gateway refusing it (it carries the re-login hint).
                if self._refresh_error is not None:
                    raise self._refresh_error from exc
                raise MinderError(f"{exc}; {RELOGIN_HINT}", status=401) from exc
        self.refresh()
        return self._send(method, path, json_body=json_body, params=params)

    def _near_expiry(self) -> bool:
        if not self.token or self._refresh_attempted:
            return False
        exp = token_expiry(self.token)
        return exp is not None and exp - time.time() < REFRESH_LEEWAY_SECONDS

    def refresh(self) -> str:
        """Swap the current token for a fresh one (``POST /v1/auth/refresh``).

        A 401 from the gateway means the session can't be renewed (absolute
        session cap reached, sessions revoked, account disabled, or a token type
        that can't be refreshed) and is raised with a re-login hint."""
        self._refresh_attempted = True
        try:
            resp = self.request("POST", "/v1/auth/refresh", auto_refresh=False)
        except MinderError as exc:
            if exc.status == 401:
                self._refresh_error = MinderError(
                    f"session expired or revoked ({exc}); {RELOGIN_HINT}", status=401
                )
                raise self._refresh_error from exc
            raise
        token = resp.get("access_token") if isinstance(resp, dict) else None
        if not token:
            raise MinderError(f"refresh response had no access_token; {RELOGIN_HINT}")
        self.token = token
        if self.on_token_refresh is not None:
            self.on_token_refresh(token)
        return token

    def _send(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = httpx.request(
                method,
                url,
                headers=self._headers(),
                json=json_body,
                params=params,
                timeout=self.timeout,
            )
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise MinderError(
                f"cannot reach {self.base_url}: {type(exc).__name__}"
            ) from exc
        if resp.status_code >= 400:
            raise MinderError(_detail(resp), status=resp.status_code)
        try:
            return resp.json()
        except ValueError:
            return resp.text

    # ── convenience wrappers over the documented endpoints ────────────────────
    def login(self, username: str, password: str) -> Any:
        return self.request(
            "POST",
            "/v1/auth/login",
            json_body={"username": username, "password": password},
        )

    def health(self) -> Any:
        return self.request("GET", "/health")

    def status(self) -> Any:
        return self.request("GET", "/v1/status")

    def plugins(self) -> Any:
        return self.request("GET", "/v1/plugins")

    def plugin_config(self, name: str) -> Any:
        return self.request("GET", f"/v1/plugins/{name}/config")

    def set_plugin_config(self, name: str, updates: dict) -> Any:
        return self.request("PUT", f"/v1/plugins/{name}/config", json_body=updates)

    # ── RAG ───────────────────────────────────────────────────────────────────
    def rag_kbs(self, limit: int = 100) -> Any:
        return self.request("GET", "/v1/rag/knowledge-bases", params={"limit": limit})

    def create_kb(self, name: str, description: str) -> Any:
        return self.request(
            "POST",
            "/v1/rag/knowledge-base",
            json_body={"name": name, "description": description},
        )

    def rag_pipelines(self, limit: int = 100) -> Any:
        return self.request("GET", "/v1/rag/pipeline", params={"limit": limit})

    def rag_query(self, pipeline_id: str, question: str, top_k: int = 3) -> Any:
        return self.request(
            "POST",
            f"/v1/rag/pipeline/{pipeline_id}/query",
            json_body={"question": question, "top_k": top_k},
        )

    # ── models ────────────────────────────────────────────────────────────────
    def models_list(self, limit: int = 500) -> Any:
        return self.request("GET", "/v1/models", params={"limit": limit})

    def models_pull(self, model_id: str) -> Any:
        return self.request("POST", "/v1/models", json_body={"model_id": model_id})

    # ── billing (SaaS) ─────────────────────────────────────────────────────────
    def billing_subscription(self) -> Any:
        return self.request("GET", "/v1/billing/subscription")

    def billing_checkout(self, tier: str) -> Any:
        return self.request("POST", "/v1/billing/checkout", json_body={"tier": tier})

    def billing_portal(self) -> Any:
        return self.request("POST", "/v1/billing/portal")

    # ── organizations (multi-tenant) ──────────────────────────────────────────
    def orgs_mine(self) -> Any:
        return self.request("GET", "/v1/organizations/mine")

    def org_switch(self, organization_id: int) -> Any:
        return self.request(
            "POST",
            "/v1/organizations/switch",
            json_body={"organization_id": organization_id},
        )

    # ── knowledge graph (correlation discovery) ───────────────────────────────
    def graph_correlations(self, entity: str, limit: int = 10) -> Any:
        # graph-rag is proxied under /v1/graph-rag/* (its own /v1/graph/* would
        # collide with marketplace's dependency graph), so the entity-correlation
        # read is /v1/graph-rag/graph/correlations.
        return self.request(
            "GET",
            "/v1/graph-rag/graph/correlations",
            params={"entity": entity, "limit": limit},
        )

    # ── AI (function-calling tools + chat) ────────────────────────────────────
    def ai_tools(self) -> Any:
        return self.request("GET", "/v1/ai/functions/definitions")

    def ai_chat(
        self, message: str, model: str = "llama3.2", tools: bool = False
    ) -> Any:
        return self.request(
            "POST",
            "/v1/ai/chat/completions",
            json_body={
                "model": model,
                "messages": [{"role": "user", "content": message}],
                "minder_tools": tools,
            },
        )
