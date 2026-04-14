"""Tests for the validate service."""

import asyncio
import unittest

import tests.keys_test  # noqa: F401
from md_backend.services.valdiate_service import ValidateService


class TestValidateService(unittest.TestCase):
    def test_process_text(self):
        service = ValidateService()
        result = asyncio.run(service.process_text("hello", "alice"))
        self.assertEqual(result, "alice sent the message 'hello' with variable test")
