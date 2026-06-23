"""Integration tests for trail (path) endpoints."""

import asyncio
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

import tests.keys_test  # noqa: F401
from md_backend.main import app
from md_backend.utils.database import engine
from tests.helpers import get_admin_headers


def _create_student(client, admin_headers):
    """Create a student and return (student_id, auth_headers)."""
    email = f"trail_student_{uuid.uuid4().hex[:8]}@example.com"
    payload = {
        "first_name": "Trail",
        "last_name": "Student",
        "email": email,
        "password": "securepass123",
        "birth_date": "2010-05-20",
        "student_class": "5th class",
    }
    resp = client.post("/api/student", json=payload, headers=admin_headers)
    student_id = resp.json()["user_id"]
    token_resp = client.post("/api/login", json={"email": email, "password": "securepass123"})
    token = token_resp.json()["token"]
    return student_id, {"Authorization": f"Bearer {token}"}


def _seed_trail(student_id: str) -> dict:
    """Seed a full trail (content, two sub-paths, a quiz, a transition, progress).

    Returns a dict of ids: path_id, sub_path_id (the quiz step), next_sub_path_id,
    resource_id, exercise_id, correct_option_id.
    """

    async def _insert():
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO subjects (name, slug, color) VALUES (:n, :s, :c) "
                    "ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name"
                ),
                {"n": "Matemática Trail Test", "s": "matematica-trail-test", "c": "#FF0000"},
            )
            subject_id = (
                await conn.execute(
                    text("SELECT id FROM subjects WHERE slug = 'matematica-trail-test'")
                )
            ).scalar_one()

            content_name = f"Álgebra Trail Test {uuid.uuid4().hex[:6]}"
            content_id = (
                await conn.execute(
                    text(
                        "INSERT INTO contents (subject_id, name, description) "
                        "VALUES (:sid, :n, :d) RETURNING id"
                    ),
                    {"sid": subject_id, "n": content_name, "d": "desc"},
                )
            ).scalar_one()

            path_name = f"Trilha de Álgebra {uuid.uuid4().hex[:6]}"
            path_id = (
                await conn.execute(
                    text(
                        "INSERT INTO paths (content_id, name, description) "
                        "VALUES (:cid, :n, :d) RETURNING id"
                    ),
                    {"cid": content_id, "n": path_name, "d": "trilha desc"},
                )
            ).scalar_one()

            sub_path_id = (
                await conn.execute(
                    text(
                        "INSERT INTO sub_paths (path_id, difficulty) "
                        "VALUES (:pid, 'EASY') RETURNING id"
                    ),
                    {"pid": path_id},
                )
            ).scalar_one()
            next_sub_path_id = (
                await conn.execute(
                    text(
                        "INSERT INTO sub_paths (path_id, difficulty) "
                        "VALUES (:pid, 'MEDIUM') RETURNING id"
                    ),
                    {"pid": path_id},
                )
            ).scalar_one()

            resource_id = (
                await conn.execute(
                    text(
                        "INSERT INTO resources (content_id, type, title, file_url) "
                        "VALUES (:cid, 'VIDEO', :t, :u) RETURNING id"
                    ),
                    {"cid": content_id, "t": "Vídeo de Introdução", "u": "https://e.com/v.mp4"},
                )
            ).scalar_one()

            exercise_id = (
                await conn.execute(
                    text(
                        "INSERT INTO exercises (content_id, statement, difficulty) "
                        "VALUES (:cid, :s, 'EASY') RETURNING id"
                    ),
                    {"cid": content_id, "s": "Quanto é 2x+4=10?"},
                )
            ).scalar_one()
            await conn.execute(
                text(
                    "INSERT INTO options (exercise_id, text, correct) VALUES (:eid, 'x=2', false)"
                ),
                {"eid": exercise_id},
            )
            correct_option_id = (
                await conn.execute(
                    text(
                        "INSERT INTO options (exercise_id, text, correct) "
                        "VALUES (:eid, 'x=3', true) RETURNING id"
                    ),
                    {"eid": exercise_id},
                )
            ).scalar_one()

            resource_item_id = (
                await conn.execute(
                    text(
                        "INSERT INTO sub_paths_item (sub_path_id, type_item, resource_id) "
                        "VALUES (:spid, 'RESOURCE', :rid) RETURNING id"
                    ),
                    {"spid": sub_path_id, "rid": resource_id},
                )
            ).scalar_one()
            exercise_item_id = (
                await conn.execute(
                    text(
                        "INSERT INTO sub_paths_item (sub_path_id, type_item, exercise_id) "
                        "VALUES (:spid, 'EXERCISE', :eid) RETURNING id"
                    ),
                    {"spid": sub_path_id, "eid": exercise_id},
                )
            ).scalar_one()

            await conn.execute(
                text(
                    "INSERT INTO path_transition "
                    "(sub_path_origin_id, sub_path_destination_id, rule_type) "
                    "VALUES (:o, :d, 'STANDARD')"
                ),
                {"o": sub_path_id, "d": next_sub_path_id},
            )

            await conn.execute(
                text(
                    "INSERT INTO student_path_progress "
                    "(student_id, path_id, current_sub_path, path_status) "
                    "VALUES (:sid, :pid, :spid, 'on_going') "
                    "ON CONFLICT DO NOTHING"
                ),
                {"sid": student_id, "pid": path_id, "spid": sub_path_id},
            )

            return {
                "path_id": path_id,
                "sub_path_id": sub_path_id,
                "next_sub_path_id": next_sub_path_id,
                "resource_id": resource_id,
                "resource_item_id": resource_item_id,
                "exercise_id": exercise_id,
                "exercise_item_id": exercise_item_id,
                "correct_option_id": correct_option_id,
            }

    return asyncio.run(_insert())


