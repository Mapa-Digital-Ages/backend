"""Tests for the login service."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import tests.keys_test  # noqa: F401
from md_backend.models.db_models import UserStatus
from md_backend.services.login_service import LoginService


def _make_mock_user(email="user@test.com", hashed_password="hashed", status=UserStatus.APROVADO):
    user = MagicMock()
    user.id = 1
    user.email = email
    user.hashed_password = hashed_password
    user.status = status
    user.role = "responsavel"
    user.name = "Test"
    return user


class TestLoginService(unittest.TestCase):
    def test_login_success(self):
        service = LoginService()
        user = _make_mock_user()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        with patch("md_backend.services.login_service.verify_password", return_value=True):
            with patch(
                "md_backend.services.login_service.create_access_token", return_value="tok123"
            ):
                result = asyncio.run(service.login("user@test.com", "pass", mock_session))

        self.assertEqual(result["token"], "tok123")
        self.assertEqual(result["email"], "user@test.com")

    def test_login_user_not_found(self):
        service = LoginService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = asyncio.run(service.login("ghost@test.com", "pass", mock_session))
        self.assertEqual(result, {"error": "invalid_credentials"})

    def test_login_wrong_password(self):
        service = LoginService()
        user = _make_mock_user()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        with patch("md_backend.services.login_service.verify_password", return_value=False):
            result = asyncio.run(service.login("user@test.com", "wrong", mock_session))

        self.assertEqual(result, {"error": "invalid_credentials"})

    def test_login_aguardando(self):
        service = LoginService()
        user = _make_mock_user(status=UserStatus.AGUARDANDO)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        with patch("md_backend.services.login_service.verify_password", return_value=True):
            result = asyncio.run(service.login("user@test.com", "pass", mock_session))

        self.assertEqual(result, {"error": "AGUARDANDO"})

    def test_login_negado(self):
        service = LoginService()
        user = _make_mock_user(status=UserStatus.NEGADO)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        with patch("md_backend.services.login_service.verify_password", return_value=True):
            result = asyncio.run(service.login("user@test.com", "pass", mock_session))

        self.assertEqual(result, {"error": "NEGADO"})
