"""A tiny HTTP client, so CLI commands go through the API rather than around it.

The CLI is a peer surface to the web app, not a second implementation. Anything
a *person* does — connect a credential, trigger a run, move a rung — goes over
HTTP to the server, because the backend is the governance boundary: RBAC, policy
enforcement, quota, content filtering and the audit trail all live on that side.
A command that wrote to SQLite directly would bypass every one of them, which is
the kind of quiet side door this product exists not to have.

Server *maintenance* is the exception and stays on the database — `init`,
`migrate`, `serve`, `doctor`, `config`, `create-admin`, `seed` — because they run
on the box, often before there is a server to talk to.

Stdlib only, per the working rules.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "http://localhost:8000"


class ApiError(RuntimeError):
    """A non-2xx response, carrying the server's own message.

    The server already explains itself — "only platform may publish an org-wide
    credential" — so the client repeats that rather than replacing it with a
    status code the reader then has to look up.
    """

    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail
        super().__init__(f"{status}: {detail}")


class Client:
    def __init__(self, url: str | None = None, token: str | None = None):
        self.url = (url or os.environ.get("OPEN_REFINERY_URL") or DEFAULT_URL).rstrip("/")
        self.token = token or os.environ.get("OPEN_REFINERY_TOKEN") or ""

    def request(self, method: str, path: str, body: dict | None = None,
                params: dict | None = None):
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(self.url + path + query, data=data,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                text = r.read().decode("utf-8", "replace")
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(raw).get("detail", raw)
            except ValueError:
                detail = raw
            raise ApiError(exc.code, str(detail)) from None
        except urllib.error.URLError as exc:
            raise ApiError(0, f"cannot reach {self.url}: {exc.reason}. "
                              "Is the server running? Set OPEN_REFINERY_URL to point elsewhere.") from None

    def get(self, path, **params):
        return self.request("GET", path, params=params or None)

    def post(self, path, body=None):
        return self.request("POST", path, body=body if body is not None else {})

    def put(self, path, body):
        return self.request("PUT", path, body=body)

    def delete(self, path):
        return self.request("DELETE", path)
