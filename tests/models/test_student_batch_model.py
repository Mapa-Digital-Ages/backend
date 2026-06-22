import unittest

from pydantic import ValidationError

from md_backend.models.api_models import StudentBatchRow
from md_backend.models.db_models import ClassEnum


class TestStudentBatchRow(unittest.TestCase):
    def _payload(self, student_class: str) -> dict:
        return {
            "first_name": "Joao",
            "last_name": "Silva",
            "email": "joao.silva@example.com",
            "phone_number": "11999999999",
            "birth_date": "2013-05-20",
            "student_class": student_class,
            "school_email": "escola.modelo@example.com",
            "guardian_email": "maria.silva@example.com",
        }

    def test_csv_year_numbers_map_to_internal_class_enum(self):
        expected = {
            "5": ClassEnum.CLASS_5TH,
            "6": ClassEnum.CLASS_6TH,
            "7": ClassEnum.CLASS_7TH,
            "8": ClassEnum.CLASS_8TH,
            "9": ClassEnum.CLASS_9TH,
        }

        for csv_value, class_enum in expected.items():
            with self.subTest(csv_value=csv_value):
                row = StudentBatchRow(**self._payload(csv_value))
                self.assertEqual(row.student_class, class_enum)

    def test_legacy_class_label_is_rejected_in_batch_csv(self):
        with self.assertRaises(ValidationError) as context:
            StudentBatchRow(**self._payload("5th class"))

        self.assertIn(
            "student_class must be one of ['5', '6', '7', '8', '9']",
            str(context.exception),
        )
