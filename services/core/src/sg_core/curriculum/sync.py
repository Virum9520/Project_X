"""Write a validated `CurriculumSpec` into `curricula`, `concepts`, `concept_edges` and `rubrics`.

Syncing is idempotent and keyed on `(key, version)` plus the spec's content hash:

- an unknown version is inserted as `draft`;
- the same content is a no-op;
- changed content replaces a `draft` in place, but an `active` or `retired` version is
  immutable (evidence cites its concepts and rubrics), so changing it needs a new version.

Activation retires the previously active version of the same curriculum key.
"""

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sg_core.curriculum.loader import CurriculumError
from sg_core.curriculum.schema import CurriculumSpec
from sg_core.models.curriculum import Concept, ConceptEdge, Curriculum, Rubric
from sg_core.models.enums import ConceptEdgeKind, CurriculumStatus, Dimension


@dataclass(frozen=True)
class RubricRow:
    key: str
    concept_key: str | None
    dimension: Dimension | None
    criteria: dict[str, Any]


@dataclass(frozen=True)
class SyncResult:
    curriculum_id: uuid.UUID
    action: Literal["created", "unchanged", "replaced"]
    status: CurriculumStatus
    concepts: int
    edges: int
    rubrics: int


def concept_rows(spec: CurriculumSpec) -> list[dict[str, Any]]:
    assessment = {d.key: d.assessment for d in spec.domains}
    return [
        {
            "key": c.key,
            "domain": c.domain,
            "title": c.title,
            "summary": c.summary,
            "difficulty": c.difficulty,
            "attributes": {
                "topic": c.topic,
                "aliases": list(c.aliases),
                "assessment": assessment[c.domain],
            },
        }
        for c in spec.concepts
    ]


def edge_rows(spec: CurriculumSpec) -> list[tuple[str, str, ConceptEdgeKind]]:
    """`(from, to, kind)`: `from` is a prerequisite of (or related to) `to`."""
    edges = []
    for concept in spec.concepts:
        edges += [(p, concept.key, ConceptEdgeKind.PREREQUISITE) for p in concept.prerequisites]
        edges += [(r, concept.key, ConceptEdgeKind.RELATED) for r in concept.related]
    return edges


def rubric_rows(spec: CurriculumSpec) -> list[RubricRow]:
    """One rubric per concept, one per evidence dimension and one per communication behavior.

    `criteria.kind` tells them apart; keys look like `cs-core@v1/dsa.hash_tables`,
    `cs-core@v1/dimension.explanation` and `cs-core@v1/communication.structure`.
    """
    rows = [
        RubricRow(
            key=spec.rubric_key(c.key),
            concept_key=c.key,
            dimension=None,
            criteria={"kind": "concept", "concept": c.key, **c.rubric.model_dump(mode="json")},
        )
        for c in spec.concepts
    ]
    rows += [
        RubricRow(
            key=spec.rubric_key(f"dimension.{r.dimension.value}"),
            concept_key=None,
            dimension=r.dimension,
            criteria={
                "kind": "dimension",
                **r.model_dump(mode="json"),
                "guardrails": list(spec.assessment_guardrails),
            },
        )
        for r in spec.dimension_rubrics
    ]
    rows += [
        RubricRow(
            key=spec.rubric_key(f"communication.{r.key}"),
            concept_key=None,
            dimension=None,
            criteria={
                "kind": "communication",
                **r.model_dump(mode="json"),
                "guardrails": list(spec.assessment_guardrails),
            },
        )
        for r in spec.communication_rubrics
    ]
    return rows


async def sync_curriculum(
    session: AsyncSession, spec: CurriculumSpec, *, activate: bool = False
) -> SyncResult:
    """Upsert `spec` (see module docstring). The caller owns the transaction and commits."""
    current = await session.scalar(
        select(Curriculum).where(Curriculum.key == spec.key, Curriculum.version == spec.version)
    )
    action: Literal["created", "unchanged", "replaced"]
    if current is None:
        current = Curriculum(
            key=spec.key,
            version=spec.version,
            title=spec.title,
            status=CurriculumStatus.DRAFT,
            content_hash=spec.content_hash,
        )
        session.add(current)
        await session.flush()
        await _insert_content(session, current.id, spec)
        action = "created"
    elif current.content_hash == spec.content_hash:
        action = "unchanged"
    elif current.status is CurriculumStatus.DRAFT:
        # Concept rubrics and edges cascade from concepts; generic rubrics are deleted here.
        await session.execute(delete(Rubric).where(Rubric.curriculum_id == current.id))
        await session.execute(delete(Concept).where(Concept.curriculum_id == current.id))
        current.title = spec.title
        current.content_hash = spec.content_hash
        await _insert_content(session, current.id, spec)
        action = "replaced"
    else:
        raise CurriculumError(
            f"{spec.ref} is {current.status.value} and its content changed; "
            "published versions are immutable, so create a new version instead"
        )

    if activate and current.status is not CurriculumStatus.ACTIVE:
        # Retire first: a partial unique index allows one active version per key.
        await session.execute(
            update(Curriculum)
            .where(
                Curriculum.key == spec.key,
                Curriculum.status == CurriculumStatus.ACTIVE,
                Curriculum.id != current.id,
            )
            .values(status=CurriculumStatus.RETIRED)
        )
        current.status = CurriculumStatus.ACTIVE
        await session.flush()

    return SyncResult(
        curriculum_id=current.id,
        action=action,
        status=current.status,
        concepts=len(spec.concepts),
        edges=len(edge_rows(spec)),
        rubrics=len(rubric_rows(spec)),
    )


async def _insert_content(
    session: AsyncSession, curriculum_id: uuid.UUID, spec: CurriculumSpec
) -> None:
    result = await session.execute(
        insert(Concept).returning(Concept.key, Concept.id),
        [{**row, "curriculum_id": curriculum_id} for row in concept_rows(spec)],
    )
    concept_ids: dict[str, uuid.UUID] = {key: id_ for key, id_ in result}

    edges = edge_rows(spec)
    if edges:
        await session.execute(
            insert(ConceptEdge),
            [
                {"from_concept_id": concept_ids[a], "to_concept_id": concept_ids[b], "kind": kind}
                for a, b, kind in edges
            ],
        )

    await session.execute(
        insert(Rubric),
        [
            {
                "key": row.key,
                "version": spec.rubric_version,
                "curriculum_id": curriculum_id,
                "concept_id": concept_ids[row.concept_key] if row.concept_key else None,
                "dimension": row.dimension,
                "criteria": row.criteria,
            }
            for row in rubric_rows(spec)
        ],
    )
