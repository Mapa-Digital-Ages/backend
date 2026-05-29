"""Unit tests for PathService."""

import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

import tests.keys_test  # noqa: F401
from md_backend.services.path_service import PathService


def _make_row(path_id, path_name, content_name, subject_id, subject_name, subject_color, total_sub_paths):
    path = MagicMock()
    path.id = path_id
    path.name = path_name
    path.description = "desc"

    content = MagicMock()
    content.name = content_name
    content.description = "content desc"

    subject = MagicMock()
    subject.id = subject_id
    subject.name = subject_name
    subject.color = subject_color

    return (path, content, subject, total_sub_paths)


class TestPathServiceListTrails(unittest.TestCase):
    def setUp(self):
        self.service = PathService()
        self.student_id = uuid.uuid4()

    def _run(self, coro):
        return asyncio.run(coro)

    def test_returns_empty_list_when_no_paths(self):
        mock_session = AsyncMock()
        paths_result = MagicMock()
        paths_result.all.return_value = []
        progress_result = MagicMock()
        progress_result.scalars.return_value.all.return_value = []

        mock_session.execute.side_effect = [paths_result, progress_result]

        result = self._run(self.service.list_trails(mock_session, self.student_id))
        self.assertEqual(result, [])

    def test_returns_trail_with_zero_progress_when_no_student_progress(self):
        mock_session = AsyncMock()

        row = _make_row(
            path_id=1,
            path_name="Álgebra",
            content_name="Conteúdo de Matemática",
            subject_id=2,
            subject_name="Matemática",
            subject_color="#FF0000",
            total_sub_paths=3,
        )
        paths_result = MagicMock()
        paths_result.all.return_value = [row]

        progress_result = MagicMock()
        progress_result.scalars.return_value.all.return_value = []

        mock_session.execute.side_effect = [paths_result, progress_result]

        result = self._run(self.service.list_trails(mock_session, self.student_id))

        self.assertEqual(len(result), 1)
        trail = result[0]
        self.assertEqual(trail["id"], "1")
        self.assertEqual(trail["name"], "Álgebra")
        self.assertEqual(trail["subject"]["label"], "Matemática")
        self.assertEqual(trail["subject"]["color"], "#FF0000")
        self.assertEqual(trail["steps"], 3)
        self.assertEqual(trail["progress"], 0)
        self.assertIsNone(trail["time_estimate"])

    def test_returns_completed_trail_when_status_is_completed(self):
        from md_backend.models.db_models import PathStatusEnum

        mock_session = AsyncMock()

        row = _make_row(1, "Álgebra", "Conteúdo", 2, "Matemática", "#FF0000", 3)
        paths_result = MagicMock()
        paths_result.all.return_value = [row]

        progress = MagicMock()
        progress.path_id = 1
        progress.path_status = PathStatusEnum.COMPLETED
        progress.current_sub_path = 99
        progress_result = MagicMock()
        progress_result.scalars.return_value.all.return_value = [progress]

        mock_session.execute.side_effect = [paths_result, progress_result]

        result = self._run(self.service.list_trails(mock_session, self.student_id))

        self.assertEqual(result[0]["progress"], 100)
        self.assertEqual(result[0]["completed"], 3)


class TestPathServiceGetTrailDetail(unittest.TestCase):
    def setUp(self):
        self.service = PathService()
        self.student_id = uuid.uuid4()
        self.path_id = 1

    def _run(self, coro):
        return asyncio.run(coro)

    def _mock_session_for_detail(
        self,
        path_name="Álgebra",
        sub_paths=None,
        sub_path_items=None,
        progress=None,
    ):
        """Build an AsyncMock session returning fixed data for get_trail_detail."""
        mock_session = AsyncMock()

        path = MagicMock(); path.id = 1; path.name = path_name; path.description = "desc"
        content = MagicMock(); content.name = "Conteúdo"; content.description = "cdesc"
        subject = MagicMock(); subject.id = 2; subject.name = "Matemática"; subject.color = "#F00"

        q1_result = MagicMock()
        q1_result.one_or_none.return_value = (path, content, subject)

        _sub_paths = sub_paths or []
        q2_result = MagicMock()
        q2_result.scalars.return_value.all.return_value = _sub_paths

        q3_result = MagicMock()
        q3_result.scalar_one_or_none.return_value = progress

        item_results = []
        for _ in _sub_paths:
            r = MagicMock()
            r.scalars.return_value.all.return_value = sub_path_items or []
            item_results.append(r)

        mock_session.execute.side_effect = [q1_result, q2_result, q3_result] + item_results
        return mock_session

    def test_returns_none_when_path_not_found(self):
        mock_session = AsyncMock()
        q1_result = MagicMock()
        q1_result.one_or_none.return_value = None
        mock_session.execute.return_value = q1_result

        result = self._run(
            self.service.get_trail_detail(mock_session, self.student_id, self.path_id)
        )
        self.assertIsNone(result)

    def test_returns_trail_detail_with_no_sub_paths(self):
        mock_session = self._mock_session_for_detail(sub_paths=[], sub_path_items=[])

        result = self._run(
            self.service.get_trail_detail(mock_session, self.student_id, self.path_id)
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "1")
        self.assertEqual(result["title"], "Álgebra")
        self.assertEqual(result["subject"]["label"], "Matemática")
        self.assertEqual(result["steps"], [])
        self.assertEqual(result["progress"], 0)
        self.assertIsNone(result["level_label"])
        self.assertIsNone(result["time_estimate"])

    def test_step_status_is_available_when_student_is_on_that_sub_path(self):
        from md_backend.models.db_models import PathStatusEnum

        sub = MagicMock(); sub.id = 10; sub.difficulty = None

        progress = MagicMock()
        progress.current_sub_path = 10
        progress.path_status = PathStatusEnum.ON_GOING

        mock_session = self._mock_session_for_detail(
            sub_paths=[sub], sub_path_items=[], progress=progress
        )

        result = self._run(
            self.service.get_trail_detail(mock_session, self.student_id, self.path_id)
        )

        self.assertEqual(len(result["steps"]), 1)
        self.assertEqual(result["steps"][0]["status"], "available")

    def test_step_before_current_is_completed(self):
        from md_backend.models.db_models import PathStatusEnum

        sub1 = MagicMock(); sub1.id = 10; sub1.difficulty = None
        sub2 = MagicMock(); sub2.id = 20; sub2.difficulty = None

        progress = MagicMock()
        progress.current_sub_path = 20
        progress.path_status = PathStatusEnum.ON_GOING

        mock_session = self._mock_session_for_detail(
            sub_paths=[sub1, sub2], sub_path_items=[], progress=progress
        )

        result = self._run(
            self.service.get_trail_detail(mock_session, self.student_id, self.path_id)
        )

        self.assertEqual(result["steps"][0]["status"], "completed")
        self.assertEqual(result["steps"][1]["status"], "available")

    def test_step_after_current_is_locked_when_no_progress(self):
        sub1 = MagicMock(); sub1.id = 10; sub1.difficulty = None
        sub2 = MagicMock(); sub2.id = 20; sub2.difficulty = None

        mock_session = self._mock_session_for_detail(
            sub_paths=[sub1, sub2], sub_path_items=[], progress=None
        )

        result = self._run(
            self.service.get_trail_detail(mock_session, self.student_id, self.path_id)
        )

        self.assertEqual(result["steps"][0]["status"], "available")
        self.assertEqual(result["steps"][1]["status"], "locked")
