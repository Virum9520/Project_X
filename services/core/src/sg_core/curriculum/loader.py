"""Read a curriculum version from its YAML directory into a validated `CurriculumSpec`.

Layout of `curriculum/<key>/<version>/`:

    curriculum.yaml           key, version, title, rubric_version, domains, assessment_guardrails
    concepts/<domain>.yaml    `domain:` plus the `concepts:` of that grove
    rubrics/dimensions.yaml   generic outcome levels for each evidence dimension
    rubrics/communication.yaml  communication behaviors for behavioral answers (optional)
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from sg_core.curriculum.schema import CurriculumSpec
from sg_core.settings import get_settings

# services/core/src/sg_core/curriculum/loader.py -> repository root
_REPO_ROOT = Path(__file__).resolve().parents[5]


class CurriculumError(ValueError):
    """The curriculum on disk (or its stored copy) is invalid or inconsistent."""


def curriculum_root() -> Path:
    """Directory holding every curriculum (`CURRICULUM_DIR`, else `<repo>/curriculum`)."""
    return get_settings().curriculum_dir or _REPO_ROOT / "curriculum"


def curriculum_path(key: str, version: str, root: Path | None = None) -> Path:
    return (root or curriculum_root()) / key / version


def load_curriculum(path: Path) -> CurriculumSpec:
    """Load and validate one curriculum version directory."""
    if not path.is_dir():
        raise CurriculumError(f"curriculum directory not found: {path}")

    manifest = _read_mapping(path / "curriculum.yaml")
    concepts: list[Any] = []
    # Concepts follow the domain order declared in curriculum.yaml (it also fixes the hash).
    declared = [d.get("key") for d in manifest.get("domains") or [] if isinstance(d, dict)]
    concept_files = sorted(
        (path / "concepts").glob("*.yaml"),
        key=lambda f: (declared.index(f.stem) if f.stem in declared else len(declared), f.stem),
    )
    if not concept_files:
        raise CurriculumError(f"no concept files in {path / 'concepts'}")
    for file in concept_files:
        data = _read_mapping(file)
        domain = data.get("domain")
        if domain != file.stem:
            raise CurriculumError(f"{file}: `domain` must match the file name ({file.stem!r})")
        for concept in data.get("concepts") or []:
            key = concept.get("key", "") if isinstance(concept, dict) else ""
            if not str(key).startswith(f"{domain}."):
                raise CurriculumError(f"{file}: concept {key!r} must be keyed `{domain}.<slug>`")
            concepts.append(concept)

    dimensions = _read_mapping(path / "rubrics" / "dimensions.yaml")
    communication_file = path / "rubrics" / "communication.yaml"
    communication = _read_mapping(communication_file) if communication_file.exists() else {}

    try:
        spec = CurriculumSpec.model_validate(
            {
                **manifest,
                "concepts": concepts,
                "dimension_rubrics": dimensions.get("dimensions"),
                "communication_rubrics": communication.get("behaviors", []),
            }
        )
    except ValidationError as exc:
        raise CurriculumError(f"{path}: invalid curriculum\n{exc}") from exc

    if (path.parent.name, path.name) != (spec.key, spec.version):
        raise CurriculumError(
            f"{path}: directory must be <root>/{spec.key}/{spec.version} to match curriculum.yaml"
        )
    return spec


def _read_mapping(file: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CurriculumError(f"missing file: {file}") from exc
    except yaml.YAMLError as exc:
        raise CurriculumError(f"{file}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise CurriculumError(f"{file}: expected a mapping at the top level")
    return data