def _add_second_question_sub_step(seed: dict) -> dict:
    """Add a second, separately grouped quiz to the seeded sub-path."""

    async def _insert():
        async with engine.begin() as conn:
            content_id = (
                await conn.execute(
                    text("SELECT content_id FROM paths WHERE id = :path_id"),
                    {"path_id": seed["path_id"]},
                )
            ).scalar_one()
            exercise_id = (
                await conn.execute(
                    text(
                        "INSERT INTO exercises (content_id, statement, difficulty) "
                        "VALUES (:content_id, :statement, 'EASY') RETURNING id"
                    ),
                    {
                        "content_id": content_id,
                        "statement": "Quanto é 3 + 4?",
                    },
                )
            ).scalar_one()
            await conn.execute(
                text(
                    "INSERT INTO options (exercise_id, text, correct) "
                    "VALUES (:exercise_id, '6', false)"
                ),
                {"exercise_id": exercise_id},
            )
            correct_option_id = (
                await conn.execute(
                    text(
                        "INSERT INTO options (exercise_id, text, correct) "
                        "VALUES (:exercise_id, '7', true) RETURNING id"
                    ),
                    {"exercise_id": exercise_id},
                )
            ).scalar_one()
            item_id = (
                await conn.execute(
                    text(
                        "INSERT INTO sub_paths_item "
                        '(sub_path_id, type_item, exercise_id, group_key, title, "order") '
                        "VALUES (:sub_path_id, 'EXERCISE', :exercise_id, "
                        "'second-quiz', 'Segundo questionário', 2) RETURNING id"
                    ),
                    {
                        "sub_path_id": seed["sub_path_id"],
                        "exercise_id": exercise_id,
                    },
                )
            ).scalar_one()
            return {
                "exercise_id": exercise_id,
                "correct_option_id": correct_option_id,
                "item_id": item_id,
                "sub_step_id": f"quiz-{seed['sub_path_id']}-second-quiz",
            }

    return asyncio.run(_insert())


