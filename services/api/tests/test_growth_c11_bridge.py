import uuid
from datetime import UTC, datetime

from sg_api.drona.growth import growth_event_from_c11


def test_c11_provisional_event_becomes_a_glow() -> None:
    event = growth_event_from_c11(
        "garden.provisional_growth",
        uuid.uuid4(),
        datetime.now(UTC),
        {"concept": "dsa.bfs", "dimension": "explanation", "assistance": "hinted"},
    )
    assert event is not None
    assert (event.kind, event.part, event.assisted) == ("provisional", "roots", True)


def test_c11_retraction_carries_the_reason() -> None:
    event = growth_event_from_c11(
        "garden.provisional_retracted",
        uuid.uuid4(),
        datetime.now(UTC),
        {"concept": "dsa.bfs", "dimension": "application", "reason": "not confirmed"},
    )
    assert event is not None
    assert (event.kind, event.reason) == ("retracted", "not confirmed")


def test_other_events_are_ignored() -> None:
    assert growth_event_from_c11("garden.revision", uuid.uuid4(), datetime.now(UTC), {}) is None
