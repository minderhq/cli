"""Transparent token refresh (#28): proactive near ``exp``, once on a 401, the
refreshed token cached back to the config file, and a clear re-login message
when the gateway refuses to refresh. httpx.request is stubbed — no network."""

import base64
import json
import os
import stat
import sys
import time

import httpx
import pytest

from minder_cli import cli, config
from minder_cli.client import MinderClient, MinderError, token_expiry


def _jwt(exp=None, **claims):
    """An unsigned JWT-shaped token (the CLI never verifies signatures)."""
    if exp is not None:
        claims["exp"] = exp

    def seg(obj):
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{seg({'alg': 'HS256'})}.{seg(claims)}.sig"


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeGateway:
    """Routes stubbed requests: /v1/auth/refresh returns ``refresh``; any other
    path answers 200 only for a token in ``valid``, else 401."""

    def __init__(self, valid, refresh):
        self.valid = set(valid)
        self.refresh = refresh
        self.calls = []

    def __call__(self, method, url, headers=None, json=None, params=None, **_):
        auth = (headers or {}).get("Authorization", "")
        token = auth[len("Bearer ") :] if auth.startswith("Bearer ") else None
        path = url.split("://", 1)[1].split("/", 1)[1]
        self.calls.append((method, "/" + path, token))
        if path == "v1/auth/refresh":
            if isinstance(self.refresh, Exception):
                raise self.refresh
            return self.refresh
        if token in self.valid:
            return _Resp(payload={"ok": True})
        return _Resp(401, {"detail": "Token has expired"})

    def paths(self):
        return [p for _, p, _ in self.calls]


@pytest.fixture
def gateway(monkeypatch):
    def install(valid, refresh):
        gw = FakeGateway(valid, refresh)
        monkeypatch.setattr(httpx, "request", gw)
        return gw

    return install


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("MINDER_API_URL", raising=False)
    monkeypatch.delenv("MINDER_TOKEN", raising=False)


def test_token_expiry_reads_exp_and_tolerates_garbage():
    assert token_expiry(_jwt(exp=1234)) == 1234.0
    assert token_expiry(_jwt()) is None
    assert token_expiry(_jwt(exp="soon")) is None
    assert token_expiry("not-a-jwt") is None
    assert token_expiry("a.!!!.c") is None


def test_401_refreshes_once_and_retries(gateway):
    new = _jwt(exp=time.time() + 900, sub="1")
    gw = gateway(valid={new}, refresh=_Resp(payload={"access_token": new}))
    seen = []
    client = MinderClient("http://x", token="opaque-old", on_token_refresh=seen.append)
    assert client.plugins() == {"ok": True}
    assert gw.paths() == ["/v1/plugins", "/v1/auth/refresh", "/v1/plugins"]
    assert gw.calls[1][2] == "opaque-old"  # refresh presents the old token
    assert client.token == new and seen == [new]


def test_near_expiry_refreshes_before_the_request(gateway):
    old = _jwt(exp=time.time() + 10, sub="1")
    new = _jwt(exp=time.time() + 900, sub="1")
    gw = gateway(valid={old, new}, refresh=_Resp(payload={"access_token": new}))
    client = MinderClient("http://x", token=old)
    client.status()
    assert gw.paths() == ["/v1/auth/refresh", "/v1/status"]
    assert gw.calls[-1][2] == new


def test_expired_token_within_grace_is_refreshed(gateway):
    # e.g. a command run 20 minutes after login with a 15-minute token
    old = _jwt(exp=time.time() - 5 * 60, sub="1")
    new = _jwt(exp=time.time() + 900, sub="1")
    gw = gateway(valid={new}, refresh=_Resp(payload={"access_token": new}))
    assert MinderClient("http://x", token=old).plugins() == {"ok": True}
    assert gw.paths() == ["/v1/auth/refresh", "/v1/plugins"]


def test_fresh_token_is_not_refreshed(gateway):
    tok = _jwt(exp=time.time() + 900, sub="1")
    gw = gateway(valid={tok}, refresh=_Resp(500, {"detail": "unexpected"}))
    MinderClient("http://x", token=tok).plugins()
    assert gw.paths() == ["/v1/plugins"]


def test_no_token_means_no_refresh(gateway):
    gw = gateway(valid=set(), refresh=_Resp(500, {"detail": "unexpected"}))
    with pytest.raises(MinderError) as ei:
        MinderClient("http://x").plugins()
    assert ei.value.status == 401 and "minder login" not in str(ei.value)
    assert gw.paths() == ["/v1/plugins"]


@pytest.mark.parametrize(
    "detail",
    [
        "Session has expired -- sign in again",
        "Session revoked by a password reset -- sign in again",
        "Account is disabled or no longer exists",
        "This token can't be refreshed -- sign in again",
    ],
)
def test_refused_refresh_asks_to_log_in_again(gateway, detail):
    old = _jwt(exp=time.time() - 60, sub="1")
    gw = gateway(valid=set(), refresh=_Resp(401, {"detail": detail}))
    with pytest.raises(MinderError) as ei:
        MinderClient("http://x", token=old).plugins()
    msg = str(ei.value)
    assert ei.value.status == 401
    assert "minder login" in msg and detail in msg
    assert old not in msg
    # one refresh attempt, never a loop
    assert gw.paths().count("/v1/auth/refresh") == 1


