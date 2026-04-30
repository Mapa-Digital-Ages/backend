"""Unit tests for GuardianService."""

import asyncio
import unittest
from unittest.mock import MagicMock

from md_backend.models.db_models import GuardianStatusEnum
from md_backend.services.guardian_service import GuardianService


class TestGuardianServiceSerialization(unittest.TestCase):
    def setUp(self):
        self.service = GuardianService()
        self.user_profile = MagicMock()
        self.user_profile.id = "123e4567-e89b-12d3-a456-426614174000"
        self.user_profile.first_name = "Paulo"
        self.user_profile.last_name = "Silva"
        self.user_profile.email = "paulo.silva@example.com"
        self.user_profile.phone_number = None
        self.user_profile.password = "secret"

        self.guardian_profile = MagicMock()
        self.guardian_profile.guardian_status = GuardianStatusEnum.APPROVED

    def test_serialize_guardian_excludes_password(self):
        result = self.service._serialize_guardian(self.user_profile, self.guardian_profile)

        self.assertEqual(result["id"], str(self.user_profile.id))
        self.assertEqual(result["guardian_status"], "approved")
        self.assertNotIn("password", result)
        self.assertEqual(result["phone_number"], "")


class TestGuardianServiceStatusFilter(unittest.TestCase):
    def setUp(self):
        self.service = GuardianService()

    def test_parse_status_filter_accepts_string_values(self):
        self.assertEqual(
            self.service._parse_status_filter("waiting"),
            GuardianStatusEnum.WAITING,
        )
        self.assertEqual(
            self.service._parse_status_filter("approved"),
            GuardianStatusEnum.APPROVED,
        )
        self.assertEqual(
            self.service._parse_status_filter("rejected"),
            GuardianStatusEnum.REJECTED,
        )

    def test_parse_status_filter_accepts_enum_values(self):
        self.assertEqual(
            self.service._parse_status_filter(GuardianStatusEnum.WAITING),
            GuardianStatusEnum.WAITING,
        )

    def test_parse_status_filter_raises_for_invalid_status(self):
        with self.assertRaises(ValueError):
            self.service._parse_status_filter("invalid")
