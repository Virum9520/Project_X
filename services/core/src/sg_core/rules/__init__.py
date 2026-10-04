"""Deterministic, versioned garden rules engine (C10). Pure: see `engine.py` for the guarantees
and `rules/README.md` for the profiles. Only `load_profile` reads files."""

from sg_core.rules.engine import (
    apply_decay,
    due_concepts,
    earned_stage,
    propose,
    replay,
    rule_version,
    status_at,
)
from sg_core.rules.profile import (
    RulesProfile,
    RulesProfileError,
    load_profile,
    profile_for_account,
)
from sg_core.rules.types import (
    ENGINE_VERSION,
    GROWTH_DIMENSIONS,
    DimensionState,
    GardenState,
    GrowthEvent,
    Observation,
    PlantChange,
    PlantState,
    RulesResult,
    Skipped,
)

__all__ = [
    "ENGINE_VERSION",
    "GROWTH_DIMENSIONS",
    "DimensionState",
    "GardenState",
    "GrowthEvent",
    "Observation",
    "PlantChange",
    "PlantState",
    "RulesProfile",
    "RulesProfileError",
    "RulesResult",
    "Skipped",
    "apply_decay",
    "due_concepts",
    "earned_stage",
    "load_profile",
    "profile_for_account",
    "propose",
    "replay",
    "rule_version",
    "status_at",
]
