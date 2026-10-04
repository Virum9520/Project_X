"""Identity, admin RBAC and the audit log (semantics owned by C01)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sg_core.models.base import Base, created_at, str_enum, updated_at, uuid_pk
from sg_core.models.enums import ActorType, AdminRole, AdminStatus


class User(Base):
    """A learner (and the identity behind any admin). Mirrors a Clerk user."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    clerk_user_id: Mapped[str] = mapped_column(String(64), unique=True)
    # Stored lower-cased; the unique index is on the stored value.
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    timezone: Mapped[str | None] = mapped_column(String(64))  # IANA, e.g. America/Detroit
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Profile(Base):
    """Onboarding answers. User claims here never establish mastery."""

    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    major: Mapped[str | None] = mapped_column(String(200))
    experience_level: Mapped[str | None] = mapped_column(String(40))
    target_role: Mapped[str | None] = mapped_column(String(200))
    goals: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    language: Mapped[str] = mapped_column(String(16), server_default="en")
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AdminUser(Base):
    """Owner-console access. Never created by a profile edit."""

    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[AdminStatus] = mapped_column(
        str_enum(AdminStatus, "status"), server_default=AdminStatus.ACTIVE.value
    )
    # True when bootstrapped from ADMIN_OWNER_EMAILS rather than invited.
    bootstrapped: Mapped[bool] = mapped_column(server_default=text("false"))
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Capability(Base):
    """Catalogue of explicit permissions, e.g. `usage.view`, `transcripts.view`, `calls.test`."""

    __tablename__ = "capabilities"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class RoleCapability(Base):
    """Which capabilities each admin role carries."""

    __tablename__ = "role_capabilities"

    role: Mapped[AdminRole] = mapped_column(str_enum(AdminRole, "role"), primary_key=True)
    capability_key: Mapped[str] = mapped_column(
        ForeignKey("capabilities.key", ondelete="CASCADE"), primary_key=True
    )


class AdminRoleGrant(Base):
    """A role held by an admin. An admin may hold several; revocation keeps the row."""

    __tablename__ = "admin_role_grants"
    __table_args__ = (
        Index(
            "uq_admin_role_grants_active",
            "admin_user_id",
            "role",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    admin_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("admin_users.id", ondelete="CASCADE")
    )
    role: Mapped[AdminRole] = mapped_column(str_enum(AdminRole, "role"))
    granted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    granted_at: Mapped[datetime] = created_at()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Append-only record of every admin mutation and other sensitive actions."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_actor_occurred", "actor_user_id", "occurred_at"),
        Index("ix_audit_log_target", "target_type", "target_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    occurred_at: Mapped[datetime] = created_at()
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_type: Mapped[ActorType] = mapped_column(str_enum(ActorType, "actor_type"))
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(128))
    request_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
