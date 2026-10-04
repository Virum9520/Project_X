"""Versioned concept catalog (`curriculum/<key>/<version>/` YAML): loading, validation and
syncing into the curriculum tables. Run `python -m sg_core.curriculum --help` for the CLI."""

from sg_core.curriculum.loader import (
    CurriculumError,
    curriculum_path,
    curriculum_root,
    load_curriculum,
)
from sg_core.curriculum.schema import (
    CommunicationRubricSpec,
    ConceptRubricSpec,
    ConceptSpec,
    CurriculumSpec,
    DimensionRubricSpec,
    DomainSpec,
)
from sg_core.curriculum.sync import SyncResult, sync_curriculum

__all__ = [
    "CommunicationRubricSpec",
    "ConceptRubricSpec",
    "ConceptSpec",
    "CurriculumError",
    "CurriculumSpec",
    "DimensionRubricSpec",
    "DomainSpec",
    "SyncResult",
    "curriculum_path",
    "curriculum_root",
    "load_curriculum",
    "sync_curriculum",
]
