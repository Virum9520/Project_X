"""Curriculum loader, catalog invariants and the shipped `cs-core@v1` content (no database)."""

import copy
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from sg_core.curriculum import CurriculumError, curriculum_path, load_curriculum
from sg_core.curriculum.sync import concept_rows, edge_rows, rubric_rows
from sg_core.models.enums import ConceptEdgeKind, Dimension

GROVES = ["dsa", "os", "networks", "databases", "system_design", "behavioral"]


# ── Shipped content ──
@pytest.fixture(scope="module")
def cs_core() -> Any:
    return load_curriculum(curriculum_path("cs-core", "v1"))


def test_cs_core_has_about_80_concepts_across_the_six_groves(cs_core: Any) -> None:
    assert cs_core.ref == "cs-core@v1"
    assert 75 <= len(cs_core.concepts) <= 95
    assert [d.key for d in cs_core.domains] == GROVES
    for grove in GROVES:
        assert len(cs_core.concepts_in(grove)) >= 8, grove
    # Concepts are grouped by grove in the declared order.
    order = [c.domain for c in cs_core.concepts]
    assert order == sorted(order, key=GROVES.index)


def test_every_grove_has_a_root_and_the_graph_is_ordered(cs_core: Any) -> None:
    # Each grove has an entry concept (prerequisites may come from other groves).
    for grove in GROVES:
        assert any(
            all(not p.startswith(f"{grove}.") for p in c.prerequisites)
            for c in cs_core.concepts_in(grove)
        ), grove
    position = {key: i for i, key in enumerate(cs_core.topological_order())}
    assert len(position) == len(cs_core.concepts)
    for concept in cs_core.concepts:
        for prerequisite in concept.prerequisites:
            assert position[prerequisite] < position[concept.key]


def test_behavioral_grove_uses_communication_rubrics(cs_core: Any) -> None:
    assessment = {d.key: d.assessment for d in cs_core.domains}
    assert assessment["behavioral"] == "behavioral"
    assert {k for k, v in assessment.items() if v == "technical"} == set(GROVES) - {"behavioral"}
    assert {r.key for r in cs_core.communication_rubrics} == {
        "structure",
        "specificity",
        "ownership",
        "conciseness",
    }


def test_closure_and_dependents(cs_core: Any) -> None:
    closure = cs_core.prerequisite_closure("dsa.shortest_paths")
    assert {"dsa.bfs", "dsa.heaps", "dsa.queues", "dsa.big_o"} <= closure
    assert "dsa.shortest_paths" not in closure
    assert "dsa.sliding_window" in cs_core.dependents("dsa.two_pointers")
    with pytest.raises(KeyError):
        cs_core.concept("dsa.nope")


def test_content_hash_is_stable_and_ignores_formatting(cs_core: Any, tmp_path: Path) -> None:
    again = load_curriculum(curriculum_path("cs-core", "v1"))
    assert again.content_hash == cs_core.content_hash
    reformatted = _copy_tree(curriculum_path("cs-core", "v1"), tmp_path / "cs-core" / "v1")
    file = reformatted / "concepts" / "os.yaml"
    file.write_text("# a comment\n" + yaml.safe_dump(yaml.safe_load(file.read_text()), indent=4))
    assert load_curriculum(reformatted).content_hash == cs_core.content_hash


def test_db_rows(cs_core: Any) -> None:
    concepts = concept_rows(cs_core)
    assert len(concepts) == len(cs_core.concepts)
    assert concepts[0]["attributes"].keys() == {"topic", "aliases", "assessment"}

    edges = edge_rows(cs_core)
    assert len(set(edges)) == len(edges)
    assert ("dsa.arrays", "dsa.hash_tables", ConceptEdgeKind.PREREQUISITE) in edges

    rubrics = rubric_rows(cs_core)
    assert len({r.key for r in rubrics}) == len(rubrics)
    kinds = [r.criteria["kind"] for r in rubrics]
    assert kinds.count("concept") == len(cs_core.concepts)
    assert {r.dimension for r in rubrics if r.criteria["kind"] == "dimension"} == set(Dimension)
    hash_tables = next(r for r in rubrics if r.concept_key == "dsa.hash_tables")
    assert hash_tables.key == "cs-core@v1/dsa.hash_tables"
    assert hash_tables.criteria["explanation"]
    explanation = next(r for r in rubrics if r.dimension is Dimension.EXPLANATION)
    assert explanation.criteria["guardrails"] == list(cs_core.assessment_guardrails)


# ── Validation failures, on a minimal curriculum ──
MINIMAL: dict[str, Any] = {
    "curriculum.yaml": {
        "key": "mini",
        "version": "v1",
        "title": "Mini",
        "description": "Test curriculum",
        "rubric_version": 1,
        "domains": [{"key": "dsa", "title": "DSA", "description": "d"}],
    },
    "concepts/dsa.yaml": {
        "domain": "dsa",
        "concepts": [
            {
                "key": f"dsa.{name}",
                "title": name,
                "topic": "t",
                "difficulty": 1,
                "summary": "s",
                "prerequisites": prerequisites,
                "rubric": {"explanation": ["a", "b"], "application": ["c"], "transfer": ["d"]},
            }
            for name, prerequisites in (
                ("a", []),
                ("b", ["dsa.a"]),
                ("c", ["dsa.b"]),
            )
        ],
    },
    "rubrics/dimensions.yaml": {
        "dimensions": [
            {
                "dimension": d.value,
                "description": "x",
                "levels": {"demonstrated": "y", "partial": "p", "not_demonstrated": "n"},
                "evidence": ["e"],
            }
            for d in Dimension
        ]
    },
}


