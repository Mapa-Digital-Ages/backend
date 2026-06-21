"""Unit tests for TrailReadService."""

import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

import tests.keys_test  # noqa: F401

from md_backend.services.trail.read_service import TrailReadService


def _make_row(
    path_id, path_name, content_name, subject_id, subject_name, subject_color, total_sub_paths
):
    path = MagicMock()
    path.id = path_id
    path.name = path_name
    path.description = "desc"

    content = MagicMock()
    content.name = content_name
    content.description = "content desc"

    subject = MagicMock()
    subject.id = subject_id
    subject.slug = None
    subject.name = subject_name
    subject.color = subject_color

    return (path, content, subject, total_sub_paths)


class TestTrailReadServiceListTrails(unittest.TestCase):
    def setUp(self):
        self.service = TrailReadService()
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
        row = _make_row(1, "Álgebra", "Conteúdo de Matemática", 2, "Matemática", "#FF0000", 3)
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
        self.assertEqual(trail["steps"], 3)
        self.assertEqual(trail["progress"], 0)

    def test_returns_completed_trail_when_status_is_completed(self):
        from md_backend.models.db_models import PathStatusEnum

        mock_session = AsyncMock()
        paths_result = MagicMock()
        paths_result.all.return_value = [_make_row(1, "Álgebra", "Conteúdo", 2, "Mat", "#F00", 3)]
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


class TestTrailReadServiceGetTrailDetail(unittest.TestCase):
    def setUp(self):
        self.service = TrailReadService()
        self.student_id = uuid.uuid4()
        self.path_id = 1

    def _run(self, coro):
        return asyncio.run(coro)

    def _mock_session_for_detail(self, sub_paths=None, sub_path_items=None, progress=None):
        mock_session = AsyncMock()
        path = MagicMock()
        path.id = 1
        path.name = "Álgebra"
        path.description = "desc"
        content = MagicMock()
        content.name = "Conteúdo"
        content.description = "cdesc"
        subject = MagicMock()
        subject.id = 2
        subject.slug = None
        subject.name = "Matemática"
        subject.color = "#F00"

        q1_result = MagicMock()
        q1_result.one_or_none.return_value = (path, content, subject)
        q2_result = MagicMock()
        q2_result.scalars.return_value.all.return_value = sub_paths or []
        q3_result = MagicMock()
        q3_result.scalar_one_or_none.return_value = progress
        item_results = []
        for _ in sub_paths or []:
            item_result = MagicMock()
            item_result.scalars.return_value.all.return_value = sub_path_items or []
            item_results.append(item_result)
        mock_session.execute.side_effect = [q1_result, q2_result, q3_result] + item_results
        return mock_session

    def test_returns_none_when_path_not_found(self):
        mock_session = AsyncMock()
        result = MagicMock()
        result.one_or_none.return_value = None
        mock_session.execute.return_value = result

        detail = self._run(
            self.service.get_trail_detail(mock_session, self.student_id, self.path_id)
        )

        self.assertIsNone(detail)

    def test_returns_trail_detail_with_no_sub_paths(self):
        detail = self._run(
            self.service.get_trail_detail(
                self._mock_session_for_detail(sub_paths=[]),
                self.student_id,
                self.path_id,
            )
        )

        self.assertIsNotNone(detail)
        self.assertEqual(detail["id"], "1")
        self.assertEqual(detail["steps"], [])
        self.assertEqual(detail["progress"], 0)

    def test_step_status_is_available_when_student_is_on_that_sub_path(self):
        from md_backend.models.db_models import PathStatusEnum

        sub = MagicMock()
        sub.id = 10
        progress = MagicMock()
        progress.current_sub_path = 10
        progress.path_status = PathStatusEnum.ON_GOING

        detail = self._run(
            self.service.get_trail_detail(
                self._mock_session_for_detail(sub_paths=[sub], progress=progress),
                self.student_id,
                self.path_id,
            )
        )

        self.assertEqual(detail["steps"][0]["status"], "available")

    def test_step_after_current_is_locked_when_no_progress(self):
        sub1 = MagicMock()
        sub1.id = 10
        sub2 = MagicMock()
        sub2.id = 20

        detail = self._run(
            self.service.get_trail_detail(
                self._mock_session_for_detail(sub_paths=[sub1, sub2]),
                self.student_id,
                self.path_id,
            )
        )

        self.assertEqual(detail["steps"][0]["status"], "available")
        self.assertEqual(detail["steps"][1]["status"], "locked")
