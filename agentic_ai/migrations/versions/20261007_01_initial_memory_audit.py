"""Create scoped memory and audit tables."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261007_01"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_records",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("repository", sa.String(length=255), nullable=False),
        sa.Column("project_id", sa.String(length=255), nullable=True),
        sa.Column("memory_type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("approved_by", sa.String(length=255), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "memory_type IN ('project_fact', 'decision', 'preference', 'workflow_note')",
            name="ck_memory_type",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_scope_expiry",
        "memory_records",
        ["user_id", "repository", "project_id", "expires_at"],
    )
    op.create_table(
        "audit_records",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("request_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("repository", sa.String(length=255), nullable=False),
        sa.Column("project_id", sa.String(length=255), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('github_read', 'analysis', 'memory_store', 'memory_delete', "
            "'memory_purge', 'wiki_proposal', 'wiki_write')",
            name="ck_audit_event_type",
        ),
        sa.CheckConstraint(
            "outcome IN ('success', 'failure', 'denied')",
            name="ck_audit_outcome",
        ),
        sa.CheckConstraint(
            "item_count IS NULL OR item_count >= 0",
            name="ck_audit_item_count",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_user_repository_time",
        "audit_records",
        ["user_id", "repository", "occurred_at"],
    )
    op.create_index("ix_audit_request_id", "audit_records", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_request_id", table_name="audit_records")
    op.drop_index("ix_audit_user_repository_time", table_name="audit_records")
    op.drop_table("audit_records")
    op.drop_index("ix_memory_scope_expiry", table_name="memory_records")
    op.drop_table("memory_records")