def _seed_incomplete_path() -> int:
    """Insert a path with one sub-path but NO items (not playable). Returns path_id."""

    async def _insert():
        async with engine.begin() as conn:
            subject_id = (
                await conn.execute(
                    text("SELECT id FROM subjects WHERE slug = 'matematica-trail-test'")
                )
            ).scalar_one()
            content_id = (
                await conn.execute(
                    text(
                        "INSERT INTO contents (subject_id, name, description) "
                        "VALUES (:sid, :n, 'd') RETURNING id"
                    ),
                    {"sid": subject_id, "n": f"Empty Content {uuid.uuid4().hex[:6]}"},
                )
            ).scalar_one()
            path_id = (
                await conn.execute(
                    text(
                        "INSERT INTO paths (content_id, name, description) "
                        "VALUES (:cid, :n, 'd') RETURNING id"
                    ),
                    {"cid": content_id, "n": f"Empty Trail {uuid.uuid4().hex[:6]}"},
                )
            ).scalar_one()
            await conn.execute(
                text("INSERT INTO sub_paths (path_id, difficulty) VALUES (:pid, 'EASY')"),
                {"pid": path_id},
            )
            return path_id

    return asyncio.run(_insert())


def _seed_path_with_optionless_exercise() -> dict:
    """Path whose only item is an exercise with NO options (unanswerable quiz)."""

    async def _insert():
        async with engine.begin() as conn:
            subject_id = (
                await conn.execute(
                    text("SELECT id FROM subjects WHERE slug = 'matematica-trail-test'")
                )
            ).scalar_one()
            content_id = (
                await conn.execute(
                    text(
                        "INSERT INTO contents (subject_id, name, description) "
                        "VALUES (:sid, :n, 'd') RETURNING id"
                    ),
                    {"sid": subject_id, "n": f"NoOpt Content {uuid.uuid4().hex[:6]}"},
                )
            ).scalar_one()
            path_id = (
                await conn.execute(
                    text(
                        "INSERT INTO paths (content_id, name, description) "
                        "VALUES (:cid, :n, 'd') RETURNING id"
                    ),
                    {"cid": content_id, "n": f"NoOpt Trail {uuid.uuid4().hex[:6]}"},
                )
            ).scalar_one()
            sub_path_id = (
                await conn.execute(
                    text(
                        "INSERT INTO sub_paths (path_id, difficulty) "
                        "VALUES (:pid, 'EASY') RETURNING id"
                    ),
                    {"pid": path_id},
                )
            ).scalar_one()
            exercise_id = (
                await conn.execute(
                    text(
                        "INSERT INTO exercises (content_id, statement, difficulty) "
                        "VALUES (:cid, 'no options here', 'EASY') RETURNING id"
                    ),
                    {"cid": content_id},
                )
            ).scalar_one()
            await conn.execute(
                text(
                    "INSERT INTO sub_paths_item (sub_path_id, type_item, exercise_id) "
                    "VALUES (:spid, 'EXERCISE', :eid)"
                ),
                {"spid": sub_path_id, "eid": exercise_id},
            )
            return {"path_id": path_id, "sub_path_id": sub_path_id}

    return asyncio.run(_insert())


