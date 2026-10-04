"""The identity services one API process shares across requests."""

from dataclasses import dataclass

import httpx

from sg_core.identity import (
    AuditSink,
    ClerkTokenVerifier,
    ClerkUserDirectory,
    GrantStore,
    LogAuditSink,
    StaticGrantStore,
)
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
    return Identity(
        verifier=verifier,
        directory=directory,
        grants=StaticGrantStore(),
        audit=LogAuditSink(),
        owner_emails=frozenset(settings.admin_owner_emails),
        admin_origins=frozenset(settings.admin_origins),
    )
