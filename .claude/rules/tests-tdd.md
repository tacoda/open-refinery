# Tests

- Non-trivial logic lands with a test.
- Prove a bug with a failing test before fixing it.
- The production loop's ordering (authorize before run; record/log only after
  success) is behavior — keep it covered.
- Run `uv run pytest`; all green before a commit or PR.
