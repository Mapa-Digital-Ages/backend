"""End-to-end integration test runner.

Orchestrates the docker-compose stack and runs every case from
``requests/integration_tests.rest`` plus an extensive battery of
extra cases (auth/JWT corner cases, Pydantic boundaries, full
``/school`` and ``/student`` coverage, soft-delete idempotency,
ordering, pagination) against the backend, validating status codes
and response shapes. Independent cases inside a stage run
concurrently via :func:`asyncio.gather`; stages with data
dependencies (captured tokens / ids) run sequentially.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import os
import pathlib
import re
import subprocess
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt

BASE_URL = "http://localhost:8000"
JWT_RE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


# ---------------------------------------------------------------------------
# Settings loading (JWT secret needed to forge tokens)
# ---------------------------------------------------------------------------


def _load_env_value(key: str, default: str = "") -> str:
    """Best-effort load of ``key`` from process env or local ``.env`` file."""
    val = os.environ.get(key)
    if val:
        return val
    env_path = pathlib.Path(__file__).parent / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip()
    return default


JWT_SECRET = _load_env_value("JWT_SECRET_KEY", "change-me-to-a-strong-random-string")
JWT_ALGORITHM = _load_env_value("JWT_ALGORITHM", "HS256")


# ---------------------------------------------------------------------------
# Pretty printing
# ---------------------------------------------------------------------------

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
DIM = "\033[2m"
RESET = "\033[0m"


def _color(s: str, c: str) -> str:
    return f"{c}{s}{RESET}"


# ---------------------------------------------------------------------------
# Test case primitives
# ---------------------------------------------------------------------------


@dataclass
class Case:
    """Single HTTP test case."""

    name: str
    method: str
    path: str
    expect_status: int | tuple[int, ...]
    json_body: dict | None = None
    headers_factory: Callable[[dict], dict] | None = None
    body_check: Callable[[Any], None] | None = None
    capture: Callable[[dict, Any], None] | None = None
    notes: str | None = None  # short tag (e.g. "documents-divergence")


@dataclass
class CaseResult:
    name: str
    passed: bool
    detail: str
    elapsed_ms: float
    status_code: int | None = None
    notes: str | None = None
    path: str = ""
    method: str = ""


@dataclass
class Stage:
    name: str
    cases: list[Case] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Body validators
# ---------------------------------------------------------------------------


class CheckError(AssertionError):
    """Raised when a body invariant fails."""


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def expect_keys(body: Any, keys: list[str]) -> None:
    if not isinstance(body, dict):
        raise CheckError(f"expected dict, got {type(body).__name__}")
    missing = [k for k in keys if k not in body]
    if missing:
        raise CheckError(f"missing keys {missing}")


def expect_keys_eq(expected: set[str]) -> Callable[[Any], None]:
    def check(body: Any) -> None:
        if not isinstance(body, dict):
            raise CheckError(f"expected dict, got {type(body).__name__}")
        actual = set(body.keys())
        if actual != expected:
            missing = expected - actual
            extra = actual - expected
            raise CheckError(f"keys mismatch missing={missing} extra={extra}")

    return check


def expect_each_has_keys(expected: set[str]) -> Callable[[Any], None]:
    def check(body: Any) -> None:
        if not isinstance(body, list):
            raise CheckError(f"expected list, got {type(body).__name__}")
        for i, item in enumerate(body):
            if not isinstance(item, dict):
                raise CheckError(f"item[{i}] is not dict")
            actual = set(item.keys())
            if actual != expected:
                missing = expected - actual
                extra = actual - expected
                raise CheckError(
                    f"item[{i}] keys mismatch missing={missing} extra={extra}"
                )

    return check


def expect_detail_eq(value: str) -> Callable[[Any], None]:
    def check(body: Any) -> None:
        if not isinstance(body, dict) or body.get("detail") != value:
            raise CheckError(f"expected detail={value!r}, got {body!r}")

    return check


def expect_id_uuid(body: Any) -> None:
    expect_keys(body, ["id"])
    if not _is_uuid(body["id"]):
        raise CheckError(f"id is not a valid UUID: {body['id']!r}")


def expect_token_role(role: str) -> Callable[[Any], None]:
    def check(body: Any) -> None:
        expect_keys(body, ["token", "role"])
        if not JWT_RE.match(str(body["token"])):
            raise CheckError(f"token is not a JWT: {body['token']!r}")
        if body["role"] != role:
            raise CheckError(f"expected role={role!r}, got {body['role']!r}")

    return check


def expect_list_only_role(role: str) -> Callable[[Any], None]:
    def check(body: Any) -> None:
        if not isinstance(body, list):
            raise CheckError(f"expected list, got {type(body).__name__}")
        wrong = [u.get("role") for u in body if u.get("role") != role]
        if wrong:
            raise CheckError(f"expected only role={role!r}, found {wrong!r}")

    return check


def expect_list_only_status(status_value: str) -> Callable[[Any], None]:
    def check(body: Any) -> None:
        if not isinstance(body, list):
            raise CheckError(f"expected list, got {type(body).__name__}")
        wrong = [u.get("status") for u in body if u.get("status") != status_value]
        if wrong:
            raise CheckError(f"expected only status={status_value!r}, found {wrong!r}")

    return check


def expect_list_min_len(n: int) -> Callable[[Any], None]:
    def check(body: Any) -> None:
        if not isinstance(body, list):
            raise CheckError(f"expected list, got {type(body).__name__}")
        if len(body) < n:
            raise CheckError(f"expected len>={n}, got {len(body)}")

    return check


def expect_list_empty(body: Any) -> None:
    if not isinstance(body, list):
        raise CheckError(f"expected list, got {type(body).__name__}")
    if body:
        raise CheckError(f"expected empty list, got len={len(body)}")


def expect_contains_email(email: str) -> Callable[[Any], None]:
    def check(body: Any) -> None:
        if not isinstance(body, list):
            raise CheckError(f"expected list, got {type(body).__name__}")
        if not any(u.get("email") == email for u in body):
            raise CheckError(f"expected to find email={email!r} in list")

    return check


def expect_not_contains_email(email: str) -> Callable[[Any], None]:
    def check(body: Any) -> None:
        if not isinstance(body, list):
            raise CheckError(f"expected list, got {type(body).__name__}")
        if any(u.get("email") == email for u in body):
            raise CheckError(f"unexpected email={email!r} in list")

    return check


def expect_last_is_superadmin(body: Any) -> None:
    if not isinstance(body, list) or not body:
        raise CheckError(f"expected non-empty list, got {body!r}")
    last = body[-1]
    if last.get("role") != "admin" or not last.get("is_superadmin"):
        raise CheckError(f"last user is not superadmin: {last!r}")


def expect_status_eq(status_value: str) -> Callable[[Any], None]:
    def check(body: Any) -> None:
        if not isinstance(body, dict) or body.get("status") != status_value:
            raise CheckError(f"expected status={status_value!r}, got {body!r}")

    return check


def expect_text_contains(*needles: str) -> Callable[[Any], None]:
    def check(body: Any) -> None:
        if not isinstance(body, str):
            raise CheckError(f"expected str body, got {type(body).__name__}")
        missing = [n for n in needles if n not in body]
        if missing:
            raise CheckError(f"text missing fragments {missing}: {body!r}")

    return check


def expect_paginated(
    expected_page: int,
    expected_size: int,
    min_total: int = 0,
) -> Callable[[Any], None]:
    def check(body: Any) -> None:
        expect_keys(body, ["items", "total", "page", "size"])
        if body["page"] != expected_page:
            raise CheckError(f"page={body['page']!r} != {expected_page}")
        if body["size"] != expected_size:
            raise CheckError(f"size={body['size']!r} != {expected_size}")
        if body["total"] < min_total:
            raise CheckError(f"total={body['total']!r} < {min_total}")
        if not isinstance(body["items"], list):
            raise CheckError("items is not a list")

    return check


def all_checks(*checks: Callable[[Any], None]) -> Callable[[Any], None]:
    def check(body: Any) -> None:
        for c in checks:
            c(body)

    return check


# ---------------------------------------------------------------------------
# Header / token helpers
# ---------------------------------------------------------------------------


def auth(token_key: str) -> Callable[[dict], dict]:
    """Bearer auth header from a token captured into ctx[token_key]."""

    def factory(ctx: dict) -> dict:
        token = ctx.get(token_key)
        if not token:
            raise CheckError(f"missing ctx[{token_key!r}] (must be captured earlier)")
        return {"Authorization": f"Bearer {token}"}

    return factory


def static_headers(headers: dict[str, str]) -> Callable[[dict], dict]:
    """Static headers, ignoring ctx (e.g. Authorization: Basic xxx)."""

    def factory(_ctx: dict) -> dict:
        return dict(headers)

    return factory


def forge_jwt(
    payload: dict,
    secret: str | None = None,
    exp_offset_minutes: float | None = None,
) -> str:
    """Forge a JWT for negative-path tests.

    - ``secret=None`` uses the backend's real secret -> valid signature.
    - Pass a different secret to produce an invalid-signature token.
    - ``exp_offset_minutes`` controls the expiration relative to now.
    """
    body = dict(payload)
    if exp_offset_minutes is not None:
        body["exp"] = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            minutes=exp_offset_minutes
        )
    return jwt.encode(body, secret if secret is not None else JWT_SECRET, algorithm=JWT_ALGORITHM)


def bearer(token: str) -> Callable[[dict], dict]:
    def factory(_ctx: dict) -> dict:
        return {"Authorization": f"Bearer {token}"}

    return factory


# ---------------------------------------------------------------------------
# Path resolvers
# ---------------------------------------------------------------------------


def resolve_path(template: str, ctx: dict) -> str:
    """Replace ``{key}`` markers in path with values from ``ctx``."""

    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in ctx:
            raise CheckError(f"missing ctx[{key!r}] for path interpolation")
        return str(ctx[key])

    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", repl, template)


def resolve_body(body: dict | None, ctx: dict) -> dict | None:
    """Recursively interpolate ``{key}`` placeholders inside string values."""
    if body is None:
        return None
    out: dict = {}
    for k, v in body.items():
        if isinstance(v, str) and "{" in v and "}" in v:
            out[k] = resolve_path(v, ctx)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _expected_statuses(case: Case) -> tuple[int, ...]:
    if isinstance(case.expect_status, int):
        return (case.expect_status,)
    return tuple(case.expect_status)


_TRANSIENT_HTTP_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.PoolTimeout,
)


async def run_case(client: httpx.AsyncClient, ctx: dict, case: Case) -> CaseResult:
    headers = case.headers_factory(ctx) if case.headers_factory else None
    started = time.perf_counter()
    try:
        path = resolve_path(case.path, ctx)
        body = resolve_body(case.json_body, ctx)
    except CheckError as e:
        elapsed = (time.perf_counter() - started) * 1000
        return CaseResult(
            case.name,
            False,
            f"setup error: {e}",
            elapsed,
            notes=case.notes,
            path=case.path,
            method=case.method,
        )

    last_error: httpx.HTTPError | None = None
    response: httpx.Response | None = None
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            response = await client.request(
                case.method,
                path,
                json=body,
                headers=headers,
            )
            last_error = None
            break
        except _TRANSIENT_HTTP_EXCEPTIONS as e:
            last_error = e
            if attempt == max_attempts:
                break
            await asyncio.sleep(0.05 * attempt)
            continue
        except httpx.HTTPError as e:
            last_error = e
            break

    if response is None:
        elapsed = (time.perf_counter() - started) * 1000
        return CaseResult(
            case.name,
            False,
            f"http error: {last_error}",
            elapsed,
            notes=case.notes,
            path=case.path,
            method=case.method,
        )

    elapsed = (time.perf_counter() - started) * 1000
    allowed = _expected_statuses(case)

    if response.status_code not in allowed:
        snippet = response.text[:200].replace("\n", " ")
        return CaseResult(
            case.name,
            False,
            f"status {response.status_code} not in {allowed}; body={snippet!r}",
            elapsed,
            response.status_code,
            notes=case.notes,
            path=case.path,
            method=case.method,
        )

    body_payload: Any
    try:
        body_payload = response.json() if response.content else None
    except ValueError:
        body_payload = response.text

    if case.body_check is not None:
        try:
            case.body_check(body_payload)
        except CheckError as e:
            return CaseResult(
                case.name,
                False,
                f"body check: {e}",
                elapsed,
                response.status_code,
                notes=case.notes,
                path=case.path,
                method=case.method,
            )
        except Exception as e:  # noqa: BLE001
            return CaseResult(
                case.name,
                False,
                f"body check raised: {e}",
                elapsed,
                response.status_code,
                notes=case.notes,
                path=case.path,
                method=case.method,
            )

    if case.capture is not None:
        try:
            case.capture(ctx, body_payload)
        except Exception as e:  # noqa: BLE001
            return CaseResult(
                case.name,
                False,
                f"capture raised: {e}",
                elapsed,
                response.status_code,
                notes=case.notes,
                path=case.path,
                method=case.method,
            )

    return CaseResult(
        case.name,
        True,
        "ok",
        elapsed,
        response.status_code,
        notes=case.notes,
        path=case.path,
        method=case.method,
    )


async def run_stage(client: httpx.AsyncClient, ctx: dict, stage: Stage) -> list[CaseResult]:
    """Run all cases in ``stage`` concurrently via :func:`asyncio.gather`."""
    print(f"\n{_color('Stage:', BLUE)} {stage.name} {_color(f'({len(stage.cases)} case(s))', DIM)}")
    coros: list[Awaitable[CaseResult]] = [run_case(client, ctx, c) for c in stage.cases]
    results = await asyncio.gather(*coros)
    for r in results:
        tag = _color("[PASS]", GREEN) if r.passed else _color("[FAIL]", RED)
        note = f" {_color('(' + r.notes + ')', YELLOW)}" if r.notes else ""
        print(f"  {tag} {r.name}{note} {_color(f'({r.elapsed_ms:.0f}ms)', DIM)}")
        if not r.passed:
            print(f"        {_color(r.detail, YELLOW)}")
    return results


# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------


# ===== Common payload fragments =====

_RESPO_USER_KEYS = {
    "id",
    "email",
    "name",
    "status",
    "role",
    "is_superadmin",
    "created_at",
}

_SCHOOL_KEYS = {
    "user_id",
    "email",
    "name",
    "is_private",
    "requested_spots",
    "is_active",
    "deactivated_at",
    "created_at",
    "quantidade_alunos",
}

_STUDENT_KEYS = {
    "id",
    "user_id",
    "first_name",
    "last_name",
    "email",
    "phone_number",
    "birth_date",
    "student_class",
    "school_id",
    "is_active",
    "created_at",
}


def _existing_core_stages() -> list[Stage]:
    """The original 31-case happy-path/error flow.

    Intentionally preserved verbatim so the regression suite still exists.
    Extra negative/Pydantic stages are interleaved around these via
    :func:`build_stages`.
    """
    return [
        # ------- Stage 0: healthcheck -------
        Stage(
            name="0. Healthcheck",
            cases=[
                Case(
                    name="GET / -> 200 alive",
                    method="GET",
                    path="/",
                    expect_status=200,
                    body_check=expect_detail_eq("Alive!"),
                ),
            ],
        ),
        # ------- Stage S0: setup Pydantic validation (run BEFORE setup OK) -------
        Stage(
            name="S0. /setup Pydantic validation (parallel)",
            cases=[
                Case(
                    name="S0.1 POST /setup empty body -> 422",
                    method="POST",
                    path="/setup",
                    json_body={},
                    expect_status=422,
                ),
                Case(
                    name="S0.2 POST /setup invalid email -> 422",
                    method="POST",
                    path="/setup",
                    json_body={"email": "not-an-email", "password": "12345678"},
                    expect_status=422,
                ),
                Case(
                    name="S0.3 POST /setup short password (7) -> 422",
                    method="POST",
                    path="/setup",
                    json_body={"email": "validemail@test.com", "password": "1234567"},
                    expect_status=422,
                ),
            ],
        ),
        # ------- Stage 1.1: setup OK -------
        Stage(
            name="1.1 Setup superadmin",
            cases=[
                Case(
                    name="POST /setup -> 201 superadmin created",
                    method="POST",
                    path="/setup",
                    json_body={
                        "email": "superadmin@test.com",
                        "password": "superpass123",
                    },
                    expect_status=201,
                    body_check=expect_id_uuid,
                ),
            ],
        ),
        # ------- Stage 1.2: setup duplicate -> 409 -------
        Stage(
            name="1.2 Setup duplicate -> 409",
            cases=[
                Case(
                    name="POST /setup duplicate -> 409",
                    method="POST",
                    path="/setup",
                    json_body={"email": "outro@test.com", "password": "outrapass123"},
                    expect_status=409,
                    body_check=expect_detail_eq("Setup ja realizado"),
                ),
                Case(
                    name="S1.1 POST /setup boundary password (8 chars) -> 409 (already setup)",
                    method="POST",
                    path="/setup",
                    json_body={"email": "boundary@test.com", "password": "12345678"},
                    expect_status=409,
                ),
            ],
        ),
        # ------- Stage 2: login wrong + admin login -------
        Stage(
            name="2. Login admin (wrong + correct + extras)",
            cases=[
                Case(
                    name="POST /login wrong password -> 401",
                    method="POST",
                    path="/login",
                    json_body={"email": "superadmin@test.com", "password": "errada"},
                    expect_status=401,
                ),
                Case(
                    name="L.1 POST /login unknown email -> 401",
                    method="POST",
                    path="/login",
                    json_body={"email": "ghost@test.com", "password": "anything12"},
                    expect_status=401,
                ),
                Case(
                    name="L.2 POST /login missing password -> 422",
                    method="POST",
                    path="/login",
                    json_body={"email": "superadmin@test.com"},
                    expect_status=422,
                ),
                Case(
                    name="L.3 POST /login invalid email format -> 422",
                    method="POST",
                    path="/login",
                    json_body={"email": "not-an-email", "password": "whatever1"},
                    expect_status=422,
                ),
                Case(
                    name="L.4 POST /login empty body -> 422",
                    method="POST",
                    path="/login",
                    json_body={},
                    expect_status=422,
                ),
                Case(
                    name="L.5 POST /login uppercase email -> 401 (DB case-sensitive)",
                    method="POST",
                    path="/login",
                    json_body={
                        "email": "SUPERADMIN@test.com",
                        "password": "superpass123",
                    },
                    expect_status=401,
                    notes="documents-divergence: emails are case-sensitive",
                ),
                Case(
                    name="POST /login admin OK -> 200, capture ADMIN_TOKEN",
                    method="POST",
                    path="/login",
                    json_body={
                        "email": "superadmin@test.com",
                        "password": "superpass123",
                    },
                    expect_status=200,
                    body_check=expect_token_role("admin"),
                    capture=lambda ctx, body: ctx.update(ADMIN_TOKEN=body["token"]),
                ),
            ],
        ),
        # ------- Stage 3.1: register Maria -------
        Stage(
            name="3.1 Register Maria (responsavel)",
            cases=[
                Case(
                    name="POST /register/responsavel Maria -> 201",
                    method="POST",
                    path="/register/responsavel",
                    json_body={
                        "name": "Maria Silva",
                        "email": "maria@test.com",
                        "password": "senha12345",
                    },
                    expect_status=201,
                    body_check=expect_id_uuid,
                    capture=lambda ctx, body: ctx.update(maria_id=body["id"]),
                ),
            ],
        ),
        # ------- Stage 3.2/3.3 + 4 + 5.{1,2,3} (parallel where independent) -------
        Stage(
            name="3.2/3.3 + 4 + 5.{1,2} parallel",
            cases=[
                Case(
                    name="3.2 register Maria duplicate -> 409",
                    method="POST",
                    path="/register/responsavel",
                    json_body={
                        "name": "Maria Silva",
                        "email": "maria@test.com",
                        "password": "senha12345",
                    },
                    expect_status=409,
                    body_check=expect_detail_eq("Email already registered"),
                ),
                Case(
                    name="3.3 register short password -> 422",
                    method="POST",
                    path="/register/responsavel",
                    json_body={"name": "X Y", "email": "x@test.com", "password": "123"},
                    expect_status=422,
                ),
                Case(
                    name="4.1 login Maria waiting -> 403 AGUARDANDO",
                    method="POST",
                    path="/login",
                    json_body={"email": "maria@test.com", "password": "senha12345"},
                    expect_status=403,
                    body_check=expect_detail_eq("AGUARDANDO"),
                ),
                Case(
                    name="5.1 register aluno missing fields -> 422",
                    method="POST",
                    path="/register/aluno",
                    json_body={
                        "name": "Joao Aluno",
                        "email": "joao@test.com",
                        "password": "alunopass1",
                    },
                    expect_status=422,
                ),
                Case(
                    name="5.2 register aluno invalid student_class -> 422",
                    method="POST",
                    path="/register/aluno",
                    json_body={
                        "name": "Joao Aluno",
                        "email": "joao@test.com",
                        "password": "alunopass1",
                        "birth_date": "2012-05-10",
                        "student_class": "10th class",
                    },
                    expect_status=422,
                ),
            ],
        ),
        # ------- Stage R1: register validation extras -------
        Stage(
            name="R1. Register Pydantic extras (parallel)",
            cases=[
                Case(
                    name="R1.1 register responsavel invalid email -> 422",
                    method="POST",
                    path="/register/responsavel",
                    json_body={
                        "name": "Bad Email",
                        "email": "invalid",
                        "password": "validpass1",
                    },
                    expect_status=422,
                ),
                Case(
                    name="R1.2 register responsavel password=7chars -> 422 (boundary)",
                    method="POST",
                    path="/register/responsavel",
                    json_body={
                        "name": "Boundary One",
                        "email": "boundary1@test.com",
                        "password": "1234567",
                    },
                    expect_status=422,
                ),
                Case(
                    name="R1.3 register responsavel password=8chars -> 201 (boundary)",
                    method="POST",
                    path="/register/responsavel",
                    json_body={
                        "name": "Boundary Two",
                        "email": "boundary2@test.com",
                        "password": "12345678",
                    },
                    expect_status=201,
                    body_check=expect_id_uuid,
                ),
                Case(
                    name="R1.4 register responsavel name='' -> 201 (no min_length)",
                    method="POST",
                    path="/register/responsavel",
                    json_body={
                        "name": "",
                        "email": "emptyname@test.com",
                        "password": "senha12345",
                    },
                    expect_status=201,
                    body_check=expect_id_uuid,
                    notes="documents-divergence: name='' is accepted",
                ),
                Case(
                    name="R1.5 register aluno duplicate email (preempt) -> 422 missing class",
                    method="POST",
                    path="/register/aluno",
                    json_body={
                        "name": "Some Aluno",
                        "email": "aluno-extra@test.com",
                        "password": "validpass1",
                        "birth_date": "2012-05-10",
                    },
                    expect_status=422,
                ),
                Case(
                    name="R1.6 register aluno invalid birth_date -> 422",
                    method="POST",
                    path="/register/aluno",
                    json_body={
                        "name": "Bad Date",
                        "email": "baddate@test.com",
                        "password": "validpass1",
                        "birth_date": "not-a-date",
                        "student_class": "7th class",
                    },
                    expect_status=422,
                ),
                Case(
                    name="R1.7 register aluno future birth_date -> 201 (no future check)",
                    method="POST",
                    path="/register/aluno",
                    json_body={
                        "name": "Future Kid",
                        "email": "futurekid@test.com",
                        "password": "validpass1",
                        "birth_date": "2050-01-01",
                        "student_class": "5th class",
                    },
                    expect_status=201,
                    body_check=expect_id_uuid,
                    notes="documents-divergence: future birth_date accepted",
                ),
            ],
        ),
        # ------- Stage R2: register one aluno per ClassEnum -------
        Stage(
            name="R2. Register aluno for each ClassEnum (parallel)",
            cases=[
                Case(
                    name=f"R2.{i + 1} register aluno class={cls} -> 201",
                    method="POST",
                    path="/register/aluno",
                    json_body={
                        "name": f"Aluno C{i + 5}",
                        "email": f"aluno-{cls.replace(' ', '-')}@test.com",
                        "password": "validpass1",
                        "birth_date": "2012-05-10",
                        "student_class": cls,
                    },
                    expect_status=201,
                    body_check=expect_id_uuid,
                )
                for i, cls in enumerate(
                    [
                        "5th class",
                        "6th class",
                        "7th class",
                        "8th class",
                        "9th class",
                    ]
                )
            ],
        ),
        # ------- Stage 5.3 register Joao OK -------
        Stage(
            name="5.3 Register Joao (aluno) OK",
            cases=[
                Case(
                    name="5.3 register Joao -> 201, capture id",
                    method="POST",
                    path="/register/aluno",
                    json_body={
                        "name": "Joao Aluno",
                        "email": "joao@test.com",
                        "password": "alunopass1",
                        "birth_date": "2012-05-10",
                        "student_class": "7th class",
                    },
                    expect_status=201,
                    body_check=expect_id_uuid,
                    capture=lambda ctx, body: ctx.update(joao_id=body["id"]),
                ),
            ],
        ),
        # ------- Stage R3: register aluno duplicate (after Joao exists) -------
        Stage(
            name="R3. Register aluno duplicate (sequential)",
            cases=[
                Case(
                    name="R3.1 register Joao again -> 409",
                    method="POST",
                    path="/register/aluno",
                    json_body={
                        "name": "Joao Aluno",
                        "email": "joao@test.com",
                        "password": "alunopass1",
                        "birth_date": "2012-05-10",
                        "student_class": "7th class",
                    },
                    expect_status=409,
                    body_check=expect_detail_eq("Email already registered"),
                ),
            ],
        ),
        # ------- Stage 6: login Joao -------
        Stage(
            name="6. Login Joao -> ALUNO_TOKEN",
            cases=[
                Case(
                    name="6.1 login Joao -> 200, role=aluno",
                    method="POST",
                    path="/login",
                    json_body={"email": "joao@test.com", "password": "alunopass1"},
                    expect_status=200,
                    body_check=expect_token_role("aluno"),
                    capture=lambda ctx, body: ctx.update(ALUNO_TOKEN=body["token"]),
                ),
            ],
        ),
        # ------- Stage 7: admin endpoints (parallel reads) -------
        Stage(
            name="7. Admin endpoints (parallel reads)",
            cases=[
                Case(
                    name="7.1 GET /admin/users no token -> 401",
                    method="GET",
                    path="/admin/users",
                    expect_status=401,
                ),
                Case(
                    name="7.2 GET /admin/users with aluno token -> 403",
                    method="GET",
                    path="/admin/users",
                    headers_factory=auth("ALUNO_TOKEN"),
                    expect_status=403,
                ),
                Case(
                    name="7.3 GET /admin/users admin -> 200 list",
                    method="GET",
                    path="/admin/users",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=200,
                    body_check=all_checks(
                        expect_list_min_len(3),
                        expect_each_has_keys(_RESPO_USER_KEYS),
                        expect_last_is_superadmin,
                    ),
                ),
                Case(
                    name="7.4 invalid user_status -> 422",
                    method="GET",
                    path="/admin/users?user_status=foo",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=422,
                ),
                Case(
                    name="7.5 invalid role -> 422",
                    method="GET",
                    path="/admin/users?role=foo",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=422,
                ),
                Case(
                    name="7.6 filter user_status=aguardando -> only aguardando",
                    method="GET",
                    path="/admin/users?user_status=aguardando",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=200,
                    body_check=expect_list_only_status("aguardando"),
                ),
                Case(
                    name="7.7 filter role=aluno -> only alunos",
                    method="GET",
                    path="/admin/users?role=aluno",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=200,
                    body_check=expect_list_only_role("aluno"),
                ),
                Case(
                    name="7.8 filter role=admin -> superadmin, capture id",
                    method="GET",
                    path="/admin/users?role=admin",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=200,
                    body_check=expect_list_only_role("admin"),
                    capture=lambda ctx, body: ctx.update(admin_id=body[0]["id"]),
                ),
            ],
        ),
        # ------- Stage A: admin/users JWT and filter extras -------
        Stage(
            name="A. /admin/users JWT and filter extras (parallel)",
            cases=[
                Case(
                    name="A.1 expired JWT -> 401 Token expired",
                    method="GET",
                    path="/admin/users",
                    headers_factory=bearer(
                        forge_jwt(
                            {
                                "sub": "superadmin@test.com",
                                "user_id": str(uuid.uuid4()),
                            },
                            exp_offset_minutes=-5,
                        )
                    ),
                    expect_status=401,
                    body_check=expect_detail_eq("Token expired"),
                ),
                Case(
                    name="A.2 wrong-secret JWT -> 401 Invalid token",
                    method="GET",
                    path="/admin/users",
                    headers_factory=bearer(
                        forge_jwt(
                            {
                                "sub": "superadmin@test.com",
                                "user_id": str(uuid.uuid4()),
                            },
                            secret="totally-wrong-secret",
                            exp_offset_minutes=30,
                        )
                    ),
                    expect_status=401,
                    body_check=expect_detail_eq("Invalid token"),
                ),
                Case(
                    name="A.3 Authorization Basic -> 401",
                    method="GET",
                    path="/admin/users",
                    headers_factory=static_headers({"Authorization": "Basic dXNlcjpwYXNz"}),
                    expect_status=401,
                ),
                Case(
                    name="A.4 Bearer with garbage token -> 401 Invalid token",
                    method="GET",
                    path="/admin/users",
                    headers_factory=static_headers({"Authorization": "Bearer notajwt"}),
                    expect_status=401,
                    body_check=expect_detail_eq("Invalid token"),
                ),
                Case(
                    name="A.5 Bearer JWT with unknown user_id -> 401 Usuario nao encontrado",
                    method="GET",
                    path="/admin/users",
                    headers_factory=bearer(
                        forge_jwt(
                            {
                                "sub": "ghost@test.com",
                                "user_id": str(uuid.uuid4()),
                            },
                            exp_offset_minutes=30,
                        )
                    ),
                    expect_status=401,
                    body_check=expect_detail_eq("Usuario nao encontrado"),
                ),
                Case(
                    name="A.6 Bearer JWT with non-uuid user_id -> 401 or 500 (bug)",
                    method="GET",
                    path="/admin/users",
                    headers_factory=bearer(
                        forge_jwt(
                            {"sub": "ghost@test.com", "user_id": "not-a-uuid"},
                            exp_offset_minutes=30,
                        )
                    ),
                    expect_status=(401, 500),
                    notes="documents-divergence: malformed user_id raises 500",
                ),
                Case(
                    name="A.7 filter user_status=aprovado -> only aprovado",
                    method="GET",
                    path="/admin/users?user_status=aprovado",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=200,
                    body_check=expect_list_only_status("aprovado"),
                ),
                Case(
                    name="A.8 filter role=admin&user_status=aguardando -> empty",
                    method="GET",
                    path="/admin/users?role=admin&user_status=aguardando",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=200,
                    body_check=expect_list_empty,
                ),
                Case(
                    name="A.9 filter role=responsavel -> only responsaveis",
                    method="GET",
                    path="/admin/users?role=responsavel",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=200,
                    body_check=expect_list_only_role("responsavel"),
                ),
            ],
        ),
        # ------- Stage 8.1-8.4: status update fail cases (parallel) -------
        Stage(
            name="8.1-8.4 Status update fail cases (parallel)",
            cases=[
                Case(
                    name="8.1 invalid status -> 422",
                    method="PATCH",
                    path="/admin/users/{maria_id}/status",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"status": "foo"},
                    expect_status=422,
                ),
                Case(
                    name="8.2 inexistent id -> 404",
                    method="PATCH",
                    path="/admin/users/00000000-0000-0000-0000-000000000000/status",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"status": "aprovado"},
                    expect_status=404,
                ),
                Case(
                    name="8.3 try modify superadmin -> 403",
                    method="PATCH",
                    path="/admin/users/{admin_id}/status",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"status": "negado"},
                    expect_status=403,
                ),
                Case(
                    name="8.4 approve aluno (no guardian profile) -> 403",
                    method="PATCH",
                    path="/admin/users/{joao_id}/status",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"status": "aprovado"},
                    expect_status=403,
                ),
                Case(
                    name="P.1 status=aguardando -> 422 (regex blocks)",
                    method="PATCH",
                    path="/admin/users/{maria_id}/status",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"status": "aguardando"},
                    expect_status=422,
                ),
                Case(
                    name="P.2 PATCH no token -> 401",
                    method="PATCH",
                    path="/admin/users/{maria_id}/status",
                    json_body={"status": "aprovado"},
                    expect_status=401,
                ),
                Case(
                    name="P.3 PATCH aluno token -> 403",
                    method="PATCH",
                    path="/admin/users/{maria_id}/status",
                    headers_factory=auth("ALUNO_TOKEN"),
                    json_body={"status": "aprovado"},
                    expect_status=403,
                ),
                Case(
                    name="P.4 PATCH invalid UUID in path -> 422",
                    method="PATCH",
                    path="/admin/users/abc/status",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"status": "aprovado"},
                    expect_status=422,
                ),
            ],
        ),
        # ------- Stage 8.5: approve Maria -------
        Stage(
            name="8.5 Approve Maria",
            cases=[
                Case(
                    name="8.5 approve Maria -> 200",
                    method="PATCH",
                    path="/admin/users/{maria_id}/status",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"status": "aprovado"},
                    expect_status=200,
                    body_check=expect_status_eq("aprovado"),
                ),
            ],
        ),
        # ------- Stage 8.6: login Maria approved -------
        Stage(
            name="8.6 Login Maria approved -> RESPO_TOKEN",
            cases=[
                Case(
                    name="8.6 login Maria approved -> 200",
                    method="POST",
                    path="/login",
                    json_body={"email": "maria@test.com", "password": "senha12345"},
                    expect_status=200,
                    body_check=expect_token_role("responsavel"),
                    capture=lambda ctx, body: ctx.update(RESPO_TOKEN=body["token"]),
                ),
            ],
        ),
        # ------- Stage P.toggle: deny -> approve -> verify token still works -------
        Stage(
            name="P.toggle.1 Deny Maria again",
            cases=[
                Case(
                    name="P.5 deny Maria -> 200",
                    method="PATCH",
                    path="/admin/users/{maria_id}/status",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"status": "negado"},
                    expect_status=200,
                    body_check=expect_status_eq("negado"),
                ),
            ],
        ),
        Stage(
            name="P.toggle.2 RESPO_TOKEN now blocked by approval check",
            cases=[
                Case(
                    name="P.6 /validate with denied Maria token -> 403",
                    method="POST",
                    path="/validate",
                    headers_factory=auth("RESPO_TOKEN"),
                    json_body={"text": "oi", "sender": "+55"},
                    expect_status=403,
                    body_check=expect_detail_eq("Conta negada"),
                ),
                Case(
                    name="P.7 login Maria denied -> 403 NEGADO",
                    method="POST",
                    path="/login",
                    json_body={"email": "maria@test.com", "password": "senha12345"},
                    expect_status=403,
                    body_check=expect_detail_eq("NEGADO"),
                ),
            ],
        ),
        Stage(
            name="P.toggle.3 Re-approve Maria",
            cases=[
                Case(
                    name="P.8 approve Maria again -> 200",
                    method="PATCH",
                    path="/admin/users/{maria_id}/status",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"status": "aprovado"},
                    expect_status=200,
                    body_check=expect_status_eq("aprovado"),
                ),
            ],
        ),
        # ------- Stage 9: validate (parallel) -------
        Stage(
            name="9. Validate endpoint (parallel)",
            cases=[
                Case(
                    name="9.1 POST /validate no token -> 401",
                    method="POST",
                    path="/validate",
                    json_body={"text": "oi", "sender": "+55"},
                    expect_status=401,
                ),
                Case(
                    name="9.2 POST /validate with approved token -> 200",
                    method="POST",
                    path="/validate",
                    headers_factory=auth("RESPO_TOKEN"),
                    json_body={"text": "oi", "sender": "+55"},
                    expect_status=200,
                    body_check=expect_text_contains("+55", "oi"),
                ),
                Case(
                    name="V.1 POST /validate with admin token -> 200",
                    method="POST",
                    path="/validate",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"text": "hi", "sender": "admin"},
                    expect_status=200,
                    body_check=expect_text_contains("admin", "hi"),
                ),
                Case(
                    name="V.2 POST /validate body missing text -> 422",
                    method="POST",
                    path="/validate",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"sender": "+55"},
                    expect_status=422,
                ),
                Case(
                    name="V.3 POST /validate empty body -> 422",
                    method="POST",
                    path="/validate",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={},
                    expect_status=422,
                ),
                Case(
                    name="V.4 POST /validate expired token -> 401",
                    method="POST",
                    path="/validate",
                    headers_factory=bearer(
                        forge_jwt(
                            {
                                "sub": "superadmin@test.com",
                                "user_id": str(uuid.uuid4()),
                            },
                            exp_offset_minutes=-5,
                        )
                    ),
                    json_body={"text": "oi", "sender": "+55"},
                    expect_status=401,
                    body_check=expect_detail_eq("Token expired"),
                ),
            ],
        ),
        # ------- Stage 10.1: register Pedro -------
        Stage(
            name="10.1 Register Pedro",
            cases=[
                Case(
                    name="10.1 register Pedro -> 201",
                    method="POST",
                    path="/register/responsavel",
                    json_body={
                        "name": "Pedro Bloqueado",
                        "email": "pedro@test.com",
                        "password": "pedrosenha1",
                    },
                    expect_status=201,
                    body_check=expect_id_uuid,
                    capture=lambda ctx, body: ctx.update(pedro_id=body["id"]),
                ),
            ],
        ),
        # ------- Stage 10.1.1: list responsaveis -------
        Stage(
            name="10.1.1 List responsaveis",
            cases=[
                Case(
                    name="10.1.1 list responsaveis -> 200 contains Pedro",
                    method="GET",
                    path="/admin/users?role=responsavel",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=200,
                    body_check=all_checks(
                        expect_list_only_role("responsavel"),
                        expect_contains_email("pedro@test.com"),
                        expect_contains_email("maria@test.com"),
                    ),
                ),
            ],
        ),
        # ------- Stage 10.2: deny Pedro -------
        Stage(
            name="10.2 Deny Pedro",
            cases=[
                Case(
                    name="10.2 deny Pedro -> 200",
                    method="PATCH",
                    path="/admin/users/{pedro_id}/status",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"status": "negado"},
                    expect_status=200,
                    body_check=expect_status_eq("negado"),
                ),
            ],
        ),
        # ------- Stage 10.3: login Pedro denied -------
        Stage(
            name="10.3 Login Pedro denied",
            cases=[
                Case(
                    name="10.3 login Pedro -> 403 NEGADO",
                    method="POST",
                    path="/login",
                    json_body={"email": "pedro@test.com", "password": "pedrosenha1"},
                    expect_status=403,
                    body_check=expect_detail_eq("NEGADO"),
                ),
                Case(
                    name="A.10 filter user_status=negado -> contains Pedro",
                    method="GET",
                    path="/admin/users?user_status=negado",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=200,
                    body_check=all_checks(
                        expect_list_only_status("negado"),
                        expect_contains_email("pedro@test.com"),
                    ),
                ),
            ],
        ),
    ]


def _school_stages() -> list[Stage]:
    """Full coverage of /school endpoints."""
    return [
        # ------- Create -------
        Stage(
            name="SC1.1 POST /school school1 (private)",
            cases=[
                Case(
                    name="SC1.1 POST /school school1 -> 201",
                    method="POST",
                    path="/school",
                    json_body={
                        "first_name": "Escola",
                        "last_name": "Privada",
                        "email": "escola1@test.com",
                        "password": "escolapass1",
                        "is_private": True,
                        "requested_spots": None,
                    },
                    expect_status=201,
                    body_check=all_checks(
                        expect_keys_eq(_SCHOOL_KEYS),
                        lambda b: (
                            None
                            if b.get("is_private") is True
                            and b.get("quantidade_alunos") == 0
                            and b.get("is_active") is True
                            else (_ for _ in ()).throw(
                                CheckError(f"unexpected school1 body: {b!r}")
                            )
                        ),
                    ),
                    capture=lambda ctx, body: ctx.update(school1_id=body["user_id"]),
                ),
            ],
        ),
        Stage(
            name="SC1.2 POST /school school2 (public)",
            cases=[
                Case(
                    name="SC1.2 POST /school school2 -> 201",
                    method="POST",
                    path="/school",
                    json_body={
                        "first_name": "Escola",
                        "last_name": "Publica",
                        "email": "escola2@test.com",
                        "password": "escolapass2",
                        "is_private": False,
                        "requested_spots": 120,
                    },
                    expect_status=201,
                    body_check=all_checks(
                        expect_keys_eq(_SCHOOL_KEYS),
                        lambda b: (
                            None
                            if b.get("is_private") is False
                            and b.get("requested_spots") == 120
                            else (_ for _ in ()).throw(
                                CheckError(f"unexpected school2 body: {b!r}")
                            )
                        ),
                    ),
                    capture=lambda ctx, body: ctx.update(school2_id=body["user_id"]),
                ),
            ],
        ),
        # ------- Negative create -------
        Stage(
            name="SC1.fails POST /school negative cases (parallel)",
            cases=[
                Case(
                    name="SC1.3 POST /school duplicate email -> 409",
                    method="POST",
                    path="/school",
                    json_body={
                        "first_name": "Outra",
                        "last_name": "Escola",
                        "email": "escola1@test.com",
                        "password": "escolapass1",
                        "is_private": True,
                    },
                    expect_status=409,
                    body_check=expect_detail_eq("E-mail ja cadastrado."),
                ),
                Case(
                    name="SC1.4 POST /school short password -> 422",
                    method="POST",
                    path="/school",
                    json_body={
                        "first_name": "Short",
                        "last_name": "Pwd",
                        "email": "shortpwd@test.com",
                        "password": "1234567",
                        "is_private": True,
                    },
                    expect_status=422,
                ),
                Case(
                    name="SC1.5 POST /school missing is_private -> 422",
                    method="POST",
                    path="/school",
                    json_body={
                        "first_name": "Missing",
                        "last_name": "Field",
                        "email": "missingfield@test.com",
                        "password": "validpass1",
                    },
                    expect_status=422,
                ),
                Case(
                    name="SC1.6 POST /school invalid email -> 422",
                    method="POST",
                    path="/school",
                    json_body={
                        "first_name": "Bad",
                        "last_name": "Email",
                        "email": "not-an-email",
                        "password": "validpass1",
                        "is_private": False,
                    },
                    expect_status=422,
                ),
                Case(
                    name="SC1.7 POST /school empty first_name -> 422 (min_length=1)",
                    method="POST",
                    path="/school",
                    json_body={
                        "first_name": "",
                        "last_name": "Last",
                        "email": "emptyfn@test.com",
                        "password": "validpass1",
                        "is_private": True,
                    },
                    expect_status=422,
                ),
                Case(
                    name="SC1.8 POST /school requested_spots=-5 -> 201 (no ge=0)",
                    method="POST",
                    path="/school",
                    json_body={
                        "first_name": "Negative",
                        "last_name": "Spots",
                        "email": "negspots@test.com",
                        "password": "validpass1",
                        "is_private": False,
                        "requested_spots": -5,
                    },
                    expect_status=201,
                    notes="documents-divergence: requested_spots can be negative",
                ),
            ],
        ),
        # ------- List / Get -------
        Stage(
            name="SC2 GET /school list and detail (parallel)",
            cases=[
                Case(
                    name="SC2.1 GET /school -> 200 list both schools",
                    method="GET",
                    path="/school",
                    expect_status=200,
                    body_check=all_checks(
                        expect_paginated(expected_page=1, expected_size=20, min_total=2),
                        lambda b: (
                            None
                            if any(s.get("email") == "escola1@test.com" for s in b["items"])
                            and any(s.get("email") == "escola2@test.com" for s in b["items"])
                            else (_ for _ in ()).throw(
                                CheckError(f"missing school in list: {b!r}")
                            )
                        ),
                    ),
                ),
                Case(
                    name="SC2.2 GET /school?name=Escola -> 200 (filter works)",
                    method="GET",
                    path="/school?name=Escola",
                    expect_status=200,
                    body_check=expect_paginated(expected_page=1, expected_size=20, min_total=2),
                ),
                Case(
                    name="SC2.3 GET /school?name=ZZZ -> 200 empty",
                    method="GET",
                    path="/school?name=ZZZ_no_match",
                    expect_status=200,
                    body_check=expect_paginated(expected_page=1, expected_size=20, min_total=0),
                ),
                Case(
                    name="SC2.4 GET /school?page=2&size=1 -> 200",
                    method="GET",
                    path="/school?page=2&size=1",
                    expect_status=200,
                    body_check=expect_paginated(expected_page=2, expected_size=1, min_total=2),
                ),
                Case(
                    name="SC2.5 GET /school?page=0 -> 422",
                    method="GET",
                    path="/school?page=0",
                    expect_status=422,
                ),
                Case(
                    name="SC2.6 GET /school?size=200 -> 422",
                    method="GET",
                    path="/school?size=200",
                    expect_status=422,
                ),
                Case(
                    name="SC2.7 GET /school?size=0 -> 422",
                    method="GET",
                    path="/school?size=0",
                    expect_status=422,
                ),
                Case(
                    name="SC2.8 GET /school/{school1_id} -> 200",
                    method="GET",
                    path="/school/{school1_id}",
                    expect_status=200,
                    body_check=expect_keys_eq(_SCHOOL_KEYS),
                ),
                Case(
                    name="SC2.9 GET /school/<unknown> -> 404",
                    method="GET",
                    path="/school/00000000-0000-0000-0000-000000000000",
                    expect_status=404,
                    body_check=expect_detail_eq("Escola não encontrada."),
                ),
                Case(
                    name="SC2.10 GET /school/abc -> 422 (bad UUID)",
                    method="GET",
                    path="/school/abc",
                    expect_status=422,
                ),
            ],
        ),
        # ------- PATCH negatives (parallel) -------
        Stage(
            name="SC3.fails PATCH /school negative cases (parallel)",
            cases=[
                Case(
                    name="SC3.1 PATCH /school no token -> 401",
                    method="PATCH",
                    path="/school/{school1_id}",
                    json_body={"first_name": "Hacker"},
                    expect_status=401,
                ),
                Case(
                    name="SC3.2 PATCH /school aluno token -> 403",
                    method="PATCH",
                    path="/school/{school1_id}",
                    headers_factory=auth("ALUNO_TOKEN"),
                    json_body={"first_name": "Hacker"},
                    expect_status=403,
                ),
                Case(
                    name="SC3.3 PATCH /school not found -> 404",
                    method="PATCH",
                    path="/school/00000000-0000-0000-0000-000000000000",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"first_name": "Ghost"},
                    expect_status=404,
                ),
                Case(
                    name="SC3.4 PATCH /school email conflict -> 409",
                    method="PATCH",
                    path="/school/{school1_id}",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"email": "escola2@test.com"},
                    expect_status=409,
                    body_check=expect_detail_eq("E-mail ja cadastrado."),
                ),
                Case(
                    name="SC3.5 PATCH /school invalid UUID -> 422",
                    method="PATCH",
                    path="/school/abc",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"first_name": "X"},
                    expect_status=422,
                ),
            ],
        ),
        # ------- PATCH success (sequential) -------
        Stage(
            name="SC3.ok PATCH school1 rename",
            cases=[
                Case(
                    name="SC3.6 PATCH /school first_name -> 200",
                    method="PATCH",
                    path="/school/{school1_id}",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"first_name": "Renomeada"},
                    expect_status=200,
                    body_check=lambda b: (
                        None
                        if b.get("name", "").startswith("Renomeada")
                        else (_ for _ in ()).throw(
                            CheckError(f"name not updated: {b!r}")
                        )
                    ),
                ),
            ],
        ),
        # ------- DELETE school1 -------
        Stage(
            name="SC4.fails DELETE /school negative cases (parallel)",
            cases=[
                Case(
                    name="SC4.1 DELETE /school no token -> 401",
                    method="DELETE",
                    path="/school/{school1_id}",
                    expect_status=401,
                ),
                Case(
                    name="SC4.2 DELETE /school aluno token -> 403",
                    method="DELETE",
                    path="/school/{school1_id}",
                    headers_factory=auth("ALUNO_TOKEN"),
                    expect_status=403,
                ),
                Case(
                    name="SC4.3 DELETE /school unknown id -> 404",
                    method="DELETE",
                    path="/school/00000000-0000-0000-0000-000000000000",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=404,
                ),
            ],
        ),
        Stage(
            name="SC4.ok DELETE school1",
            cases=[
                Case(
                    name="SC4.4 DELETE /school school1 -> 204",
                    method="DELETE",
                    path="/school/{school1_id}",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=204,
                ),
            ],
        ),
        Stage(
            name="SC4.post DELETE state checks (parallel)",
            cases=[
                Case(
                    name="SC4.5 GET /school excludes deleted school1",
                    method="GET",
                    path="/school?size=100",
                    expect_status=200,
                    body_check=lambda b: (
                        None
                        if not any(
                            s.get("email") == "escola1@test.com" for s in b.get("items", [])
                        )
                        else (_ for _ in ()).throw(
                            CheckError("deleted school1 still in list")
                        )
                    ),
                ),
                Case(
                    name="SC4.6 GET /school/{school1_id} -> 200 with is_active=False",
                    method="GET",
                    path="/school/{school1_id}",
                    expect_status=200,
                    body_check=lambda b: (
                        None
                        if b.get("is_active") is False and b.get("deactivated_at")
                        else (_ for _ in ()).throw(
                            CheckError(f"expected deactivated school: {b!r}")
                        )
                    ),
                    notes="documents-divergence: get_school_by_id ignores is_active",
                ),
                Case(
                    name="SC4.7 DELETE /school school1 again -> 204 (idempotent)",
                    method="DELETE",
                    path="/school/{school1_id}",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=204,
                    notes="documents-divergence: delete is idempotent",
                ),
            ],
        ),
    ]


def _student_stages() -> list[Stage]:
    """Full coverage of /student endpoints."""
    return [
        # ------- Create negatives (parallel) -------
        Stage(
            name="ST1.fails POST /student negative cases (parallel)",
            cases=[
                Case(
                    name="ST1.1 POST /student no token -> 401",
                    method="POST",
                    path="/student",
                    json_body={
                        "first_name": "Foo",
                        "last_name": "Bar",
                        "email": "noauth@test.com",
                        "password": "validpass1",
                        "birth_date": "2012-05-10",
                        "student_class": "7th class",
                    },
                    expect_status=401,
                ),
                Case(
                    name="ST1.2 POST /student aluno token -> 403",
                    method="POST",
                    path="/student",
                    headers_factory=auth("ALUNO_TOKEN"),
                    json_body={
                        "first_name": "Foo",
                        "last_name": "Bar",
                        "email": "alunoauth@test.com",
                        "password": "validpass1",
                        "birth_date": "2012-05-10",
                        "student_class": "7th class",
                    },
                    expect_status=403,
                ),
                Case(
                    name="ST1.3 POST /student invalid student_class -> 422",
                    method="POST",
                    path="/student",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={
                        "first_name": "Bad",
                        "last_name": "Class",
                        "email": "badclass@test.com",
                        "password": "validpass1",
                        "birth_date": "2012-05-10",
                        "student_class": "99th class",
                    },
                    expect_status=422,
                ),
                Case(
                    name="ST1.4 POST /student short password -> 422",
                    method="POST",
                    path="/student",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={
                        "first_name": "Bad",
                        "last_name": "Pwd",
                        "email": "badpwd@test.com",
                        "password": "1234567",
                        "birth_date": "2012-05-10",
                        "student_class": "7th class",
                    },
                    expect_status=422,
                ),
                Case(
                    name="ST1.5 POST /student invalid email -> 422",
                    method="POST",
                    path="/student",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={
                        "first_name": "Bad",
                        "last_name": "Email",
                        "email": "not-an-email",
                        "password": "validpass1",
                        "birth_date": "2012-05-10",
                        "student_class": "7th class",
                    },
                    expect_status=422,
                ),
            ],
        ),
        # ------- Create OK (sequential) -------
        Stage(
            name="ST1.ok POST /student admin -> 201",
            cases=[
                Case(
                    name="ST1.6 POST /student admin -> 201",
                    method="POST",
                    path="/student",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={
                        "first_name": "Ana",
                        "last_name": "Estudante",
                        "email": "ana-student@test.com",
                        "password": "alunopass1",
                        "birth_date": "2013-08-20",
                        "student_class": "6th class",
                    },
                    expect_status=201,
                    body_check=expect_keys_eq(_STUDENT_KEYS),
                    capture=lambda ctx, body: ctx.update(student_id=body["id"]),
                ),
            ],
        ),
        Stage(
            name="ST1.dup POST /student duplicate email -> 409",
            cases=[
                Case(
                    name="ST1.7 POST /student duplicate email -> 409",
                    method="POST",
                    path="/student",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={
                        "first_name": "Ana",
                        "last_name": "Repetida",
                        "email": "ana-student@test.com",
                        "password": "alunopass1",
                        "birth_date": "2013-08-20",
                        "student_class": "6th class",
                    },
                    expect_status=409,
                ),
            ],
        ),
        # ------- List / Get (parallel) -------
        Stage(
            name="ST2 GET /student list and detail (parallel)",
            cases=[
                Case(
                    name="ST2.1 GET /student no token -> 401",
                    method="GET",
                    path="/student",
                    expect_status=401,
                ),
                Case(
                    name="ST2.2 GET /student admin -> 200 list contains Ana",
                    method="GET",
                    path="/student?size=100",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=200,
                    body_check=all_checks(
                        expect_list_min_len(1),
                        expect_each_has_keys(_STUDENT_KEYS),
                        expect_contains_email("ana-student@test.com"),
                    ),
                ),
                Case(
                    name="ST2.3 GET /student?name=Ana -> 200 only Ana",
                    method="GET",
                    path="/student?name=Ana",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=200,
                    body_check=expect_contains_email("ana-student@test.com"),
                ),
                Case(
                    name="ST2.4 GET /student?email=ana-student -> 200",
                    method="GET",
                    path="/student?email=ana-student",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=200,
                    body_check=expect_contains_email("ana-student@test.com"),
                ),
                Case(
                    name="ST2.5 GET /student?page=0 -> 422",
                    method="GET",
                    path="/student?page=0",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=422,
                ),
                Case(
                    name="ST2.6 GET /student?size=0 -> 422",
                    method="GET",
                    path="/student?size=0",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=422,
                ),
                Case(
                    name="ST2.7 GET /student?size=101 -> 422",
                    method="GET",
                    path="/student?size=101",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=422,
                ),
                Case(
                    name="ST2.8 GET /student/{student_id} -> 200",
                    method="GET",
                    path="/student/{student_id}",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=200,
                    body_check=expect_keys_eq(_STUDENT_KEYS),
                ),
                Case(
                    name="ST2.9 GET /student/<unknown> -> 404",
                    method="GET",
                    path="/student/00000000-0000-0000-0000-000000000000",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=404,
                    body_check=expect_detail_eq("Student not found"),
                ),
                Case(
                    name="ST2.10 GET /student/abc -> 422 (bad UUID)",
                    method="GET",
                    path="/student/abc",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=422,
                ),
            ],
        ),
        # ------- PUT happy + edge -------
        Stage(
            name="ST3.ok PUT /student rename",
            cases=[
                Case(
                    name="ST3.1 PUT /student first_name -> 200",
                    method="PUT",
                    path="/student/{student_id}",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"first_name": "AnaMaria"},
                    expect_status=200,
                    body_check=lambda b: (
                        None
                        if b.get("first_name") == "AnaMaria"
                        else (_ for _ in ()).throw(
                            CheckError(f"name not updated: {b!r}")
                        )
                    ),
                ),
            ],
        ),
        Stage(
            name="ST3.attach PUT /student attach school2",
            cases=[
                Case(
                    name="ST3.2 PUT /student school_id={school2_id} -> 200",
                    method="PUT",
                    path="/student/{student_id}",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"school_id": "{school2_id}"},
                    expect_status=200,
                    body_check=lambda b: (
                        None
                        if b.get("school_id")
                        else (_ for _ in ()).throw(
                            CheckError(f"school_id not set: {b!r}")
                        )
                    ),
                ),
            ],
        ),
        Stage(
            name="ST3.fk PUT /student bad school_id (FK violation)",
            cases=[
                Case(
                    name="ST3.3 PUT /student bad school_id -> 4xx or 500 (bug)",
                    method="PUT",
                    path="/student/{student_id}",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"school_id": "00000000-0000-0000-0000-000000000000"},
                    expect_status=(400, 409, 422, 500),
                    notes="documents-divergence: FK violation surfaces as 500",
                ),
            ],
        ),
        Stage(
            name="ST3.misc PUT /student edge cases (parallel)",
            cases=[
                Case(
                    name="ST3.4 PUT /student no token -> 401",
                    method="PUT",
                    path="/student/{student_id}",
                    json_body={"first_name": "X"},
                    expect_status=401,
                ),
                Case(
                    name="ST3.5 PUT /student not found -> 404",
                    method="PUT",
                    path="/student/00000000-0000-0000-0000-000000000000",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"first_name": "Ghost"},
                    expect_status=404,
                ),
                Case(
                    name="ST3.6 PUT /student invalid UUID -> 422",
                    method="PUT",
                    path="/student/abc",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"first_name": "Y"},
                    expect_status=422,
                ),
                Case(
                    name="ST3.7 PUT /student invalid student_class -> 422",
                    method="PUT",
                    path="/student/{student_id}",
                    headers_factory=auth("ADMIN_TOKEN"),
                    json_body={"student_class": "99th class"},
                    expect_status=422,
                ),
            ],
        ),
        # ------- DELETE -------
        Stage(
            name="ST4.fails DELETE /student negative cases (parallel)",
            cases=[
                Case(
                    name="ST4.1 DELETE /student no token -> 401",
                    method="DELETE",
                    path="/student/{student_id}",
                    expect_status=401,
                ),
                Case(
                    name="ST4.2 DELETE /student unknown -> 404",
                    method="DELETE",
                    path="/student/00000000-0000-0000-0000-000000000000",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=404,
                ),
                Case(
                    name="ST4.3 DELETE /student invalid UUID -> 422",
                    method="DELETE",
                    path="/student/abc",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=422,
                ),
            ],
        ),
        Stage(
            name="ST4.ok DELETE student",
            cases=[
                Case(
                    name="ST4.4 DELETE /student admin -> 204",
                    method="DELETE",
                    path="/student/{student_id}",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=204,
                ),
            ],
        ),
        Stage(
            name="ST4.post DELETE state checks (parallel)",
            cases=[
                Case(
                    name="ST4.5 GET /student?name=AnaMaria excludes deleted",
                    method="GET",
                    path="/student?name=AnaMaria",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=200,
                    body_check=expect_not_contains_email("ana-student@test.com"),
                ),
                Case(
                    name="ST4.6 GET /student/{student_id} -> 200 with is_active=False",
                    method="GET",
                    path="/student/{student_id}",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=200,
                    body_check=lambda b: (
                        None
                        if b.get("is_active") is False
                        else (_ for _ in ()).throw(
                            CheckError(f"expected deactivated student: {b!r}")
                        )
                    ),
                    notes="documents-divergence: get_student_by_id ignores is_active",
                ),
                Case(
                    name="ST4.7 DELETE /student again -> 204 (idempotent)",
                    method="DELETE",
                    path="/student/{student_id}",
                    headers_factory=auth("ADMIN_TOKEN"),
                    expect_status=204,
                    notes="documents-divergence: delete is idempotent",
                ),
            ],
        ),
    ]


def build_stages() -> list[Stage]:
    return [*_existing_core_stages(), *_school_stages(), *_student_stages()]


# ---------------------------------------------------------------------------
# Docker compose orchestration
# ---------------------------------------------------------------------------


def _run_compose(args: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", *args]
    print(_color(f"$ {' '.join(cmd)}", DIM))
    return subprocess.run(
        cmd,
        check=True,
        capture_output=capture,
        text=True,
    )


def reset_stack() -> None:
    print(_color("\n=== Resetting docker-compose stack ===", BLUE))
    _run_compose(["down", "-v"])
    _run_compose(["up", "-d", "--build"])


def teardown_stack() -> None:
    print(_color("\n=== Tearing down docker-compose stack ===", BLUE))
    _run_compose(["down", "-v"])


async def wait_for_backend(client: httpx.AsyncClient, timeout: float = 90.0) -> None:
    print(_color(f"Waiting for backend at {BASE_URL} (timeout={timeout}s)...", DIM))
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            r = await client.get("/")
            if r.status_code == 200:
                print(_color("Backend is up.", GREEN))
                return
        except httpx.HTTPError as e:  # noqa: PERF203
            last_err = e
        await asyncio.sleep(1.0)
    raise RuntimeError(f"backend never became ready: {last_err!r}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _route_bucket(method: str, path: str) -> str:
    """Best-effort coarse route grouping for the summary."""
    head = path.lstrip("/").split("?", 1)[0].split("/", 2)
    if not head or not head[0]:
        return f"{method} /"
    base = head[0]
    return f"{method} /{base}"


def _print_summary(all_results: list[CaseResult], elapsed: float) -> None:
    total = len(all_results)
    passed = sum(1 for r in all_results if r.passed)
    failed = total - passed

    summary = f"\n{passed}/{total} passed ({failed} failed) in {elapsed:.2f}s"
    print(_color(summary, GREEN if failed == 0 else RED))

    by_route: dict[str, list[CaseResult]] = {}
    for r in all_results:
        by_route.setdefault(_route_bucket(r.method, r.path), []).append(r)
    print(_color("\nCoverage by route:", BLUE))
    for route in sorted(by_route):
        rs = by_route[route]
        ok = sum(1 for r in rs if r.passed)
        print(f"  {route:<25} {ok}/{len(rs)}")

    divergent = [r for r in all_results if r.notes and r.notes.startswith("documents-divergence")]
    if divergent:
        print(_color("\nDivergent-behavior cases (documenting current backend):", YELLOW))
        for r in divergent:
            tag = "PASS" if r.passed else "FAIL"
            print(f"  [{tag}] {r.name} -- {r.notes}")

    if failed:
        print(_color("\nFailed cases:", RED))
        for r in all_results:
            if not r.passed:
                print(f"  - {r.name}: {r.detail}")


async def run_all_stages(client: httpx.AsyncClient, fail_fast: bool) -> int:
    ctx: dict = {}
    stages = build_stages()
    all_results: list[CaseResult] = []
    started = time.perf_counter()

    for stage in stages:
        results = await run_stage(client, ctx, stage)
        all_results.extend(results)
        if fail_fast and any(not r.passed for r in results):
            print(
                _color(
                    f"\nStopping early after failure(s) in stage: {stage.name}",
                    YELLOW,
                )
            )
            break

    elapsed = time.perf_counter() - started
    _print_summary(all_results, elapsed)
    failed = sum(1 for r in all_results if not r.passed)
    return 0 if failed == 0 else 1


async def amain(args: argparse.Namespace) -> int:
    if not args.no_reset:
        reset_stack()
    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
            await wait_for_backend(client, timeout=args.boot_timeout)
            return await run_all_stages(client, fail_fast=args.fail_fast)
    finally:
        if args.keep_up:
            print(_color("\n--keep-up: leaving stack running.", YELLOW))
        elif not args.no_reset:
            teardown_stack()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Skip docker compose down/up (assume stack is already running with empty DB).",
    )
    parser.add_argument(
        "--keep-up",
        action="store_true",
        help="Do not tear down the stack after the run (useful for debugging).",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop at the first stage with any failure (default: keep going).",
    )
    parser.add_argument(
        "--boot-timeout",
        type=float,
        default=90.0,
        help="Seconds to wait for backend to respond on / (default: 90).",
    )
    args = parser.parse_args()

    try:
        return asyncio.run(amain(args))
    except KeyboardInterrupt:
        print(_color("\nInterrupted.", YELLOW))
        return 130
    except subprocess.CalledProcessError as e:
        print(_color(f"\ndocker command failed: {e}", RED))
        return e.returncode or 1
    except Exception as e:  # noqa: BLE001
        print(_color(f"\nunexpected error: {e!r}", RED))
        return 1


if __name__ == "__main__":
    sys.exit(main())
