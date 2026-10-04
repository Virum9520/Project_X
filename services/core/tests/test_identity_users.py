from sg_core.identity import Capability
from sg_core.identity.capabilities import CAPABILITY_DESCRIPTIONS, ROLE_CAPABILITIES
from sg_core.identity.clerk import _parse_user
from sg_core.identity.users import parse_onboarding
from sg_core.models.enums import AdminRole


def test_every_capability_is_described_and_owner_holds_all() -> None:
    assert set(CAPABILITY_DESCRIPTIONS) == set(Capability)
    assert ROLE_CAPABILITIES[AdminRole.OWNER] == frozenset(Capability)
    assert set(ROLE_CAPABILITIES) == set(AdminRole)
    for caps in ROLE_CAPABILITIES.values():
        assert Capability.CONSOLE_ACCESS in caps


def test_only_owner_can_manage_grants() -> None:
    for role, caps in ROLE_CAPABILITIES.items():
        assert (Capability.GRANTS_MANAGE in caps) == (role is AdminRole.OWNER)


def test_parse_onboarding_maps_clerk_metadata() -> None:
    fields = parse_onboarding(
        {
            "major": "  Computer Science ",
            "goals": ["job-search", 3, "technical-interviews"],
            "experience": "projects",
            "timezone": "America/Detroit",
            "completedAt": "2026-10-04T12:00:00.000Z",
        }
    )
    assert fields is not None
    assert fields.major == "Computer Science"
    assert fields.goals == ["job-search", "technical-interviews"]
    assert fields.experience_level == "projects"
    assert fields.timezone == "America/Detroit"
    assert fields.onboarded_at is not None and fields.onboarded_at.tzinfo is not None


def test_parse_onboarding_drops_malformed_values() -> None:
    fields = parse_onboarding(
        {"major": 5, "goals": "x", "experience": "wizard", "completedAt": "no"}
    )
    assert fields is not None
    assert (fields.major, fields.goals, fields.experience_level, fields.onboarded_at) == (
        None,
        [],
        None,
        None,
    )
    assert parse_onboarding(None) is None
    assert parse_onboarding({}) is None


def test_clerk_user_carries_name_and_onboarding() -> None:
    user = _parse_user(
        {
            "id": "user_1",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "primary_email_address_id": "idn_1",
            "email_addresses": [
                {
                    "id": "idn_1",
                    "email_address": "Ada@Example.com",
                    "verification": {"status": "verified"},
                }
            ],
            "public_metadata": {"onboarding": {"major": "Math"}},
        }
    )
    assert user.display_name == "Ada Lovelace"
    assert user.primary_email == "ada@example.com"
    assert user.onboarding == {"major": "Math"}
    assert _parse_user({"id": "u", "public_metadata": None}).onboarding is None
