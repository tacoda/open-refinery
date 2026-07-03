# Dev workflow — always use make tasks

For local development, always drive the app through the `make` tasks, never raw
`uv run open-refinery serve ...` with ad-hoc env or paths. `make` runs from the
repo root, so the dev database resolves consistently — running the server by
hand from another directory (e.g. `frontend/`) silently creates a *new empty*
SQLite file and logins fail.

- `make dev` — run the server with a fixed dev `SECRET_KEY` and an **absolute**
  path to `devtest.db` on port 8000. Background it yourself: `make dev &`.
- `make seed` — seed `devtest.db` with sample data + login tokens.
- `make ui` / `make ui-dev` — build / dev-serve the dashboard.
- `make test` — run the suite. `make dist` — build UI + wheel.

After changing backend code, **restart** `make dev` — a running server holds the
old routes in memory (static files are served fresh from disk, Python code is
not).

`make` is **dev-only**. End users never need it: they `pip install open-refinery`
and run `open-refinery serve`.
