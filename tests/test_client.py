"""The CLI's HTTP client — the thing that keeps application commands going
*through* the API rather than around it.

A command that wrote to SQLite directly would bypass RBAC, policy, quota and
the audit trail. These tests pin the behaviour that makes going through the API
tolerable: the server's own error text survives, and an unreachable server says
so rather than raising a stack trace at the user.
"""

import json

import pytest

from open_refinery.client import DEFAULT_URL, ApiError, Client


class _Response:
    def __init__(self, payload, status=200):
        self._body = json.dumps(payload).encode() if payload is not None else b""
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_url_and_token_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("OPEN_REFINERY_URL", "https://refinery.example.com/")
    monkeypatch.setenv("OPEN_REFINERY_TOKEN", "tok")
    client = Client()

    assert client.url == "https://refinery.example.com"   # trailing slash trimmed
    assert client.token == "tok"


def test_explicit_arguments_beat_the_environment(monkeypatch):
    monkeypatch.setenv("OPEN_REFINERY_URL", "https://env.example.com")
    assert Client("https://flag.example.com").url == "https://flag.example.com"


def test_it_defaults_to_localhost(monkeypatch):
    monkeypatch.delenv("OPEN_REFINERY_URL", raising=False)
    assert Client().url == DEFAULT_URL


def test_the_token_is_sent_as_a_bearer_header(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["auth"] = req.get_header("Authorization")
        seen["method"] = req.get_method()
        return _Response({"ok": True})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    Client("http://x", "secret-token").get("/credentials")

    assert seen["auth"] == "Bearer secret-token"
    assert seen["method"] == "GET"


def test_no_authorization_header_when_there_is_no_token(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["auth"] = req.get_header("Authorization")
        return _Response({})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    Client("http://x", "").get("/health")
    assert seen["auth"] is None


def test_query_parameters_are_encoded(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        return _Response([])

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    Client("http://x").get("/credentials", family="model")
    assert seen["url"] == "http://x/credentials?family=model"


def test_a_body_is_sent_as_json(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["body"] = json.loads(req.data)
        seen["type"] = req.get_header("Content-type")
        return _Response({"id": "1"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    Client("http://x").post("/credentials", {"provider": "github"})

    assert seen["body"] == {"provider": "github"}
    assert seen["type"] == "application/json"


def test_an_empty_response_body_is_not_a_parse_error(monkeypatch):
    """A 204-shaped reply is normal for a delete."""
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _Response(None))
    assert Client("http://x").delete("/credentials/abc") == {}


def test_the_servers_own_message_survives(monkeypatch):
    """The server already explains itself — 'only platform may publish an
    org-wide credential'. Replacing that with a bare status code makes the
    reader go and look it up."""
    import urllib.error

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            "http://x", 403, "Forbidden", {},
            __import__("io").BytesIO(json.dumps({"detail": "only platform may publish"}).encode()))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(ApiError) as exc:
        Client("http://x").post("/credentials", {})

    assert exc.value.status == 403
    assert exc.value.detail == "only platform may publish"


def test_a_non_json_error_body_is_passed_through_rather_than_swallowed(monkeypatch):
    import io
    import urllib.error

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError("http://x", 502, "Bad Gateway", {},
                                     io.BytesIO(b"<html>nginx</html>"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(ApiError) as exc:
        Client("http://x").get("/credentials")
    assert "nginx" in exc.value.detail


def test_an_unreachable_server_says_so_and_names_the_url(monkeypatch):
    """The most common failure by far: nothing is running on :8000."""
    import urllib.error

    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(ApiError) as exc:
        Client("http://localhost:9999").get("/credentials")

    assert exc.value.status == 0
    assert "localhost:9999" in exc.value.detail
    assert "OPEN_REFINERY_URL" in exc.value.detail
