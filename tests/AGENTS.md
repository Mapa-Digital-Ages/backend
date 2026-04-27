# AGENTS.md — `tests/`

Scope: every file under `tests/`. These rules apply to any agent editing test code.

## Layout

- `tests/conftest.py` — pytest setup, env vars, async engine disposal.
- `tests/keys_test.py` — default environment values for tests.
- `tests/helpers.py` — shared fixtures and helpers for routes/services tests.
- `tests/routes/` — HTTP-level tests using FastAPI's test client.
- `tests/services/` — direct unit tests for business logic in `src/md_backend/services/`.
- `tests/models/` — tests for Pydantic and ORM models.
- `tests/utils/` — tests for helpers in `src/md_backend/utils/`.
- `tests/test_main.py` — application bootstrap tests.

## General conventions

- Python 3.12, `pytest` + `pytest-asyncio` style. Use `httpx.AsyncClient` for route tests.
- Test files are named `test_*.py`, test functions `test_*`, test classes `Test*`.
- Reuse fixtures from `helpers.py` and `conftest.py`; do not redefine equivalent fixtures locally.
- Each test must be independent: no shared mutable state between tests, no ordering assumptions.
- Use the in-memory / aiosqlite test database wired by `conftest.py`. Never hit a real Postgres or external service.
- Mock outbound side effects (HTTP, email, time, randomness) with `unittest.mock`. Do not introduce new heavyweight test deps.
- Style is enforced by Ruff (`pyproject.toml`). Per-file ignores already disable docstring requirements for tests; do not add docstrings just to satisfy linters.
- Assertions should be specific: assert status code AND payload shape, not just one.

## Running tests and coverage

The canonical validation command pair (must be used to certify 100% coverage):

```bash
uv run coverage run -m unittest discover -s .
uv run coverage report
```

The `coverage report` output **must show 100%** on the `TOTAL` row. Any value below 100% means the task is not done.

Coverage scope is `src/md_backend` (production code only). Test files are excluded from coverage measurement.

---

## Trigger: "implement code coverage"

When the user message contains the phrase **"implement code coverage"** (case-insensitive, any language), follow this workflow exactly. This is a hard contract.

### Hard rules

1. **Do not modify any file under `src/`.** Not a single character. No reformatting, no docstring tweaks, no import reordering, no "drive-by" fixes. If `src/` looks broken, stop and report it — never edit.
2. **Only write or edit files under `tests/`.** New fixtures, new test modules, new helpers, parametrizations, mocks — all of it goes in `tests/`.
3. **Target: 100% coverage of `src/md_backend`**, certified by running:
   ```bash
   uv run coverage run -m unittest discover -s .
   uv run coverage report
   ```
   The `TOTAL` line of `coverage report` **must read 100%**. Anything less is a failure — the task is not complete and must not be reported as done. No `# pragma: no cover` additions, no edits to `pyproject.toml` / coverage config to exclude lines, no skipped tests.
4. **Do not weaken existing tests.** Adding new tests must not delete or relax existing assertions.
5. **No network, no real DB, no real filesystem writes outside `tmp_path`.** Use mocks, fakes, and the existing aiosqlite setup.

### Workflow

1. Run the canonical baseline:
   ```bash
   uv run coverage run -m unittest discover -s .
   uv run coverage report
   ```
   Capture the missing lines per file (use `uv run coverage report -m` for detail).
2. List every file in `src/md_backend` with missing lines/branches.
3. For each gap, decide the appropriate level:
   - Pure logic / branching → unit test in `tests/services/`, `tests/models/`, or `tests/utils/`.
   - HTTP behavior, status codes, validation errors → route test in `tests/routes/`.
   - Error handling that requires a failing dependency → mock the dependency at the seam.
4. Add the tests. Prefer parametrization / table-driven tests over copy-pasted test bodies. Tests must be discoverable by `unittest discover` (subclass `unittest.TestCase` or be importable async tests already wired through `conftest.py`).
5. Re-run the canonical pair and iterate until `coverage report` shows **100%** on the `TOTAL` row:
   ```bash
   uv run coverage run -m unittest discover -s .
   uv run coverage report
   ```
6. Final certification: the very last commands you run before reporting must be exactly:
   ```bash
   uv run coverage run -m unittest discover -s .
   uv run coverage report
   ```
   and the output must show 100%. If it does not, you are not done — keep iterating.
7. Report back with:
   - The full `coverage report` output (must show 100% on `TOTAL`).
   - List of test files added or modified.
   - Confirmation that no file under `src/` was changed.

### If 100% is impossible without touching `src/`

Stop. Do **not** modify `src/`. Tell the user exactly which lines cannot be covered from tests alone and why (e.g., `if __name__ == "__main__"` blocks, defensive branches behind impossible states), and ask whether to leave them or whether they want to authorize a `src/` change in a separate step.
