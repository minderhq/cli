"""A thin, synchronous httpx client over the Minder api-gateway.

Every call returns parsed JSON or raises :class:`MinderError` with a friendly
message (an unreachable gateway, or the API's own ``detail`` on a 4xx/5xx). The
gateway is JWT-gated for writes; reads like ``/health`` and ``/v1/status`` are
open, so a token is optional.
"""

from typing import Any, Optional

import httpx


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


class MinderClient:
    def __init__(
        self, base_url: str, token: Optional[str] = None, timeout: float = 15.0
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def request(
        self, method: str, path: str, *, json_body: Optional[dict] = None
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = httpx.request(
                method,
                url,
                headers=self._headers(),
                json=json_body,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
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
