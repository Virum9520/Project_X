"""Typed, validated shape of a curriculum version on disk (`curriculum/<key>/<version>/`).

A `CurriculumSpec` is immutable. Its validators enforce the catalog invariants that the
judge, rules engine and garden rely on: unique stable keys, known domains, resolvable edges,
an acyclic prerequisite graph and complete rubrics.
"""

import hashlib
import json
from collections import defaultdict, deque
from collections.abc import Iterable
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from sg_core.models.enums import Dimension

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)]
CurriculumKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*$", max_length=64)]
# `<domain>.<slug>`: stable across curriculum versions, so learner history can follow a concept.
ConceptKey = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$", max_length=128)
]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LevelDescriptors(_Spec):
    """What each judge outcome looks like. Names match `AssessmentOutcome`."""

    demonstrated: Text
    partial: Text
    not_demonstrated: Text


class ConceptRubricSpec(_Spec):
    """Concept-specific criteria the judge checks, per evidence dimension.

    Retention has no concept-specific criteria: it is the explanation and application criteria
    met again after a review interval (see the generic `retention` dimension rubric).
    """

    explanation: tuple[Text, ...] = Field(min_length=2)
    application: tuple[Text, ...] = Field(min_length=1)
    transfer: tuple[Text, ...] = Field(min_length=1)
    misconceptions: tuple[Text, ...] = ()


class ConceptSpec(_Spec):
    key: ConceptKey
    title: Title
    topic: Slug
    difficulty: int = Field(ge=1, le=5)
    summary: Text
    aliases: tuple[Text, ...] = ()
    prerequisites: tuple[ConceptKey, ...] = ()
    related: tuple[ConceptKey, ...] = ()
    rubric: ConceptRubricSpec

    @property
    def domain(self) -> str:
        return self.key.split(".", 1)[0]


class DomainSpec(_Spec):
    """A grove in the garden."""

    key: Slug
    title: Title
    description: Text
    # Behavioral concepts are also scored against the communication rubrics.
    assessment: Literal["technical", "behavioral"] = "technical"


class DimensionRubricSpec(_Spec):
    """Generic outcome levels for one evidence dimension (one plant part)."""

    dimension: Dimension
    description: Text
    levels: LevelDescriptors
    evidence: tuple[Text, ...] = Field(min_length=1)


class CommunicationRubricSpec(_Spec):
    """A communication behavior scored in behavioral answers (not tied to a concept)."""

    key: Slug
    title: Title
    description: Text
    look_for: tuple[Text, ...] = Field(min_length=1)
    levels: LevelDescriptors


class CurriculumSpec(_Spec):
    key: CurriculumKey
    version: Annotated[str, StringConstraints(pattern=r"^v[1-9][0-9]*$")]
    title: Title
    description: Text
    rubric_version: int = Field(ge=1)
    domains: tuple[DomainSpec, ...] = Field(min_length=1)
    concepts: tuple[ConceptSpec, ...] = Field(min_length=1)
    dimension_rubrics: tuple[DimensionRubricSpec, ...]
    communication_rubrics: tuple[CommunicationRubricSpec, ...] = ()
    # Rules every judge prompt must carry (e.g. what may never be inferred).
    assessment_guardrails: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def _check_catalog(self) -> Self:
        _require_unique("domain", (d.key for d in self.domains))
        _require_unique("concept", (c.key for c in self.concepts))
        _require_unique("communication rubric", (r.key for r in self.communication_rubrics))
        _require_unique("dimension rubric", (r.dimension for r in self.dimension_rubrics))

        missing_dims = set(Dimension) - {r.dimension for r in self.dimension_rubrics}
        if missing_dims:
            raise ValueError(f"missing dimension rubrics: {sorted(missing_dims)}")

        domains = {d.key for d in self.domains}
        keys = {c.key for c in self.concepts}
        related_pairs: set[frozenset[str]] = set()
        for concept in self.concepts:
            if concept.domain not in domains:
                raise ValueError(f"{concept.key}: domain {concept.domain!r} is not declared")
            _require_unique(f"{concept.key} prerequisite", concept.prerequisites)
            _require_unique(f"{concept.key} related", concept.related)
            for ref in (*concept.prerequisites, *concept.related):
                if ref == concept.key:
                    raise ValueError(f"{concept.key}: a concept cannot reference itself")
                if ref not in keys:
                    raise ValueError(f"{concept.key}: unknown concept {ref!r}")
            both = set(concept.prerequisites) & set(concept.related)
            if both:
                raise ValueError(f"{concept.key}: {sorted(both)} is both prerequisite and related")
            for ref in concept.related:
                pair = frozenset((concept.key, ref))
                if pair in related_pairs:
                    raise ValueError(f"{concept.key} <-> {ref}: declare a related edge only once")
                related_pairs.add(pair)

        empty = domains - {c.domain for c in self.concepts}
        if empty:
            raise ValueError(f"domains without concepts: {sorted(empty)}")

        self.topological_order()  # raises on a prerequisite cycle

        # Only direct prerequisites: the garden draws each edge as a root path.
        for concept in self.concepts:
            for prerequisite in concept.prerequisites:
                for other in concept.prerequisites:
                    if other != prerequisite and prerequisite in self.prerequisite_closure(other):
                        raise ValueError(
                            f"{concept.key}: prerequisite {prerequisite!r} is already implied "
                            f"by {other!r}; list only direct prerequisites"
                        )
        return self

    # ── Lookups ──
    @property
    def ref(self) -> str:
        """Human reference used in rubric keys and logs, e.g. `cs-core@v1`."""
        return f"{self.key}@{self.version}"

    @property
    def content_hash(self) -> str:
        """SHA-256 of the canonical content; independent of YAML formatting and comments."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def concept(self, key: str) -> ConceptSpec:
        for concept in self.concepts:
            if concept.key == key:
                return concept
        raise KeyError(key)

    def concepts_in(self, domain: str) -> tuple[ConceptSpec, ...]:
        return tuple(c for c in self.concepts if c.domain == domain)

    def rubric_key(self, name: str) -> str:
        """Key of a stored rubric: a concept key, `dimension.<d>` or `communication.<k>`."""
        return f"{self.ref}/{name}"

    def dependents(self, key: str) -> tuple[str, ...]:
        """Concepts that list `key` as a direct prerequisite."""
        return tuple(c.key for c in self.concepts if key in c.prerequisites)

    def prerequisite_closure(self, key: str) -> frozenset[str]:
        """Every direct and transitive prerequisite of `key`."""
        seen: set[str] = set()
        stack = list(self.concept(key).prerequisites)
        while stack:
            current = stack.pop()
            if current not in seen:
                seen.add(current)
                stack.extend(self.concept(current).prerequisites)
        return frozenset(seen)

    def topological_order(self) -> tuple[str, ...]:
        """Concept keys with every prerequisite before its dependents (stable: file order)."""
        indegree = {c.key: len(c.prerequisites) for c in self.concepts}
        dependents: defaultdict[str, list[str]] = defaultdict(list)
        for concept in self.concepts:
            for prerequisite in concept.prerequisites:
                dependents[prerequisite].append(concept.key)
        ready = deque(key for key, degree in indegree.items() if degree == 0)
        order: list[str] = []
        while ready:
            key = ready.popleft()
            order.append(key)
            for dependent in dependents[key]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
        if len(order) != len(indegree):
            cyclic = sorted(key for key, degree in indegree.items() if degree > 0)
            raise ValueError(f"prerequisite cycle; unresolvable concepts: {cyclic}")
        return tuple(order)


def _require_unique(label: str, values: Iterable[str]) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label} {value!r}")
        seen.add(value)
