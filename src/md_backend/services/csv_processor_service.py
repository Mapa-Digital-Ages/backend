"""Generic CSV batch-import engine (All-or-Nothing validation pipeline).

This service is intentionally decoupled from any single domain (school,
student, etc.). It receives the raw CSV bytes plus a fixed header template
and a Pydantic row model, and returns a structured result describing either
every validated row (success) or every error found (abort) — never a mix.

Consumers (e.g. ``SchoolService``) are responsible for the second half of
the "semáforo": the database-integrity check (duplicate emails) and the
actual persistence step. This service only handles steps 1 and 2A of the
pipeline: structural header validation and per-row Pydantic validation.
"""

import csv
import io
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError


@dataclass
class CSVRowError:
    """A single row-level validation error."""

    row: int
    email: str
    reason: str
    # Dados brutos da linha para exibição no relatório de erros
    first_name: str = ""
    last_name: str = ""
    phone_number: str = ""
    is_private: str = ""


@dataclass
class CSVValidationResult[RowModelT: BaseModel]:
    """Outcome of the in-memory validation pass (schema validation only).

    Every source row ends up in exactly one of ``valid_rows`` or ``errors``.
    ``total_processed`` always equals ``len(valid_rows) + len(errors)``.

    ``valid_rows_with_line`` mirrors ``valid_rows`` but keeps the original
    1-indexed Excel/CSV row number (header = row 1) alongside each validated
    model, so a later integrity-check stage can still report errors against
    the row the user actually sees in their spreadsheet.
    """

    valid_rows: list[RowModelT] = field(default_factory=list)
    valid_rows_with_line: list[tuple[int, RowModelT]] = field(default_factory=list)
    errors: list[CSVRowError] = field(default_factory=list)
    total_processed: int = 0

    @property
    def has_errors(self) -> bool:
        """Return whether any row failed schema validation."""
        return len(self.errors) > 0


class CSVHeaderError(ValueError):
    """Raised when the uploaded file's headers don't match the expected template."""


class CSVProcessorService:
    """Generic, reusable CSV parsing + schema-validation engine.

    The service never touches the database and never raises ``HTTPException``
    (per project convention, only routers do that). Structural header
    mismatches raise ``CSVHeaderError``, which the caller maps to a 400.
    """

    def decode_csv(self, raw_content: bytes, encoding: str = "utf-8") -> str:
        """Safely decode the raw uploaded bytes into text.

        Args:
            raw_content: The raw bytes read from the ``UploadFile``.
            encoding: Text encoding to use when decoding.

        Returns:
            The decoded CSV content as a string.

        Raises:
            CSVHeaderError: If the content cannot be decoded with ``encoding``.
        """
        try:
            return raw_content.decode(encoding)
        except UnicodeDecodeError as exc:
            raise CSVHeaderError(f"File is not valid {encoding} text.") from exc

    def validate_headers(self, content: str, expected_headers: set[str]) -> csv.DictReader:
        """Parse the CSV text and enforce a strict, fixed header set.

        Args:
            content: Decoded CSV text.
            expected_headers: The exact set of column names the template requires.

        Returns:
            A ``csv.DictReader`` positioned at the first data row.

        Raises:
            CSVHeaderError: If headers are missing, extra, or the file has none at all.
        """
        reader = csv.DictReader(io.StringIO(content))
        actual_headers = set(reader.fieldnames or [])

        if actual_headers != expected_headers:
            missing = expected_headers - actual_headers
            extra = actual_headers - expected_headers
            details = []
            if missing:
                details.append(f"missing columns: {sorted(missing)}")
            if extra:
                details.append(f"unexpected columns: {sorted(extra)}")
            raise CSVHeaderError(
                "CSV header does not match the expected template ("
                + "; ".join(details or ["no headers found"])
                + ")."
            )

        return reader

    def validate_rows[RowModelT: BaseModel](
        self,
        reader: csv.DictReader,
        row_model: type[RowModelT],
    ) -> CSVValidationResult[RowModelT]:
        """Run the Pydantic schema-validation pass over every CSV row.

        Does not touch the database — this is purely the in-memory "semáforo"
        stage. Real Excel/spreadsheet row numbers (header = row 1) are
        preserved via ``enumerate(reader, start=2)``.

        Args:
            reader: A ``csv.DictReader`` already validated by ``validate_headers``.
            row_model: The Pydantic model used to validate each row dict.

        Returns:
            A ``CSVValidationResult`` with every row sorted into ``valid_rows``
            or ``errors``.
        """
        result: CSVValidationResult[RowModelT] = CSVValidationResult()

        for line_number, raw_row in enumerate(reader, start=2):
            result.total_processed += 1
            try:
                validated = row_model(**raw_row)
            except ValidationError as exc:
                result.errors.append(
                    CSVRowError(
                        row=line_number,
                        email=raw_row.get("email", ""),
                        reason=self._format_validation_error(exc),
                        first_name=raw_row.get("first_name", ""),
                        last_name=raw_row.get("last_name", ""),
                        phone_number=raw_row.get("phone_number", ""),
                        is_private=raw_row.get("is_private", ""),
                    )
                )
                continue

            result.valid_rows.append(validated)
            result.valid_rows_with_line.append((line_number, validated))

        return result

    def _format_validation_error(self, exc: ValidationError) -> str:
        """Collapse a Pydantic ``ValidationError`` into a single human-readable reason."""
        first_error = exc.errors()[0]
        field_name = ".".join(str(part) for part in first_error["loc"]) or "value"
        return f"{field_name}: {first_error['msg']}"
