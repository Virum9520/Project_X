"""Bhima accountability (C18): self-report columns on commitments and push subscriptions.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("commitments", sa.Column("reported_status", sa.String(length=20), nullable=True))
    op.add_column("commitments", sa.Column("reported_note", sa.String(length=400), nullable=True))
    op.add_column(
        "commitments", sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("commitments", sa.Column("concept_key", sa.String(length=128), nullable=True))
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(length=256), nullable=False),
        sa.Column("auth", sa.String(length=128), nullable=False),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_push_subscriptions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_push_subscriptions")),
        sa.UniqueConstraint("endpoint", name=op.f("uq_push_subscriptions_endpoint")),
    )
    op.create_index(
        op.f("ix_push_subscriptions_user_id"), "push_subscriptions", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_push_subscriptions_user_id"), table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
    op.drop_column("commitments", "concept_key")
    op.drop_column("commitments", "reported_at")
    op.drop_column("commitments", "reported_note")
    op.drop_column("commitments", "reported_status")