def test_refused_refresh_on_401_path_asks_to_log_in_again(gateway):
    gw = gateway(valid=set(), refresh=_Resp(401, {"detail": "Session has expired"}))
    with pytest.raises(MinderError, match="minder login"):
        MinderClient("http://x", token="opaque").plugins()
    assert gw.paths() == ["/v1/plugins", "/v1/auth/refresh"]


def test_refresh_transport_error_surfaces_on_401_path(gateway):
    gateway(valid=set(), refresh=httpx.ConnectError("nope"))
    with pytest.raises(MinderError, match="cannot reach"):
        MinderClient("http://x", token="opaque").plugins()


def test_refresh_without_access_token_is_an_error(gateway):
    gateway(valid=set(), refresh=_Resp(payload={"nope": 1}))
    with pytest.raises(MinderError, match="no access_token"):
        MinderClient("http://x", token="opaque").plugins()


def test_retry_after_refresh_is_not_repeated(gateway):
    new = _jwt(exp=time.time() + 900, sub="1")
    # the refreshed token is still refused (e.g. revoked in between)
    gw = gateway(valid=set(), refresh=_Resp(payload={"access_token": new}))
    with pytest.raises(MinderError) as ei:
        MinderClient("http://x", token="opaque").plugins()
    assert ei.value.status == 401
    assert gw.paths() == ["/v1/plugins", "/v1/auth/refresh", "/v1/plugins"]


# ── CLI: the refreshed token is written back to the cache ────────────────────
def test_cli_persists_refreshed_token(gateway, capsys):
    old = _jwt(exp=time.time() - 20 * 60, sub="1")
    new = _jwt(exp=time.time() + 900, sub="1")
    config.save_token(old, api_url="http://gw:8000")
    gateway(valid={new}, refresh=_Resp(payload={"access_token": new}))
    assert cli.main(["plugins", "list"]) == 0
    data = json.loads(config.config_path().read_text(encoding="utf-8"))
    assert data == {"token": new, "api_url": "http://gw:8000"}
    out = capsys.readouterr()
    assert old not in out.out + out.err and new not in out.out + out.err


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_cli_keeps_cache_file_permissions(gateway):
    old = _jwt(exp=time.time() - 60, sub="1")
    new = _jwt(exp=time.time() + 900, sub="1")
    config.save_token(old, api_url="http://gw:8000")
    os.chmod(config.config_path(), 0o600)
    gateway(valid={new}, refresh=_Resp(payload={"access_token": new}))
    assert cli.main(["health"]) == 0
    assert stat.S_IMODE(os.stat(config.config_path()).st_mode) == 0o600
    assert config.resolve_token() == new


def test_cli_cache_write_failure_is_only_a_warning(gateway, monkeypatch, capsys):
    old = _jwt(exp=time.time() - 60, sub="1")
    new = _jwt(exp=time.time() + 900, sub="1")
    config.save_token(old, api_url="http://gw:8000")
    gateway(valid={new}, refresh=_Resp(payload={"access_token": new}))

    def readonly(token, api_url=None):
        raise PermissionError("read-only")

    monkeypatch.setattr(config, "save_token", readonly)
    assert cli.main(["health"]) == 0
    err = capsys.readouterr().err
    assert "could not cache the refreshed token" in err and new not in err


@pytest.mark.parametrize("source", ["flag", "env"])
def test_cli_does_not_cache_an_override_token(gateway, monkeypatch, source):
    cached = _jwt(exp=time.time() + 900, sub="1")
    override = _jwt(exp=time.time() - 60, sub="2")
    new = _jwt(exp=time.time() + 900, sub="2")
    config.save_token(cached, api_url="http://gw:8000")
    gw = gateway(valid={new}, refresh=_Resp(payload={"access_token": new}))
    argv = ["health"]
    if source == "flag":
        argv += ["--token", override]
    else:
        monkeypatch.setenv("MINDER_TOKEN", override)
    assert cli.main(argv) == 0
    assert gw.calls[-1][2] == new
    stored = json.loads(config.config_path().read_text(encoding="utf-8"))
    assert stored["token"] == cached


def test_cli_session_cap_prints_relogin_message(gateway, capsys):
    old = _jwt(exp=time.time() - 60, sub="1")
    config.save_token(old, api_url="http://gw:8000")
    gateway(
        valid=set(),
        refresh=_Resp(401, {"detail": "Session has expired -- sign in again"}),
    )
    assert cli.main(["plugins", "list"]) == 1
    err = capsys.readouterr().err
    assert "please run `minder login` again" in err
    assert old not in err
    assert config.resolve_token() == old  # cache untouched on failure
