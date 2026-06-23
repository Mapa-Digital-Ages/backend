"""Unit tests for TrailReadService."""

import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

import tests.keys_test  # noqa: F401

from md_backend.models.db_models import PathStatusEnum, TypeItemEnum
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
        self.service.sub_step_progress_by_path = AsyncMock(
            return_value={(self.student_id, 1): {"completed": 0, "total": 3, "progress": 0}}
        )

        result = self._run(self.service.list_trails(mock_session, self.student_id))

        self.assertEqual(len(result), 1)
        trail = result[0]
        self.assertEqual(trail["id"], "1")
        self.assertEqual(trail["name"], "Álgebra")
        self.assertEqual(trail["subject"]["label"], "Matemática")
        self.assertEqual(trail["steps"], 3)
        self.assertEqual(trail["progress"], 0)

    def test_returns_completed_trail_when_status_is_completed(self):
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
        self.service.sub_step_progress_by_path = AsyncMock(
            return_value={(self.student_id, 1): {"completed": 3, "total": 3, "progress": 100}}
        )

        result = self._run(self.service.list_trails(mock_session, self.student_id))

        self.assertEqual(result[0]["progress"], 100)
        self.assertEqual(result[0]["completed"], 3)


class TestTrailReadServiceSubStepProgress(unittest.TestCase):
    def test_counts_completed_sub_steps_across_one_or_multiple_steps(self):
        service = TrailReadService()
        student_id = uuid.uuid4()
        session = AsyncMock()

        def resource_item(item_id: int, group_key: str):
            item = MagicMock()
            item.id = item_id
            item.type_item = TypeItemEnum.RESOURCE
            item.group_key = group_key
            item.exercise = None
            return item

        positions_result = MagicMock()
        positions_result.all.return_value = [
            (1, 10, 1),
            (2, 20, 1),
            (2, 30, 2),
        ]
        item_result = MagicMock()
        item_result.all.return_value = [
            (resource_item(1, "p1-a"), 1, 10, 1),
            (resource_item(2, "p1-b"), 1, 10, 1),
            (resource_item(3, "p2-a"), 2, 20, 1),
            (resource_item(4, "p2-b"), 2, 20, 1),
            (resource_item(5, "p2-c"), 2, 30, 2),
            (resource_item(6, "p2-d"), 2, 30, 2),
        ]
        path_one_progress = MagicMock(
            student_id=student_id,
            path_id=1,
            current_sub_path=10,
            path_status=PathStatusEnum.ON_GOING,
        )
        path_two_progress = MagicMock(
            student_id=student_id,
            path_id=2,
            current_sub_path=20,
            path_status=PathStatusEnum.ON_GOING,
        )
        progress_result = MagicMock()
        progress_result.scalars.return_value.all.return_value = [
            path_one_progress,
            path_two_progress,
        ]
        completed_result = MagicMock()
        completed_result.all.return_value = [
            (student_id, 1, 1),
            (student_id, 2, 3),
        ]
        session.execute.side_effect = [
            positions_result,
            item_result,
            progress_result,
            completed_result,
        ]

        result = asyncio.run(
            service.sub_step_progress_by_path(
                session=session,
                student_ids=[student_id],
                path_ids=[1, 2],
            )
        )

        self.assertEqual(result[(student_id, 1)]["progress"], 50)
        self.assertEqual(result[(student_id, 2)]["progress"], 25)


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

    def test_detail_progress_counts_completed_sub_steps_across_all_steps(self):
        first_step = MagicMock(id=10, title="Etapa 1", description=None)
        second_step = MagicMock(id=20, title="Etapa 2", description=None)
        progress = MagicMock(
            current_sub_path=10,
            path_status=PathStatusEnum.ON_GOING,
        )
        self.service._build_sub_steps = AsyncMock(
            side_effect=[
                [
                    {"id": "a", "status": "completed"},
                    {"id": "b", "status": "available"},
                ],
                [
                    {"id": "c", "status": "locked"},
                    {"id": "d", "status": "locked"},
                ],
            ]
        )

        detail = self._run(
            self.service.get_trail_detail(
                self._mock_session_for_detail(
                    sub_paths=[first_step, second_step],
                    progress=progress,
                ),
                self.student_id,
                self.path_id,
            )
        )

        self.assertEqual(detail["progress"], 25)
        self.assertEqual(detail["completed_steps"], 0)

    def test_question_flow_selects_the_requested_quiz_group(self):
        session = AsyncMock()
        subject = MagicMock(id=2, slug=None, name="Matemática", color="#F00")
        subject_result = MagicMock()
        subject_result.scalar_one_or_none.return_value = subject
        session.execute.return_value = subject_result
        self.service._build_sub_steps = AsyncMock(
            return_value=[
                {
                    "id": "quiz-10-first",
                    "item_ids": ["101"],
                    "kind": "question",
                    "title": "Primeiro quiz",
                    "status": "completed",
                    "questions": [{"id": "1"}],
                },
                {
                    "id": "quiz-10-second",
                    "item_ids": ["102"],
                    "kind": "question",
                    "title": "Segundo quiz",
                    "status": "available",
                    "questions": [{"id": "2"}],
                },
            ]
        )

        flow = self._run(
            self.service.get_question_flow(
                session=session,
                path_id=1,
                sub_path_id=10,
                sub_step_id="quiz-10-second",
                student_id=self.student_id,
            )
        )

        self.assertEqual(flow["subStepId"], "quiz-10-second")
        self.assertEqual(flow["itemIds"], ["102"])
        self.assertEqual(flow["questions"], [{"id": "2"}])

    def test_legacy_question_flow_is_empty_when_step_has_no_quiz(self):
        session = AsyncMock()
        subject = MagicMock(id=2, slug=None, name="Matemática", color="#F00")
        subject_result = MagicMock()
        subject_result.scalar_one_or_none.return_value = subject
        session.execute.return_value = subject_result
        self.service._build_sub_steps = AsyncMock(return_value=[])

        flow = self._run(
            self.service.get_question_flow(
                session=session,
                path_id=1,
                sub_path_id=10,
                student_id=self.student_id,
            )
        )

        self.assertEqual(flow["questions"], [])
        self.assertEqual(flow["subStepId"], "quiz-10")
