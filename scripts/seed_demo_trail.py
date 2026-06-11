"""Seed (or clean) a complete demo adaptive trail for manual/smoke testing.

Real trail content is produced by the AI content pipeline; this script only
creates ONE fully-formed trail so the feature can be exercised end to end before
that content exists. A "complete" trail = Subject -> Content -> Resource +
Exercises (each WITH options) -> Path -> SubPaths -> SubPathItems -> a
PathTransition, optionally with StudentPathProgress for a given student.

Usage (inside the backend container or with DATABASE_URL pointing at the DB):

    python -m scripts.seed_demo_trail seed
    python -m scripts.seed_demo_trail seed --student aluno@example.com
    python -m scripts.seed_demo_trail clean            # remove non-playable trails
    python -m scripts.seed_demo_trail clean --all-demo  # also remove this demo trail
"""

import argparse
import asyncio
import sys

from sqlalchemy import delete, func, or_, select

from md_backend.models.db_models import (
    Content,
    DifficultyEnum,
    Exercise,
    Option,
    Path,
    PathStatusEnum,
    PathTransition,
    Resource,
    ResourceTypeEnum,
    RuleTypeEnum,
    StudentPathProgress,
    Subject,
    SubPath,
    SubPathItem,
    TypeItemEnum,
    UserProfile,
)
from md_backend.utils.database import AsyncSessionLocal

DEMO_PATH_NAME = "Trilha Demo de Álgebra"
DEMO_SUBJECT_SLUG = "mathematics"


async def _get_or_create_subject(session) -> Subject:
    subject = (
        await session.execute(select(Subject).where(Subject.slug == DEMO_SUBJECT_SLUG))
    ).scalar_one_or_none()
    if subject is None:
        subject = (
            await session.execute(select(Subject).limit(1))
        ).scalar_one_or_none()
    if subject is None:
        subject = Subject(slug=DEMO_SUBJECT_SLUG, name="Matemática", color="#2563EB")
        session.add(subject)
        await session.flush()
    return subject


async def seed(student_email: str | None) -> None:
    """Create one complete demo trail (idempotent by path name)."""
    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(select(Path).where(Path.name == DEMO_PATH_NAME))
        ).scalar_one_or_none()
        if existing is not None:
            print(f"Demo trail already exists (path id={existing.id}); nothing to do.")
            path = existing
        else:
            subject = await _get_or_create_subject(session)

            content = Content(
                subject_id=subject.id,
                name="Fundamentos de Álgebra (demo)",
                description="Trilha demo para reforço em álgebra.",
            )
            session.add(content)
            await session.flush()

            resource = Resource(
                content_id=content.id,
                type=ResourceTypeEnum.VIDEO,
                title="Assistir: Introdução às Equações do 1º Grau",
                file_url="https://example.com/demo-video.mp4",
            )
            session.add(resource)

            ex1 = Exercise(
                contents_id=content.id,
                statement="Quanto vale x em 2x + 4 = 10?",
                difficulty=DifficultyEnum.EASY,
            )
            ex2 = Exercise(
                contents_id=content.id,
                statement="Qual é a forma decimal de 1/2?",
                difficulty=DifficultyEnum.MEDIUM,
            )
            session.add_all([ex1, ex2])
            await session.flush()

            session.add_all([
                Option(exercise_id=ex1.id, text="x = 2", correct=False),
                Option(exercise_id=ex1.id, text="x = 3", correct=True),
                Option(exercise_id=ex1.id, text="x = 7", correct=False),
                Option(exercise_id=ex2.id, text="0,25", correct=False),
                Option(exercise_id=ex2.id, text="0,5", correct=True),
                Option(exercise_id=ex2.id, text="0,75", correct=False),
            ])

            path = Path(
                contents_id=content.id,
                name=DEMO_PATH_NAME,
                description="Trilha adaptativa demo com vídeo e dois quizzes.",
            )
            session.add(path)
            await session.flush()

            sp1 = SubPath(path_id=path.id, difficulty=DifficultyEnum.EASY)
            sp2 = SubPath(path_id=path.id, difficulty=DifficultyEnum.MEDIUM)
            session.add_all([sp1, sp2])
            await session.flush()

            session.add_all([
                SubPathItem(
                    sub_path_id=sp1.id, type_item=TypeItemEnum.RESOURCE, item_id=resource.id
                ),
                SubPathItem(
                    sub_path_id=sp1.id, type_item=TypeItemEnum.EXERCISE, item_id=ex1.id
                ),
                SubPathItem(
                    sub_path_id=sp2.id, type_item=TypeItemEnum.EXERCISE, item_id=ex2.id
                ),
                # Adaptive edge: by default advance from step 1 to step 2.
                PathTransition(
                    sub_path_origin_id=sp1.id,
                    sub_path_destination_id=sp2.id,
                    rule_type=RuleTypeEnum.STANDARD,
                ),
            ])
            await session.flush()
            print(f"Created demo trail (path id={path.id}, sub-paths {sp1.id},{sp2.id}).")

        if student_email:
            await _init_progress(session, path, student_email)

        await session.commit()
        print("Done.")