class TestPathRouter(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)
        self.student_id, self.student_headers = _create_student(self.client, self.admin_headers)
        self.seed = _seed_trail(self.student_id)
        self.path_id = self.seed["path_id"]

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_list_trails_returns_200_for_own_student(self):
        resp = self.client.get(
            f"/api/student/{self.student_id}/trails",
            headers=self.student_headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
        self.assertTrue(any(t["id"] == str(self.path_id) for t in data))

    def test_list_trails_returns_403_for_other_student(self):
        other_id, _ = _create_student(self.client, self.admin_headers)
        resp = self.client.get(
            f"/api/student/{other_id}/trails",
            headers=self.student_headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_get_trail_detail_returns_200(self):
        resp = self.client.get(
            f"/api/student/{self.student_id}/trails/{self.path_id}",
            headers=self.student_headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["id"], str(self.path_id))
        self.assertIn("steps", data)
        self.assertIn("subject", data)

    def test_get_subject_trails_returns_all_details_for_subject(self):
        resp = self.client.get(
            f"/api/student/{self.student_id}/trails/subjects/matematica-trail-test",
            headers=self.student_headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
        ids = {trail["id"] for trail in data}
        self.assertIn(str(self.path_id), ids)
        trail = next(t for t in data if t["id"] == str(self.path_id))
        self.assertIn("steps", trail)
        self.assertEqual(trail["subject"]["id"], "matematica-trail-test")

    def test_detail_returns_quiz_sub_steps_without_answer_key(self):
        resp = self.client.get(
            f"/api/student/{self.student_id}/trails/{self.path_id}",
            headers=self.student_headers,
        )
        self.assertEqual(resp.status_code, 200)
        steps = resp.json()["steps"]
        sub_steps = next(
            s["sub_steps"] for s in steps if str(s["id"]) == str(self.seed["sub_path_id"])
        )
        self.assertEqual([ss["kind"] for ss in sub_steps], ["video", "question"])
        quiz = next(ss for ss in sub_steps if ss["kind"] == "question")
        self.assertEqual(quiz["id"], f"quiz-{self.seed['sub_path_id']}")
        self.assertEqual(len(quiz["questions"]), 1)
        question = quiz["questions"][0]
        self.assertEqual(question["question"], "Quanto é 2x+4=10?")
        self.assertEqual({o["label"] for o in question["options"]}, {"x=2", "x=3"})
        self.assertNotIn("correctOptionId", question)
        for opt in question["options"]:
            self.assertNotIn("correct", opt)

    def test_get_trail_detail_returns_404_for_unknown_path(self):
        resp = self.client.get(
            f"/api/student/{self.student_id}/trails/999999",
            headers=self.student_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_list_trails_returns_401_without_auth(self):
        resp = self.client.get(f"/api/student/{self.student_id}/trails")
        self.assertEqual(resp.status_code, 401)

    def test_question_flow_returns_questions(self):
        sub_path_id = self.seed["sub_path_id"]
        resp = self.client.get(
            f"/api/student/{self.student_id}/trails/{self.path_id}/steps/{sub_path_id}/questions",
            headers=self.student_headers,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["stepId"], str(sub_path_id))
        self.assertEqual(body["subStepId"], f"quiz-{sub_path_id}")
        self.assertGreaterEqual(len(body["questions"]), 1)

    def test_question_flow_403_for_other_student(self):
        other_id, _ = _create_student(self.client, self.admin_headers)
        sub_path_id = self.seed["sub_path_id"]
        resp = self.client.get(
            f"/api/student/{other_id}/trails/{self.path_id}/steps/{sub_path_id}/questions",
            headers=self.student_headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_complete_step_grades_records_and_advances(self):
        s = self.seed
        resp = self.client.post(
            f"/api/student/{self.student_id}/trails/{s['path_id']}"
            f"/steps/{s['sub_path_id']}/complete",
            headers=self.student_headers,
            json={
                "answers": [{"exercise_id": s["exercise_id"], "option_id": s["correct_option_id"]}]
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["correct"], 1)
        self.assertEqual(body["total"], 1)
        self.assertTrue(body["passed"])
        self.assertEqual(body["current_sub_path"], s["next_sub_path_id"])
        self.assertEqual(body["path_status"], "on_going")

    def test_complete_resource_item_marks_the_video_sub_step_completed(self):
        s = self.seed
        resp = self.client.post(
            f"/api/student/{self.student_id}/trails/{s['path_id']}"
            f"/items/{s['resource_item_id']}/complete",
            headers=self.student_headers,
            json={"answers": []},
        )
        self.assertEqual(resp.status_code, 200)
        step = next(st for st in resp.json()["steps"] if st["id"] == str(s["sub_path_id"]))
        self.assertEqual(step["sub_steps"][0]["status"], "completed")
        self.assertEqual(step["sub_steps"][1]["status"], "available")

    def test_completing_all_items_in_sub_path_advances_to_next_sub_path(self):
        s = self.seed
        resource_resp = self.client.post(
            f"/api/student/{self.student_id}/trails/{s['path_id']}"
            f"/items/{s['resource_item_id']}/complete",
            headers=self.student_headers,
            json={"answers": []},
        )
        self.assertEqual(resource_resp.status_code, 200)

        resp = self.client.post(
            f"/api/student/{self.student_id}/trails/{s['path_id']}"
            f"/items/{s['exercise_item_id']}/complete",
            headers=self.student_headers,
            json={
                "answers": [{"exercise_id": s["exercise_id"], "option_id": s["correct_option_id"]}]
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["completed_steps"], 1)
        next_step = next(st for st in body["steps"] if st["id"] == str(s["next_sub_path_id"]))
        self.assertEqual(next_step["status"], "available")

    def test_completing_first_quiz_group_keeps_sibling_sub_step_open(self):
        s = self.seed
        second = _add_second_question_sub_step(s)
        self.client.post(
            f"/api/student/{self.student_id}/trails/{s['path_id']}"
            f"/items/{s['resource_item_id']}/complete",
            headers=self.student_headers,
            json={"answers": []},
        )

        first_sub_step_id = f"quiz-{s['sub_path_id']}"
        flow = self.client.get(
            f"/api/student/{self.student_id}/trails/{s['path_id']}"
            f"/steps/{s['sub_path_id']}/sub-steps/{first_sub_step_id}/questions",
            headers=self.student_headers,
        )
        self.assertEqual(flow.status_code, 200)
        self.assertEqual(flow.json()["subStepId"], first_sub_step_id)
        self.assertEqual(
            [question["id"] for question in flow.json()["questions"]],
            [str(s["exercise_id"])],
        )

        response = self.client.post(
            f"/api/student/{self.student_id}/trails/{s['path_id']}"
            f"/steps/{s['sub_path_id']}/sub-steps/{first_sub_step_id}/complete",
            headers=self.student_headers,
            json={
                "answers": [
                    {
                        "exercise_id": s["exercise_id"],
                        "option_id": s["correct_option_id"],
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["current_sub_path"], s["sub_path_id"])
        self.assertEqual(body["path_status"], "on_going")
        step = next(item for item in body["steps"] if item["id"] == str(s["sub_path_id"]))
        statuses = {sub_step["id"]: sub_step["status"] for sub_step in step["sub_steps"]}
        self.assertEqual(statuses[first_sub_step_id], "completed")
        self.assertEqual(statuses[second["sub_step_id"]], "available")
        self.assertEqual(step["status"], "available")

    def test_validate_answer_reports_selected_option_correctness(self):
        s = self.seed
        resp = self.client.post(
            f"/api/student/{self.student_id}/trails/{s['path_id']}"
            f"/steps/{s['sub_path_id']}/answers/validate",
            headers=self.student_headers,
            json={"exercise_id": s["exercise_id"], "option_id": s["correct_option_id"]},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["exercise_id"], s["exercise_id"])
        self.assertEqual(body["option_id"], s["correct_option_id"])
        self.assertTrue(body["correct"])

    def test_validate_answer_rejects_option_outside_step(self):
        s = self.seed
        resp = self.client.post(
            f"/api/student/{self.student_id}/trails/{s['path_id']}"
            f"/steps/{s['sub_path_id']}/answers/validate",
            headers=self.student_headers,
            json={"exercise_id": s["exercise_id"], "option_id": 999999},
        )
        self.assertEqual(resp.status_code, 404)

    def test_complete_last_step_marks_trail_completed(self):
        s = self.seed
        self.client.post(
            f"/api/student/{self.student_id}/trails/{s['path_id']}"
            f"/steps/{s['sub_path_id']}/complete",
            headers=self.student_headers,
            json={"answers": []},
        )
        resp = self.client.post(
            f"/api/student/{self.student_id}/trails/{s['path_id']}"
            f"/steps/{s['next_sub_path_id']}/complete",
            headers=self.student_headers,
            json={"answers": []},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["path_status"], "completed")

    def test_list_reports_partial_progress_after_advancing(self):
        s = self.seed
        # complete the first sub-path -> advances to the second (1 of 2 done)
        self.client.post(
            f"/api/student/{self.student_id}/trails/{s['path_id']}"
            f"/steps/{s['sub_path_id']}/complete",
            headers=self.student_headers,
            json={
                "answers": [{"exercise_id": s["exercise_id"], "option_id": s["correct_option_id"]}]
            },
        )
        resp = self.client.get(
            f"/api/student/{self.student_id}/trails",
            headers=self.student_headers,
        )
        self.assertEqual(resp.status_code, 200)
        trail = next(t for t in resp.json() if t["id"] == str(s["path_id"]))
        self.assertEqual(trail["steps"], 2)
        self.assertEqual(trail["completed"], 1)
        self.assertEqual(trail["progress"], 50)

    def test_list_excludes_incomplete_trails(self):
        incomplete_id = _seed_incomplete_path()
        resp = self.client.get(
            f"/api/student/{self.student_id}/trails",
            headers=self.student_headers,
        )
        self.assertEqual(resp.status_code, 200)
        ids = {t["id"] for t in resp.json()}
        self.assertIn(str(self.path_id), ids)  # complete trail is shown
        self.assertNotIn(str(incomplete_id), ids)  # empty trail is hidden

    def test_complete_step_wrong_answer_scores_zero(self):
        s = self.seed
        # a foreign/incorrect option id must not count as correct
        resp = self.client.post(
            f"/api/student/{self.student_id}/trails/{s['path_id']}"
            f"/steps/{s['sub_path_id']}/complete",
            headers=self.student_headers,
            json={"answers": [{"exercise_id": s["exercise_id"], "option_id": 999999}]},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["correct"], 0)
        self.assertEqual(body["total"], 1)
        self.assertFalse(body["passed"])

    def test_optionless_exercise_is_not_an_answerable_quiz(self):
        p = _seed_path_with_optionless_exercise()
        # hidden from the list (no usable item)
        list_resp = self.client.get(
            f"/api/student/{self.student_id}/trails",
            headers=self.student_headers,
        )
        self.assertNotIn(str(p["path_id"]), {t["id"] for t in list_resp.json()})
        # and its detail/question-flow expose no quiz (graceful, no 500)
        flow = self.client.get(
            f"/api/student/{self.student_id}/trails/{p['path_id']}"
            f"/steps/{p['sub_path_id']}/questions",
            headers=self.student_headers,
        )
        self.assertEqual(flow.status_code, 200)
        self.assertEqual(flow.json()["questions"], [])

    def test_question_flow_empty_when_sub_path_has_no_exercises(self):
        s = self.seed
        # the second sub-path has no items at all -> graceful empty quiz
        resp = self.client.get(
            f"/api/student/{self.student_id}/trails/{s['path_id']}"
            f"/steps/{s['next_sub_path_id']}/questions",
            headers=self.student_headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["questions"], [])

    def test_detail_of_incomplete_trail_is_graceful(self):
        incomplete_id = _seed_incomplete_path()
        resp = self.client.get(
            f"/api/student/{self.student_id}/trails/{incomplete_id}",
            headers=self.student_headers,
        )
        self.assertEqual(resp.status_code, 200)
        steps = resp.json()["steps"]
        self.assertTrue(all(st["sub_steps"] == [] for st in steps))

    def test_complete_step_403_for_other_student(self):
        other_id, _ = _create_student(self.client, self.admin_headers)
        s = self.seed
        resp = self.client.post(
            f"/api/student/{other_id}/trails/{s['path_id']}/steps/{s['sub_path_id']}/complete",
            headers=self.student_headers,
            json={"answers": []},
        )
        self.assertEqual(resp.status_code, 403)
