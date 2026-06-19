"""Unit tests for the generic CSVProcessorService."""

import unittest

from pydantic import BaseModel, EmailStr, Field

import tests.keys_test  # noqa: F401
from md_backend.services.csv_processor_service import (
    CSVHeaderError,
    CSVProcessorService,
)

EXPECTED_HEADERS = {"first_name", "last_name", "email", "phone_number", "is_private"}

VALID_CSV = (
    "first_name,last_name,email,phone_number,is_private\r\n"
    "Ana,Silva,ana@test.com,11999990000,true\r\n"
    "Bruno,Souza,bruno@test.com,,false\r\n"
)

MISSING_COLUMN_CSV = "first_name,last_name,email,is_private\r\nAna,Silva,ana@test.com,true\r\n"

EXTRA_COLUMN_CSV = (
    "first_name,last_name,email,phone_number,is_private,extra_col\r\n"
    "Ana,Silva,ana@test.com,11999990000,true,oops\r\n"
)

INVALID_EMAIL_CSV = (
    "first_name,last_name,email,phone_number,is_private\r\n"
    "Ana,Silva,invalido.com,11999990000,true\r\n"
)


class SampleRow(BaseModel):
    """Minimal row model mirroring SchoolBatchRow for isolated engine tests."""

    first_name: str = Field(min_length=1)
    last_name: str | None = None
    email: EmailStr
    phone_number: str | None = None
    is_private: bool


class TestCSVProcessorServiceHeaders(unittest.TestCase):
    """Tests for the structural header validation stage."""

    def setUp(self):
        self.service = CSVProcessorService()

    def test_valid_headers_return_a_dict_reader(self):
        reader = self.service.validate_headers(VALID_CSV, EXPECTED_HEADERS)
        rows = list(reader)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["email"], "ana@test.com")

    def test_missing_column_raises_csv_header_error(self):
        with self.assertRaises(CSVHeaderError) as ctx:
            self.service.validate_headers(MISSING_COLUMN_CSV, EXPECTED_HEADERS)
        self.assertIn("missing columns", str(ctx.exception))

    def test_extra_column_raises_csv_header_error(self):
        with self.assertRaises(CSVHeaderError) as ctx:
            self.service.validate_headers(EXTRA_COLUMN_CSV, EXPECTED_HEADERS)
        self.assertIn("unexpected columns", str(ctx.exception))

    def test_empty_file_raises_csv_header_error(self):
        with self.assertRaises(CSVHeaderError):
            self.service.validate_headers("", EXPECTED_HEADERS)

    def test_decode_csv_returns_text(self):
        decoded = self.service.decode_csv(VALID_CSV.encode("utf-8"))
        self.assertEqual(decoded, VALID_CSV)

    def test_decode_csv_invalid_encoding_raises_csv_header_error(self):
        with self.assertRaises(CSVHeaderError):
            self.service.decode_csv(b"\xff\xfe\x00\x01", encoding="utf-8")


class TestCSVProcessorServiceRowValidation(unittest.TestCase):
    """Tests for the per-row Pydantic schema-validation stage."""

    def setUp(self):
        self.service = CSVProcessorService()

    def test_all_valid_rows_produce_no_errors(self):
        reader = self.service.validate_headers(VALID_CSV, EXPECTED_HEADERS)
        result = self.service.validate_rows(reader, SampleRow)

        self.assertEqual(result.total_processed, 2)
        self.assertEqual(len(result.valid_rows), 2)
        self.assertEqual(len(result.errors), 0)
        self.assertFalse(result.has_errors)

    def test_real_excel_row_numbers_are_preserved(self):
        reader = self.service.validate_headers(VALID_CSV, EXPECTED_HEADERS)
        result = self.service.validate_rows(reader, SampleRow)

        line_numbers = [line for line, _ in result.valid_rows_with_line]
        self.assertEqual(line_numbers, [2, 3])

    def test_invalid_email_is_collected_as_row_error(self):
        reader = self.service.validate_headers(INVALID_EMAIL_CSV, EXPECTED_HEADERS)
        result = self.service.validate_rows(reader, SampleRow)

        self.assertEqual(result.total_processed, 1)
        self.assertEqual(len(result.valid_rows), 0)
        self.assertTrue(result.has_errors)
        self.assertEqual(result.errors[0].row, 2)
        self.assertEqual(result.errors[0].email, "invalido.com")
        self.assertIn("email", result.errors[0].reason)

    def test_blank_optional_field_is_passed_through_as_empty_string(self):
        """The generic engine does not coerce blanks; that's the row model's job."""
        reader = self.service.validate_headers(VALID_CSV, EXPECTED_HEADERS)
        result = self.service.validate_rows(reader, SampleRow)

        bruno = next(row for row in result.valid_rows if row.email == "bruno@test.com")
        self.assertEqual(bruno.phone_number, "")
        self.assertFalse(bruno.is_private)


if __name__ == "__main__":
    unittest.main()
