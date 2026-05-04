"""Tests for security utilities."""

import asyncio
import unittest

import jwt

import tests.keys_test  # noqa: F401
from md_backend.utils.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from md_backend.utils.settings import settings


class TestPasswordHashing(unittest.TestCase):
    def test_hash_password_returns_bcrypt_hash(self):
        hashed = asyncio.run(hash_password("testpassword"))
        self.assertTrue(hashed.startswith("$2b$"))

    def test_verify_password_correct(self):
        hashed = asyncio.run(hash_password("testpassword"))
        self.assertTrue(asyncio.run(verify_password("testpassword", hashed)))

    def test_verify_password_incorrect(self):
        hashed = asyncio.run(hash_password("testpassword"))
        self.assertFalse(asyncio.run(verify_password("wrongpassword", hashed)))


class TestJWT(unittest.TestCase):
    def test_create_and_decode_token(self):
        data = {"sub": "user@test.com", "user_id": 1}
        token = create_access_token(data)
        decoded = decode_access_token(token)
        self.assertEqual(decoded["sub"], "user@test.com")
        self.assertEqual(decoded["user_id"], 1)
        self.assertIn("exp", decoded)

    def test_decode_invalid_token_raises(self):
        with self.assertRaises(jwt.InvalidTokenError):
            decode_access_token("invalid.token.here")

    def test_decode_tampered_token_raises(self):
        token = create_access_token({"sub": "user@test.com"})
        tampered = token + "x"
        with self.assertRaises(jwt.InvalidTokenError):
            decode_access_token(tampered)

    def test_token_with_wrong_secret_raises(self):
        token = jwt.encode({"sub": "user@test.com"}, "wrong-secret", algorithm="HS256")
        with self.assertRaises(jwt.InvalidTokenError):
            decode_access_token(token)
