"""Schema invariants that need no database."""

import re
from pathlib import Path

from sqlalchemy import ForeignKeyConstraint

from sg_core.models import HYPERTABLES, Base
from sg_core.models.enums import Character, Dimension, PlantStatus

CONTRACTS = Path(__file__).parents[3] / "packages/contracts/src/index.ts"


def _ts_string_array(name: str) -> list[str]:
    match = re.search(rf"{name} = \[(.*?)\] as const", CONTRACTS.read_text(), re.S)
    assert match, f"{name} not found in contracts"
    return re.findall(r'"([^"]+)"', match.group(1))


def test_every_table_has_a_primary_key() -> None:
    for table in Base.metadata.tables.values():
        assert table.primary_key.columns, table.name


def test_hypertable_keys_include_the_time_column() -> None:
    for name, (time_column, _) in HYPERTABLES.items():
        table = Base.metadata.tables[name]
        assert time_column in table.primary_key.columns, name
        for index in table.indexes:
            if index.unique:
                assert time_column in {c.name for c in index.columns}, index.name


def test_nothing_references_a_hypertable() -> None:
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if isinstance(constraint, ForeignKeyConstraint):
                assert constraint.referred_table.name not in HYPERTABLES, (
                    f"{table.name} -> {constraint.referred_table.name}"
                )


def test_constraint_names_follow_the_convention() -> None:
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            assert constraint.name, f"unnamed constraint on {table.name}"
        for index in table.indexes:
            assert index.name and index.name.startswith(("ix_", "uq_")), index.name


def test_enums_match_the_typescript_contracts() -> None:
    assert [c.value for c in Character] == _ts_string_array("CHARACTERS")
    stages = _ts_string_array("PLANT_STAGES")
    assert [s.value for s in PlantStatus][: len(stages)] == stages
    assert {d.value for d in Dimension} == {
        "explanation",
        "application",
        "transfer",
        "retention",
    }
