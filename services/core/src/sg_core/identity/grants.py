"""Where non-owner admins get their capabilities.

Grants will live in `admin_role_grants` (C02 baseline). Until that table exists the API uses
`StaticGrantStore`, which grants nothing, so only allowlisted owners can reach the console.
"""

from collections.abc import Mapping
from typing import Protocol

from sg_core.identity.capabilities import Capability


class GrantStore(Protocol):
    async def capabilities_for(self, user_id: str) -> frozenset[Capability]: ...


class StaticGrantStore:
    def __init__(self, grants: Mapping[str, frozenset[Capability]] | None = None) -> None:
        self._grants = dict(grants or {})

    async def capabilities_for(self, user_id: str) -> frozenset[Capability]:
        return self._grants.get(user_id, frozenset())
