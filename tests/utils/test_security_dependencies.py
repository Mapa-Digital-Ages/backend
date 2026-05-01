"""Tests for security dependency functions (get_current_approved_user, get_current_superadmin)."""

import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException

import tests.keys_test  # noqa: F401
from md_backend.models.db_models import GuardianStatusEnum
from md_backend.utils.security import (
    get_current_approved_user,
    get_current_superadmin,
    get_current_user,
)


def _build_user(
    *,
    is_active=True,
    has_guardian=False,
    guardian_status=GuardianStatusEnum.APPROVED,
    has_admin=False,
    is_superadmin=False,
):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "u@test.com"
    user.is_active = is_active

    if has_guardian:
        guardian = MagicMock()
        guardian.guardian_status = guardian_status
        user.guardian_profile = guardian
    else:
        user.guardian_profile = None

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
    session = AsyncMock()
    session.execute.return_value = mock_result
    return session


class TestGetCurrentUser(unittest.TestCase):
    def test_missing_credentials_raises_401(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_current_user(credentials=None))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, "Missing authorization header")


class TestGetCurrentApprovedUser(unittest.TestCase):
    def _payload(self, user_id):
        return {"sub": "u@test.com", "user_id": str(user_id)}

    def test_user_not_found_raises_401(self):
        session = _session_with_user(None)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                get_current_approved_user(
                    payload=self._payload(uuid.uuid4()), session=session
                )
            )
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, "User not found")

    def test_inactive_user_raises_403(self):
        user = _build_user(is_active=False)
        session = _session_with_user(user)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                get_current_approved_user(payload=self._payload(user.id), session=session)
            )
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Account deactivated")

    def test_guardian_waiting_raises_403(self):
        user = _build_user(
            has_guardian=True, guardian_status=GuardianStatusEnum.WAITING
        )
        session = _session_with_user(user)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                get_current_approved_user(payload=self._payload(user.id), session=session)
            )
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Account awaiting approval")

    def test_guardian_rejected_raises_403(self):
        user = _build_user(
            has_guardian=True, guardian_status=GuardianStatusEnum.REJECTED
        )
        session = _session_with_user(user)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                get_current_approved_user(payload=self._payload(user.id), session=session)
            )
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Account rejected")

    def test_approved_guardian_returns_user_dict(self):
        user = _build_user(
            has_guardian=True, guardian_status=GuardianStatusEnum.APPROVED
        )
        session = _session_with_user(user)
        result = asyncio.run(
            get_current_approved_user(payload=self._payload(user.id), session=session)
        )
        self.assertEqual(result["user_id"], str(user.id))
        self.assertEqual(result["email"], user.email)
        self.assertFalse(result["is_superadmin"])

    def test_admin_returns_superadmin_true(self):
        user = _build_user(has_admin=True, is_superadmin=True)
        session = _session_with_user(user)
        result = asyncio.run(
            get_current_approved_user(payload=self._payload(user.id), session=session)
        )
        self.assertTrue(result["is_superadmin"])


class TestGetCurrentSuperadmin(unittest.TestCase):
    def test_non_superadmin_raises_403(self):
        user = {"user_id": "x", "email": "u@test.com", "is_superadmin": False}
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_current_superadmin(user=user))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Access restricted to administrators")

    def test_superadmin_passes(self):
        user = {"user_id": "x", "email": "u@test.com", "is_superadmin": True}
        result = asyncio.run(get_current_superadmin(user=user))
        self.assertEqual(result, user)
