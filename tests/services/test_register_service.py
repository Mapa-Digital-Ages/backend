"""Tests for the register service."""

import asyncio
import datetime
import unittest
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.exc import IntegrityError

import tests.keys_test  # noqa: F401
from md_backend.models.db_models import ClassEnum
from md_backend.services.register_service import RegisterService


class TestRegisterServiceIntegrityError(unittest.TestCase):
    def test_register_responsavel_returns_none_on_integrity_error(self):
        service = RegisterService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()
        mock_session.commit.side_effect = IntegrityError("", "", Exception())

        result = asyncio.run(
            service.register_responsavel("race@test.com", "validpass123", "Race", mock_session)
        )

        self.assertIsNone(result)
        mock_session.rollback.assert_called_once()

    def test_register_aluno_returns_none_on_integrity_error(self):
        service = RegisterService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()
        mock_session.commit.side_effect = IntegrityError("", "", Exception())

        result = asyncio.run(
            service.register_aluno(
                "race_aluno@test.com",
                "validpass123",
                "Race",
                datetime.date(2010, 5, 1),
                ClassEnum.CLASS_5TH,
                mock_session,
            )
        )

        self.assertIsNone(result)
        mock_session.rollback.assert_called_once()


class TestRegisterServiceDuplicateEmail(unittest.TestCase):
    def test_register_responsavel_returns_none_when_email_exists(self):
        service = RegisterService()

        existing_user = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()

        result = asyncio.run(
            service.register_responsavel("dup@test.com", "validpass123", "Dup", mock_session)
        )

        self.assertIsNone(result)
        mock_session.add.assert_not_called()

    def test_register_aluno_returns_none_when_email_exists(self):
        service = RegisterService()

        existing_user = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()

        result = asyncio.run(
            service.register_aluno(
                "dup_aluno@test.com",
                "validpass123",
                "Dup Aluno",
                datetime.date(2010, 1, 1),
                ClassEnum.CLASS_6TH,
                mock_session,
            )
        )

        self.assertIsNone(result)
        mock_session.add.assert_not_called()


class TestRegisterServiceSuccess(unittest.TestCase):
    def test_register_responsavel_success_with_full_name(self):
        service = RegisterService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()

        result = asyncio.run(
            service.register_responsavel(
                "ok@test.com", "validpass123", "First Last", mock_session
            )
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["detail"], "Cadastro realizado. Aguardando aprovacao.")
        self.assertIn("id", result)
        mock_session.commit.assert_called_once()

    def test_register_responsavel_success_with_single_name(self):
        service = RegisterService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()

        result = asyncio.run(
            service.register_responsavel("solo@test.com", "validpass123", "Solo", mock_session)
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["detail"], "Cadastro realizado. Aguardando aprovacao.")

    def test_register_aluno_success(self):
        service = RegisterService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()

        result = asyncio.run(
            service.register_aluno(
                "stu@test.com",
                "validpass123",
                "Stu Dent",
                datetime.date(2010, 6, 15),
                ClassEnum.CLASS_7TH,
                mock_session,
            )
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["detail"], "Cadastro realizado.")
        self.assertIn("id", result)
        mock_session.commit.assert_called_once()