async def _init_progress(session, path: Path, student_email: str) -> None:
    user = (
        await session.execute(
            select(UserProfile).where(UserProfile.email == student_email)
        )
    ).scalar_one_or_none()
    if user is None:
        print(f"  ! No user with email {student_email}; skipping progress init.")
        return
    first_sub_path = (
        await session.execute(
            select(func.min(SubPath.id)).where(SubPath.path_id == path.id)
        )
    ).scalar_one()
    existing = (
        await session.execute(
            select(StudentPathProgress).where(
                StudentPathProgress.student_id == user.id,
                StudentPathProgress.path_id == path.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(StudentPathProgress(
            student_id=user.id,
            path_id=path.id,
            current_sub_path=first_sub_path,
            path_status=PathStatusEnum.ON_GOING,
        ))
        print(f"  Initialised progress for {student_email} at sub-path {first_sub_path}.")
    else:
        print(f"  Progress already exists for {student_email}.")


async def clean(all_demo: bool) -> None:
    """Delete trails that are not playable. With --all-demo, also delete the demo trail."""
    async with AsyncSessionLocal() as session:
        has_options = (
            select(Option.id).where(Option.exercise_id == SubPathItem.item_id).exists()
        )
        usable = (
            select(SubPathItem.id)
            .join(SubPath, SubPath.id == SubPathItem.sub_path_id)
            .where(
                SubPath.path_id == Path.id,
                or_(SubPathItem.type_item == TypeItemEnum.RESOURCE, has_options),
            )
            .exists()
        )
        all_ids = set(
            (await session.execute(select(Path.id))).scalars().all()
        )
        playable_ids = set(
            (await session.execute(select(Path.id).where(usable))).scalars().all()
        )
        delete_ids = all_ids - playable_ids

        if all_demo:
            demo_ids = set(
                (await session.execute(
                    select(Path.id).where(Path.name == DEMO_PATH_NAME)
                )).scalars().all()
            )
            delete_ids |= demo_ids

        for path_id in delete_ids:
            sub_ids = (
                await session.execute(select(SubPath.id).where(SubPath.path_id == path_id))
            ).scalars().all()
            if sub_ids:
                await session.execute(
                    delete(PathTransition).where(
                        or_(
                            PathTransition.sub_path_origin_id.in_(sub_ids),
                            PathTransition.sub_path_destination_id.in_(sub_ids),
                        )
                    )
                )
                await session.execute(
                    delete(SubPathItem).where(SubPathItem.sub_path_id.in_(sub_ids))
                )
            await session.execute(
                delete(StudentPathProgress).where(StudentPathProgress.path_id == path_id)
            )
            await session.execute(delete(SubPath).where(SubPath.path_id == path_id))
            await session.execute(delete(Path).where(Path.id == path_id))

        await session.commit()
        print(f"Removed {len(delete_ids)} trail(s).")


def main() -> None:
    """Parse args and run the requested subcommand."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed", help="create one complete demo trail")
    s.add_argument("--student", help="email of a student to initialise progress for")
    c = sub.add_parser("clean", help="remove non-playable trails")
    c.add_argument("--all-demo", action="store_true", help="also remove the demo trail")
    args = parser.parse_args()

    if args.cmd == "seed":
        asyncio.run(seed(args.student))
    elif args.cmd == "clean":
        asyncio.run(clean(args.all_demo))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
