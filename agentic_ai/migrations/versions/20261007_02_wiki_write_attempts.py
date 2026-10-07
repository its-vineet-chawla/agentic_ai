"""Add durable wiki write idempotency records."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261007_02"
down_revision: Union[str, None] = "20261007_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wiki_write_attempts",
        sa.Column("idempotency_key", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("proposal_digest", sa.String(length=64), nullable=False),
        sa.Column("repository", sa.String(length=255), nullable=False),
        sa.Column("target_page", sa.String(length=255), nullable=False),
        sa.Column("operation", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("remote_version", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "operation IN ('create', 'update')",
            name="ck_wiki_attempt_operation",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'uncertain')",
            name="ck_wiki_attempt_status",
        ),
        sa.PrimaryKeyConstraint("idempotency_key"),
        sa.UniqueConstraint("proposal_digest", name="uq_wiki_attempt_proposal_digest"),
    )


def downgrade() -> None:
    op.drop_table("wiki_write_attempts")