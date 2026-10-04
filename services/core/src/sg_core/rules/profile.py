"""Rules profile: the numbers that tune the engine (`rules/profile*.yaml`).

`RulesProfile` is immutable data. Reading the YAML (`load_profile`) is the only I/O in this
package; the engine itself receives an already-built profile.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from sg_core.models.enums import AssessmentOutcome

# services/core/src/sg_core/rules/profile.py -> repository root
_REPO_ROOT = Path(__file__).resolve().parents[5]

PROFILE_FILES = {"normal": "profile.yaml", "demo": "profile.demo.yaml"}


class RulesProfileError(ValueError):
    """The profile on disk is missing or invalid."""


class RulesProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    version: int = Field(ge=1)
    outcome_credit: dict[AssessmentOutcome, float]
    max_uncertainty: float = Field(ge=0, le=1)
    reach_threshold: float = Field(gt=0, le=1)
    retention_min_gap_seconds: int = Field(ge=0)
    review_intervals_seconds: tuple[int, ...] = Field(min_length=1)
    wilt_grace_seconds: int = Field(ge=0)
    review_fail_drop: int = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> Self:
        for outcome in (
            AssessmentOutcome.DEMONSTRATED,
            AssessmentOutcome.PARTIAL,
            AssessmentOutcome.NOT_DEMONSTRATED,
        ):
            credit = self.outcome_credit.get(outcome)
            if credit is None or not 0 <= credit <= 1:
                raise ValueError(f"outcome_credit.{outcome.value} must be a number in [0, 1]")
        if AssessmentOutcome.UNASSESSABLE in self.outcome_credit:
            raise ValueError("outcome_credit must not define `unassessable` (it never counts)")
        if self.outcome_credit[AssessmentOutcome.DEMONSTRATED] < self.reach_threshold:
            raise ValueError("one demonstrated outcome must reach `reach_threshold`")
        credits = self.outcome_credit
        if credits[AssessmentOutcome.NOT_DEMONSTRATED] != 0:
            raise ValueError("outcome_credit.not_demonstrated must be 0 (a miss never grows)")
        if credits[AssessmentOutcome.PARTIAL] > credits[AssessmentOutcome.DEMONSTRATED]:
            raise ValueError("outcome_credit.partial must not exceed demonstrated")
        if any(i <= 0 for i in self.review_intervals_seconds):
            raise ValueError("review_intervals_seconds must be positive")
        if list(self.review_intervals_seconds) != sorted(self.review_intervals_seconds):
            raise ValueError("review_intervals_seconds must be non-decreasing")
        return self

    @property
    def content_hash(self) -> str:
        """Stable short hash of the numbers, so a replay can detect a silently edited profile."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


def rules_root() -> Path:
    return _REPO_ROOT / "rules"


def load_profile(name: str = "normal", root: Path | None = None) -> RulesProfile:
    """Load `normal` (`profile.yaml`) or `demo` (`profile.demo.yaml`)."""
    try:
        filename = PROFILE_FILES[name]
    except KeyError:
        raise RulesProfileError(
            f"unknown rules profile {name!r}; expected {sorted(PROFILE_FILES)}"
        ) from None
    path = (root or rules_root()) / filename
    if not path.is_file():
        raise RulesProfileError(f"rules profile not found: {path}")
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RulesProfileError(f"{path}: expected a mapping")
    try:
        profile = RulesProfile.model_validate(data)
    except ValidationError as exc:
        raise RulesProfileError(f"{path}: invalid rules profile\n{exc}") from exc
    if profile.name != name:
        raise RulesProfileError(f"{path}: `name` must be {name!r}, got {profile.name!r}")
    return profile


def profile_for_account(*, demo: bool, root: Path | None = None) -> RulesProfile:
    """The demo profile is enabled per account (demo and test accounts only)."""
    return load_profile("demo" if demo else "normal", root)
