"""The identity services one API process shares across requests."""

from dataclasses import dataclass, field

import httpx

from sg_core.db import get_sessionmaker
from sg_core.identity import (
    AuditSink,
    ClerkTokenVerifier,
    ClerkUserDirectory,
    GrantStore,
    LogAuditSink,
    NullUserStore,
    StaticGrantStore,
    UserStore,
)
from sg_core.identity.db import DbAuditSink, DbGrantStore, DbUserStore
from sg_core.settings import Settings


@dataclass(slots=True)
class Identity:
    # None when Clerk isn't configured; authenticated routes then answer 503.
    verifier: ClerkTokenVerifier | None
    directory: ClerkUserDirectory | None
    grants: GrantStore
    audit: AuditSink
    owner_emails: frozenset[str]
    admin_origins: frozenset[str]
    users: UserStore = field(default_factory=NullUserStore)


def build_identity(settings: Settings, http: httpx.AsyncClient) -> Identity:
    verifier = (
        ClerkTokenVerifier(
            settings.clerk_issuer, authorized_parties=settings.authorized_parties, http=http
        )
        if settings.clerk_issuer
        else None
    )
    directory = (
        ClerkUserDirectory(
            settings.clerk_api_url, settings.clerk_secret_key.get_secret_value(), http=http
        )
        if settings.clerk_secret_key
        else None
    )
    identity = Identity(
        verifier=verifier,
        directory=directory,
        grants=StaticGrantStore(),
        audit=LogAuditSink(),
        owner_emails=frozenset(settings.admin_owner_emails),
        admin_origins=frozenset(settings.admin_origins),
    )
    if settings.identity_backend == "db":
        # Lazy engine: nothing connects until the first query.
        sessions = get_sessionmaker()
        identity.grants = DbGrantStore(sessions)
        identity.audit = DbAuditSink(sessions)
        identity.users = DbUserStore(sessions)
    return identity