def _write(root: Path, files: dict[str, Any]) -> Path:
    path = root / "mini" / "v1"
    for name, data in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(yaml.safe_dump(data))
    return path


def _concepts(files: dict[str, Any]) -> list[dict[str, Any]]:
    concepts: list[dict[str, Any]] = files["concepts/dsa.yaml"]["concepts"]
    return concepts


def test_minimal_curriculum_loads(tmp_path: Path) -> None:
    spec = load_curriculum(_write(tmp_path, MINIMAL))
    assert spec.topological_order() == ("dsa.a", "dsa.b", "dsa.c")
    assert spec.communication_rubrics == ()


def _mutations() -> list[tuple[str, Any, str]]:
    def unknown_prereq(f: dict[str, Any]) -> None:
        _concepts(f)[1]["prerequisites"] = ["dsa.zzz"]

    def cycle(f: dict[str, Any]) -> None:
        _concepts(f)[0]["prerequisites"] = ["dsa.c"]

    def duplicate(f: dict[str, Any]) -> None:
        _concepts(f)[2]["key"] = "dsa.a"

    def self_edge(f: dict[str, Any]) -> None:
        _concepts(f)[0]["related"] = ["dsa.a"]

    def redundant(f: dict[str, Any]) -> None:
        _concepts(f)[2]["prerequisites"] = ["dsa.a", "dsa.b"]

    def related_twice(f: dict[str, Any]) -> None:
        _concepts(f)[0]["related"] = ["dsa.c"]
        _concepts(f)[2]["related"] = ["dsa.a"]

    def prerequisite_and_related(f: dict[str, Any]) -> None:
        _concepts(f)[1]["related"] = ["dsa.a"]

    def wrong_prefix(f: dict[str, Any]) -> None:
        _concepts(f)[0]["key"] = "os.a"

    def undeclared_domain(f: dict[str, Any]) -> None:
        f["curriculum.yaml"]["domains"][0]["key"] = "os"

    def missing_dimension(f: dict[str, Any]) -> None:
        f["rubrics/dimensions.yaml"]["dimensions"].pop()

    def thin_rubric(f: dict[str, Any]) -> None:
        _concepts(f)[0]["rubric"]["explanation"] = ["only one"]

    def unknown_field(f: dict[str, Any]) -> None:
        _concepts(f)[0]["owner"] = "someone"

    def bad_difficulty(f: dict[str, Any]) -> None:
        _concepts(f)[0]["difficulty"] = 9

    return [
        ("unknown_prereq", unknown_prereq, "unknown concept 'dsa.zzz'"),
        ("cycle", cycle, "prerequisite cycle"),
        ("duplicate", duplicate, "duplicate concept 'dsa.a'"),
        ("self_edge", self_edge, "cannot reference itself"),
        ("redundant", redundant, "already implied by 'dsa.b'"),
        ("related_twice", related_twice, "declare a related edge only once"),
        ("prerequisite_and_related", prerequisite_and_related, "both prerequisite and related"),
        ("wrong_prefix", wrong_prefix, "must be keyed `dsa.<slug>`"),
        ("undeclared_domain", undeclared_domain, "domain 'dsa' is not declared"),
        ("missing_dimension", missing_dimension, "missing dimension rubrics"),
        ("thin_rubric", thin_rubric, "explanation"),
        ("unknown_field", unknown_field, "owner"),
        ("bad_difficulty", bad_difficulty, "difficulty"),
    ]


@pytest.mark.parametrize(
    ("mutate", "message"), [m[1:] for m in _mutations()], ids=[m[0] for m in _mutations()]
)
def test_invalid_curricula_are_rejected(tmp_path: Path, mutate: Any, message: str) -> None:
    files = copy.deepcopy(MINIMAL)
    mutate(files)
    with pytest.raises(CurriculumError, match=re.escape(message)):
        load_curriculum(_write(tmp_path, files))


def test_directory_must_match_key_and_version(tmp_path: Path) -> None:
    path = _write(tmp_path, MINIMAL)
    moved = path.rename(path.parent / "v2")
    with pytest.raises(CurriculumError, match="directory must be"):
        load_curriculum(moved)


def test_missing_and_malformed_files(tmp_path: Path) -> None:
    with pytest.raises(CurriculumError, match="not found"):
        load_curriculum(tmp_path / "nope")
    path = _write(tmp_path, MINIMAL)
    (path / "rubrics" / "dimensions.yaml").unlink()
    with pytest.raises(CurriculumError, match="missing file"):
        load_curriculum(path)
    (path / "rubrics" / "dimensions.yaml").write_text("dimensions: [unclosed")
    with pytest.raises(CurriculumError, match="invalid YAML"):
        load_curriculum(path)


def _copy_tree(src: Path, dst: Path) -> Path:
    for file in src.rglob("*.yaml"):
        target = dst / file.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file.read_text())
    return dst
