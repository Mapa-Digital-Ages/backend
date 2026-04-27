# AGENTS.md — `src/`

Scope: every file under `src/` (production code for `md_backend`).

## Layout

- `md_backend/main.py` — FastAPI app entrypoint and router wiring.
- `md_backend/models/` — Pydantic request/response models and SQLAlchemy ORM models.
- `md_backend/routes/` — FastAPI routers. Thin layer: validate input, call a service, return response.
- `md_backend/services/` — Business logic. All side effects (DB, crypto, JWT) live here.
- `md_backend/utils/` — Cross-cutting helpers (database engine/session, settings, security).

## Conventions

- Python 3.12, fully async stack (FastAPI + SQLAlchemy async + asyncpg).
- Style is enforced by Ruff (`pyproject.toml`): line length 100, double quotes, Google docstrings.
- Public functions and classes must have a Google-style docstring. Routes and services count as public.
- Type-annotate every function signature. Prefer `from __future__ import annotations` only if needed.
- Pydantic models go in `models/api_models.py` (or a sibling module). Never return raw ORM objects from routes.
- Settings and secrets are read through `md_backend/utils/settings.py` — do not call `os.environ` directly inside routes/services.
- Keep routers free of business logic. If a route grows an `if` tree, push it into a service.
- Errors: raise `HTTPException` from routers; services should raise domain-specific exceptions or return result objects, never `HTTPException`.
- Database access: use the async session from `md_backend/utils/database.py`. Always `await session.commit()` explicitly when writing.

## Adding a new endpoint

1. Define request/response Pydantic models in `models/`.
2. Add the business logic to a service in `services/` (create a new module if the domain is new).
3. Add the route in `routes/`, depending on the service via `Depends`.
4. Register the router in `main.py` if it is a new module.
5. Mirror the change with tests under `tests/routes/` and `tests/services/`.

## Things to avoid

- Do not import from `tests/` inside `src/`.
- Do not add synchronous DB calls.
- Do not log secrets, tokens, or password hashes.
- Do not introduce new top-level packages without updating this file.
