"""Path (adaptive trail) service."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import (
    Content,
    DifficultyEnum,
    Exercise,
    Path,
    PathStatusEnum,
    Resource,
    StudentPathProgress,
    SubPath,
    SubPathItem,
    Subject,
    TypeItemEnum,
)

# ---------------------------------------------------------------------------
# Default trail catalog
# Each trail entry: one Content + one Path with N sub-paths.
# Each sub-path has a list of items; each item is either:
#   ("resource", title, resource_type)   → creates a Resource record
#   ("exercise", statement, difficulty)  → creates an Exercise record
# ---------------------------------------------------------------------------
_DEFAULT_TRAILS = [
    {
        "subject_slug": "mathematics",
        "content_name": "Fundamentos de Álgebra",
        "content_description": "Introdução a equações, variáveis e operações algébricas básicas.",
        "path_name": "Trilha de Álgebra",
        "path_description": "Trilha adaptativa para reforço em álgebra do ensino fundamental.",
        "sub_paths": [
            {
                "difficulty": DifficultyEnum.EASY,
                "items": [
                    ("resource", "Introdução às Equações do 1º Grau", "video"),
                    ("resource", "Propriedades da Igualdade", "text"),
                    ("exercise", "Qual o valor de x em 2x + 4 = 10?", DifficultyEnum.EASY),
                ],
            },
            {
                "difficulty": DifficultyEnum.MEDIUM,
                "items": [
                    ("resource", "Equações com Frações e Decimais", "video"),
                    ("exercise", "Resolva: x/3 + 2 = 5", DifficultyEnum.MEDIUM),
                ],
            },
            {
                "difficulty": DifficultyEnum.HARD,
                "items": [
                    ("exercise", "Um número aumentado de 15 é igual ao dobro desse número. Qual é ele?", DifficultyEnum.HARD),
                    ("exercise", "Resolva o sistema: 2x + y = 8 e x - y = 1", DifficultyEnum.HARD),
                ],
            },
        ],
    },
    {
        "subject_slug": "portuguese",
        "content_name": "Interpretação de Textos",
        "content_description": "Leitura crítica, inferência e argumentação textual.",
        "path_name": "Trilha de Interpretação",
        "path_description": "Desenvolva habilidades de leitura e análise de diferentes gêneros textuais.",
        "sub_paths": [
            {
                "difficulty": DifficultyEnum.EASY,
                "items": [
                    ("resource", "Técnicas de Leitura Crítica", "text"),
                    ("exercise", "Qual é a ideia central do texto apresentado?", DifficultyEnum.EASY),
                ],
            },
            {
                "difficulty": DifficultyEnum.MEDIUM,
                "items": [
                    ("resource", "Inferência e Argumentação Textual", "video"),
                    ("exercise", "Identifique o argumento principal do trecho abaixo.", DifficultyEnum.MEDIUM),
                ],
            },
        ],
    },
    {
        "subject_slug": "science",
        "content_name": "Ecossistemas e Sustentabilidade",
        "content_description": "Estudo dos ecossistemas, cadeias alimentares e sustentabilidade ambiental.",
        "path_name": "Trilha de Ecologia",
        "path_description": "Explore a interdependência dos seres vivos e os desafios ambientais.",
        "sub_paths": [
            {
                "difficulty": DifficultyEnum.EASY,
                "items": [
                    ("resource", "Cadeias Alimentares e Ecossistemas", "video"),
                    ("exercise", "O que é uma cadeia alimentar? Dê um exemplo.", DifficultyEnum.EASY),
                ],
            },
            {
                "difficulty": DifficultyEnum.MEDIUM,
                "items": [
                    ("resource", "Sustentabilidade e Ciclos Naturais", "text"),
                    ("exercise", "Explique a diferença entre produtor, consumidor e decomposto.", DifficultyEnum.MEDIUM),
                ],
            },
        ],
    },
    {
        "subject_slug": "history",
        "content_name": "Brasil Colônia",
        "content_description": "Contexto histórico, exploração e formação da sociedade colonial brasileira.",
        "path_name": "Trilha do Brasil Colonial",
        "path_description": "Explore a história da colonização portuguesa e a formação do Brasil.",
        "sub_paths": [
            {
                "difficulty": DifficultyEnum.EASY,
                "items": [
                    ("resource", "Brasil Colonial: Contexto e Chegada dos Portugueses", "video"),
                    ("exercise", "Em que ano Pedro Álvares Cabral chegou ao Brasil?", DifficultyEnum.EASY),
                ],
            },
            {
                "difficulty": DifficultyEnum.MEDIUM,
                "items": [
                    ("resource", "Leitura de Fontes Históricas Primárias", "text"),
                    ("exercise", "Quais foram as principais consequências da colonização para os povos indígenas?", DifficultyEnum.MEDIUM),
                ],
            },
        ],
    },
    {
        "subject_slug": "geography",
        "content_name": "Clima e Relevo",
        "content_description": "Tipos climáticos, formações de relevo e sua influência no cotidiano.",
        "path_name": "Trilha de Clima e Relevo",
        "path_description": "Compreenda os fatores que influenciam o clima e as formas do relevo.",
        "sub_paths": [
            {
                "difficulty": DifficultyEnum.EASY,
                "items": [
                    ("resource", "Tipos de Clima no Brasil", "video"),
                    ("exercise", "Cite dois fatores que influenciam o clima de uma região.", DifficultyEnum.EASY),
                ],
            },
            {
                "difficulty": DifficultyEnum.MEDIUM,
                "items": [
                    ("resource", "Formações de Relevo e Sua Origem", "text"),
                    ("exercise", "Qual a diferença entre planalto, planície e depressão?", DifficultyEnum.MEDIUM),
                ],
            },
        ],
    },
    {
        "subject_slug": "biology",
        "content_name": "Célula e Genética",
        "content_description": "Estrutura celular, divisão celular e introdução à genética.",
        "path_name": "Trilha de Biologia Celular",
        "path_description": "Descubra como as células funcionam e como a herança genética opera.",
        "sub_paths": [
            {
                "difficulty": DifficultyEnum.EASY,
                "items": [
                    ("resource", "Estrutura da Célula: Organelas e Funções", "video"),
                    ("exercise", "Qual é a função da mitocôndria na célula?", DifficultyEnum.EASY),
                ],
            },
            {
                "difficulty": DifficultyEnum.MEDIUM,
                "items": [
                    ("resource", "Divisão Celular: Mitose e Meiose", "text"),
                    ("exercise", "Qual a diferença entre mitose e meiose?", DifficultyEnum.MEDIUM),
                ],
            },
        ],
    },
    {
        "subject_slug": "english",
        "content_name": "Grammar Basics",
        "content_description": "Fundamentos de gramática inglesa: verbos, tempos verbais e estrutura de frases.",
        "path_name": "Trilha de Gramática Inglesa",
        "path_description": "Build a solid foundation in English grammar through structured practice.",
        "sub_paths": [
            {
                "difficulty": DifficultyEnum.EASY,
                "items": [
                    ("resource", "Present Simple vs Present Continuous", "video"),
                    ("exercise", "Complete: She ___ (to go) to school every day.", DifficultyEnum.EASY),
                ],
            },
            {
                "difficulty": DifficultyEnum.MEDIUM,
                "items": [
                    ("resource", "Past Tense: Regular and Irregular Verbs", "text"),
                    ("exercise", "Write the past tense of: go, buy, study, play.", DifficultyEnum.MEDIUM),
                ],
            },
        ],
    },
]


async def seed_default_trails(session: AsyncSession) -> int:
    """Insert the default trail catalog. Returns the number of paths created.

    Idempotent — skips entries where a Path with the same name already exists.
    Skips subjects that do not exist in the database.
    """
    existing_path_names = set(
        (await session.execute(select(Path.name))).scalars().all()
    )

    subjects_by_slug: dict[str, Subject] = {
        s.slug: s
        for s in (await session.execute(select(Subject))).scalars().all()
        if s.slug is not None
    }

    created = 0
    for trail in _DEFAULT_TRAILS:
        if trail["path_name"] in existing_path_names:
            continue

        subject = subjects_by_slug.get(trail["subject_slug"])
        if subject is None:
            continue

        content = Content(
            subject_id=subject.id,
            name=trail["content_name"],
            description=trail["content_description"],
        )
        session.add(content)
        await session.flush()

        path = Path(
            contents_id=content.id,
            name=trail["path_name"],
            description=trail["path_description"],
        )
        session.add(path)
        await session.flush()

        for sub_path_data in trail["sub_paths"]:
            sub_path = SubPath(path_id=path.id, difficulty=sub_path_data["difficulty"])
            session.add(sub_path)
            await session.flush()

            for item_spec in sub_path_data["items"]:
                if item_spec[0] == "resource":
                    _, title, resource_type = item_spec
                    record = Resource(
                        contents_id=content.id,
                        type=resource_type,
                        title=title,
                    )
                    session.add(record)
                    await session.flush()
                    session.add(SubPathItem(
                        sub_path_id=sub_path.id,
                        type_item=TypeItemEnum.RESOURCE,
                        item_id=record.id,
                    ))
                else:
                    _, statement, difficulty = item_spec
                    record = Exercise(
                        contents_id=content.id,
                        statement=statement,
                        difficulty=difficulty,
                    )
                    session.add(record)
                    await session.flush()
                    session.add(SubPathItem(
                        sub_path_id=sub_path.id,
                        type_item=TypeItemEnum.EXERCISE,
                        item_id=record.id,
                    ))

        created += 1

    return created


class PathService:
    """Read-only operations for adaptive learning paths."""

    async def list_trails(
        self, session: AsyncSession, student_id: uuid.UUID
    ) -> list[dict]:
        """List all paths with per-student progress."""
        sub_path_count_sq = (
            select(SubPath.path_id, func.count(SubPath.id).label("total"))
            .group_by(SubPath.path_id)
            .subquery()
        )

        stmt = (
            select(Path, Content, Subject, sub_path_count_sq.c.total)
            .join(Content, Path.contents_id == Content.id)
            .join(Subject, Content.subject_id == Subject.id)
            .outerjoin(sub_path_count_sq, Path.id == sub_path_count_sq.c.path_id)
        )
        rows = (await session.execute(stmt)).all()

        progress_rows = (
            await session.execute(
                select(StudentPathProgress).where(
                    StudentPathProgress.student_id == student_id
                )
            )
        ).scalars().all()

        progress_by_path: dict[int, StudentPathProgress] = {
            p.path_id: p for p in progress_rows
        }

        result = []
        for path, content, subject, total_steps in rows:
            total = total_steps or 0
            progress_record = progress_by_path.get(path.id)

            if progress_record is None:
                completed = 0
                pct = 0
            elif progress_record.path_status == PathStatusEnum.COMPLETED:
                completed = total
                pct = 100
            else:
                completed = 0
                pct = 0

            result.append({
                "id": str(path.id),
                "name": path.name or content.name,
                "description": path.description or content.description,
                "subject": {
                    "id": str(subject.id),
                    "label": subject.name,
                    "color": subject.color,
                },
                "steps": total,
                "completed": completed,
                "progress": pct,
                "time_estimate": None,
            })

        return result

    async def get_trail_detail(
        self, session: AsyncSession, student_id: uuid.UUID, path_id: int
    ) -> dict | None:
        """Return full trail detail with sub-path statuses for a student."""
        row = (
            await session.execute(
                select(Path, Content, Subject)
                .join(Content, Path.contents_id == Content.id)
                .join(Subject, Content.subject_id == Subject.id)
                .where(Path.id == path_id)
            )
        ).one_or_none()

        if row is None:
            return None

        path, content, subject = row

        sub_paths = (
            await session.execute(
                select(SubPath).where(SubPath.path_id == path_id).order_by(SubPath.id)
            )
        ).scalars().all()

        progress = (
            await session.execute(
                select(StudentPathProgress).where(
                    StudentPathProgress.student_id == student_id,
                    StudentPathProgress.path_id == path_id,
                )
            )
        ).scalar_one_or_none()

        current_sub_path_id: int | None = (
            progress.current_sub_path if progress is not None else None
        )

        steps = []
        reached_current = False

        for order, sub_path in enumerate(sub_paths, start=1):
            if progress is None:
                if order == 1:
                    step_status = "available"
                else:
                    step_status = "locked"
            elif sub_path.id == current_sub_path_id:
                step_status = "available"
                reached_current = True
            elif not reached_current:
                step_status = "completed"
            else:
                step_status = "locked"

            items = (
                await session.execute(
                    select(SubPathItem)
                    .where(SubPathItem.sub_path_id == sub_path.id)
                    .order_by(SubPathItem.id)
                )
            ).scalars().all()

            sub_steps = [
                {
                    "id": str(item.id),
                    "kind": "question" if item.type_item == "exercise" else "resource",
                    "title": f"Etapa {item.id}",
                    "order": idx,
                    "status": step_status,
                    "questions": [],
                }
                for idx, item in enumerate(items, start=1)
            ]

            steps.append({
                "id": str(sub_path.id),
                "title": f"Etapa {order}",
                "description": None,
                "order": order,
                "status": step_status,
                "sub_steps": sub_steps,
            })

        total = len(steps)
        completed_count = sum(1 for s in steps if s["status"] == "completed")
        pct = round((completed_count / total) * 100) if total > 0 else 0

        return {
            "id": str(path.id),
            "title": path.name or content.name,
            "description": path.description or content.description,
            "subject": {
                "id": str(subject.id),
                "label": subject.name,
                "color": subject.color,
            },
            "progress": pct,
            "completed_steps": completed_count,
            "level_label": None,
            "time_estimate": None,
            "steps": steps,
        }
