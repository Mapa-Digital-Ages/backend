"""Tests for the login service."""

import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import tests.keys_test  # noqa: F401
from md_backend.models.db_models import GuardianStatusEnum
from md_backend.services.login_service import LoginService


def _make_user(
    *,
    email="user@test.com",
    password="hashed",
    first_name="First",
    last_name="Last",
    guardian_status=GuardianStatusEnum.APPROVED,
    has_guardian=True,
    has_student=False,
    has_admin=False,
    is_superadmin=False,
):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = email
    user.password = password
    user.first_name = first_name
    user.last_name = last_name

    if has_guardian:
        guardian = MagicMock()
        guardian.guardian_status = guardian_status
        user.guardian_profile = guardian
    else:
        user.guardian_profile = None

    if has_student:
        user.student_profile = MagicMock()
    else:
        user.student_profile = None

    if has_admin:
        admin = MagicMock()
        admin.is_superadmin = is_superadmin
        user.admin_profile = admin
    else:
        user.admin_profile = None
    return user


def _session_with_user(user):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result
    return mock_session


class TestLoginService(unittest.TestCase):
    def test_login_success_responsavel(self):
        service = LoginService()
        user = _make_user(guardian_status=GuardianStatusEnum.APPROVED)
        session = _session_with_user(user)

        with patch("md_backend.services.login_service.verify_password", return_value=True):
            with patch(
                "md_backend.services.login_service.create_access_token", return_value="tok123"
            ):
                result = asyncio.run(service.login(user.email, "pass", session))

        self.assertEqual(result["token"], "tok123")
        self.assertEqual(result["email"], user.email)
        self.assertEqual(result["role"], "responsavel")
        self.assertEqual(result["name"], "First Last")

    def test_login_success_admin(self):
        service = LoginService()
        user = _make_user(
            has_guardian=False, has_admin=True, is_superadmin=True
        )
        session = _session_with_user(user)

        with patch("md_backend.services.login_service.verify_password", return_value=True):
            with patch(
                "md_backend.services.login_service.create_access_token", return_value="tok"
            ):
                result = asyncio.run(service.login(user.email, "pass", session))

        self.assertEqual(result["role"], "admin")

    def test_login_success_aluno(self):
        service = LoginService()
        user = _make_user(has_guardian=False, has_student=True)
        session = _session_with_user(user)

        with patch("md_backend.services.login_service.verify_password", return_value=True):
            with patch(
                "md_backend.services.login_service.create_access_token", return_value="tok"
            ):
                result = asyncio.run(service.login(user.email, "pass", session))

        self.assertEqual(result["role"], "aluno")

    def test_login_user_not_found(self):
        service = LoginService()
        session = _session_with_user(None)

        result = asyncio.run(service.login("ghost@test.com", "pass", session))
        self.assertEqual(result, {"error": "invalid_credentials"})

    def test_login_wrong_password(self):
        service = LoginService()
        user = _make_user()
        session = _session_with_user(user)

        with patch("md_backend.services.login_service.verify_password", return_value=False):
            result = asyncio.run(service.login(user.email, "wrong", session))

        self.assertEqual(result, {"error": "invalid_credentials"})

    def test_login_aguardando(self):
        service = LoginService()
        user = _make_user(guardian_status=GuardianStatusEnum.WAITING)
        session = _session_with_user(user)

        with patch("md_backend.services.login_service.verify_password", return_value=True):
            result = asyncio.run(service.login(user.email, "pass", session))

        self.assertEqual(result, {"error": "AGUARDANDO"})

    def test_login_negado(self):
        service = LoginService()
        user = _make_user(guardian_status=GuardianStatusEnum.REJECTED)
        session = _session_with_user(user)

        with patch("md_backend.services.login_service.verify_password", return_value=True):
            result = asyncio.run(service.login(user.email, "pass", session))

        self.assertEqual(result, {"error": "NEGADO"})
