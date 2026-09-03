"""MinderClient: header/auth handling, endpoint wrappers, and error mapping.
httpx.request is stubbed — no network."""

import httpx
import pytest

from minder_cli.client import MinderClient, MinderError


class _Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _stub(monkeypatch, resp=None, capture=None, raise_exc=None):
    def fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        if capture is not None:
            capture.update(
                method=method, url=url, headers=headers, json=json, params=params
            )
        if raise_exc is not None:
            raise raise_exc
        return resp

    monkeypatch.setattr(httpx, "request", fake_request)


def test_auth_header_only_with_token(monkeypatch):
    cap = {}
    _stub(monkeypatch, _Resp(payload={"ok": True}), capture=cap)
    MinderClient("http://x", token="jwt").health()
    assert cap["headers"]["Authorization"] == "Bearer jwt"
    _stub(monkeypatch, _Resp(payload={"ok": True}), capture=cap)
    MinderClient("http://x").health()
    assert "Authorization" not in cap["headers"]


def test_endpoints_build_the_right_request(monkeypatch):
    cap = {}
    _stub(monkeypatch, _Resp(payload={}), capture=cap)
    MinderClient("http://x/").status()
    assert cap["url"] == "http://x/v1/status" and cap["method"] == "GET"

    _stub(monkeypatch, _Resp(payload={}), capture=cap)
    MinderClient("http://x").login("u", "p")
    assert cap["url"] == "http://x/v1/auth/login" and cap["method"] == "POST"
    assert cap["json"] == {"username": "u", "password": "p"}


def test_4xx_raises_with_api_detail(monkeypatch):
    _stub(monkeypatch, _Resp(status_code=401, payload={"detail": "Not authenticated"}))
    with pytest.raises(MinderError) as ei:
        MinderClient("http://x").plugins()
    assert ei.value.status == 401 and "Not authenticated" in str(ei.value)


def test_unreachable_is_friendly(monkeypatch):
    _stub(monkeypatch, raise_exc=httpx.ConnectError("nope"))
    with pytest.raises(MinderError, match="cannot reach"):
        MinderClient("http://x").health()


def test_non_json_body_returns_text(monkeypatch):
    _stub(monkeypatch, _Resp(payload=None, text="pong"))
    assert MinderClient("http://x").health() == "pong"


def test_rag_endpoints_build_correctly(monkeypatch):
    cap = {}
    _stub(monkeypatch, _Resp(payload={}), capture=cap)
    MinderClient("http://x").rag_kbs(limit=50)
    assert cap["url"] == "http://x/v1/rag/knowledge-bases" and cap["params"] == {
        "limit": 50
    }

    _stub(monkeypatch, _Resp(payload={}), capture=cap)
    MinderClient("http://x").create_kb("Docs", "my docs")
    assert cap["url"] == "http://x/v1/rag/knowledge-base"
    assert cap["json"] == {"name": "Docs", "description": "my docs"}

    _stub(monkeypatch, _Resp(payload={}), capture=cap)
    MinderClient("http://x").rag_query("pid", "what?", top_k=5)
    assert cap["url"] == "http://x/v1/rag/pipeline/pid/query"
    assert cap["json"] == {"question": "what?", "top_k": 5}


def test_models_endpoints_build_correctly(monkeypatch):
    cap = {}
    _stub(monkeypatch, _Resp(payload={}), capture=cap)
    MinderClient("http://x").models_list()
    assert cap["url"] == "http://x/v1/models" and cap["method"] == "GET"

    _stub(monkeypatch, _Resp(payload={}), capture=cap)
    MinderClient("http://x").models_pull("llama3.2:latest")
    assert cap["method"] == "POST" and cap["json"] == {"model_id": "llama3.2:latest"}
