import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import ConfigDict, Field, field_validator
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    UniqueConstraint,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agentic_ai.config import Settings
from agentic_ai.models import GitHubModel


_SECRET_PATTERNS = (
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bbearer\s+\S{16,}"),
)


class Base(DeclarativeBase):
    pass


class MemoryRow(Base):
    __tablename__ = "memory_records"
    __table_args__ = (
        Index(
            "ix_memory_scope_expiry",
            "user_id",
            "repository",
            "project_id",
            "expires_at",
        ),
        CheckConstraint(
            "memory_type IN ('project_fact', 'decision', 'preference', 'workflow_note')",
            name="ck_memory_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    repository: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by: Mapped[str] = mapped_column(String(255), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditRow(Base):
    __tablename__ = "audit_records"
    __table_args__ = (
        Index("ix_audit_user_repository_time", "user_id", "repository", "occurred_at"),
        Index("ix_audit_request_id", "request_id"),
        CheckConstraint(
            "event_type IN ('github_read', 'analysis', 'memory_store', 'memory_delete', "
            "'memory_purge', 'wiki_proposal', 'wiki_write')",
            name="ck_audit_event_type",
        ),
        CheckConstraint("outcome IN ('success', 'failure', 'denied')", name="ck_audit_outcome"),
        CheckConstraint("item_count IS NULL OR item_count >= 0", name="ck_audit_item_count"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    repository: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WikiWriteAttemptRow(Base):
    __tablename__ = "wiki_write_attempts"
    __table_args__ = (
        UniqueConstraint("proposal_digest", name="uq_wiki_attempt_proposal_digest"),
        CheckConstraint("operation IN ('create', 'update')", name="ck_wiki_attempt_operation"),
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'uncertain')",
            name="ck_wiki_attempt_status",
        ),
    )

    idempotency_key: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    proposal_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    repository: Mapped[str] = mapped_column(String(255), nullable=False)
    target_page: Mapped[str] = mapped_column(String(255), nullable=False)
    operation: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    remote_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryScope(GitHubModel):
    user_id: str = Field(min_length=1, max_length=255)
    repository: str = Field(min_length=3, max_length=255)
    project_id: str | None = Field(default=None, max_length=255)

    @field_validator("repository")
    @classmethod
    def normalize_repository(cls, value: str) -> str:
        repository = value.casefold()
        if repository.count("/") != 1 or not all(repository.split("/")):
            raise ValueError("Repository must use the owner/name format")
        return repository

    @field_validator("project_id", mode="before")
    @classmethod
    def normalize_project_id(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class ApprovedMemory(GitHubModel):
    user_id: str = Field(min_length=1, max_length=255)
    repository: str = Field(min_length=3, max_length=255)
    project_id: str | None = Field(default=None, max_length=255)
    memory_type: Literal["project_fact", "decision", "preference", "workflow_note"]
    content: str = Field(min_length=1, max_length=4000)
    approved_by: str = Field(min_length=1, max_length=255)

    @field_validator("repository")
    @classmethod
    def normalize_repository(cls, value: str) -> str:
        repository = value.casefold()
        if repository.count("/") != 1 or not all(repository.split("/")):
            raise ValueError("Repository must use the owner/name format")
        return repository

    @field_validator("project_id", mode="before")
    @classmethod
    def normalize_project_id(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class StoredMemory(GitHubModel):
    id: uuid.UUID
    user_id: str
    repository: str
    project_id: str | None
    memory_type: str
    content: str
    approved_by: str
    approved_at: datetime
    created_at: datetime
    expires_at: datetime


class AuditEventInput(GitHubModel):
    user_id: str = Field(min_length=1, max_length=255)
    repository: str = Field(min_length=3, max_length=255)
    project_id: str | None = Field(default=None, max_length=255)
    request_id: uuid.UUID | None = None
    event_type: Literal[
        "github_read",
        "analysis",
        "memory_store",
        "memory_delete",
        "memory_purge",
        "wiki_proposal",
        "wiki_write",
    ]
    outcome: Literal["success", "failure", "denied"]
    item_count: int | None = Field(default=None, ge=0)
    error_code: Literal[
        "authentication_failed",
        "scope_denied",
        "dependency_unavailable",
        "rate_limited",
        "validation_failed",
        "conflict",
    ] | None = None

    @field_validator("repository")
    @classmethod
    def normalize_repository(cls, value: str) -> str:
        repository = value.casefold()
        if repository.count("/") != 1 or not all(repository.split("/")):
            raise ValueError("Repository must use the owner/name format")
        return repository

    @field_validator("project_id", mode="before")
    @classmethod
    def normalize_project_id(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class StoredAuditEvent(GitHubModel):
    id: uuid.UUID
    request_id: uuid.UUID | None
    user_id: str
    repository: str
    project_id: str | None
    event_type: str
    outcome: str
    item_count: int | None
    error_code: str | None
    occurred_at: datetime


class WikiWriteAttempt(GitHubModel):
    idempotency_key: uuid.UUID
    proposal_digest: str
    repository: str
    target_page: str
    operation: Literal["create", "update"]
    status: Literal["pending", "succeeded", "uncertain"]
    remote_version: str | None
    created_at: datetime
    completed_at: datetime | None


class DuplicateWikiWriteAttempt(RuntimeError):
    pass


class WikiWriteAttemptStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def claim(
        self,
        *,
        idempotency_key: uuid.UUID,
        proposal_digest: str,
        repository: str,
        target_page: str,
        operation: Literal["create", "update"],
    ) -> WikiWriteAttempt:
        if re.fullmatch(r"[0-9a-f]{64}", proposal_digest) is None:
            raise ValueError("proposal_digest must be a lowercase SHA-256 digest")
        row = WikiWriteAttemptRow(
            idempotency_key=idempotency_key,
            proposal_digest=proposal_digest,
            repository=repository,
            target_page=target_page,
            operation=operation,
            status="pending",
            created_at=datetime.now(timezone.utc),
        )
        try:
            async with self._sessions() as session:
                async with session.begin():
                    session.add(row)
                    await session.flush()
        except IntegrityError as error:
            raise DuplicateWikiWriteAttempt(
                "This wiki proposal or idempotency key has already been attempted."
            ) from error
        return self._to_record(row)

    async def complete(
        self,
        idempotency_key: uuid.UUID,
        *,
        status: Literal["succeeded", "uncertain"],
        remote_version: str | None = None,
    ) -> WikiWriteAttempt:
        now = datetime.now(timezone.utc)
        async with self._sessions() as session:
            async with session.begin():
                result = await session.execute(
                    update(WikiWriteAttemptRow)
                    .where(
                        WikiWriteAttemptRow.idempotency_key == idempotency_key,
                        WikiWriteAttemptRow.status == "pending",
                    )
                    .values(
                        status=status,
                        remote_version=remote_version,
                        completed_at=now,
                    )
                )
                if result.rowcount != 1:
                    raise ValueError("Wiki write attempt is missing or already completed")
                row = await session.get(WikiWriteAttemptRow, idempotency_key)
                if row is None:
                    raise ValueError("Wiki write attempt disappeared during completion")
                await session.refresh(row)
                return self._to_record(row)

    async def get(self, idempotency_key: uuid.UUID) -> WikiWriteAttempt | None:
        async with self._sessions() as session:
            row = await session.get(WikiWriteAttemptRow, idempotency_key)
        return self._to_record(row) if row is not None else None

    @staticmethod
    def _to_record(row: WikiWriteAttemptRow) -> WikiWriteAttempt:
        return WikiWriteAttempt(
            idempotency_key=row.idempotency_key,
            proposal_digest=row.proposal_digest,
            repository=row.repository,
            target_page=row.target_page,
            operation=row.operation,
            status=row.status,
            remote_version=row.remote_version,
            created_at=row.created_at,
            completed_at=row.completed_at,
        )


class MemoryAuditStore:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        retention_days: int = 90,
    ) -> None:
        if retention_days < 1:
            raise ValueError("retention_days must be at least 1")
        self._sessions = sessions
        self._retention_days = retention_days

    async def store_approved_memory(
        self,
        *,
        user_id: str,
        repository: str,
        memory_type: Literal["project_fact", "decision", "preference", "workflow_note"],
        content: str,
        approved_by: str,
        project_id: str | None = None,
    ) -> StoredMemory:
        memory = ApprovedMemory(
            user_id=user_id,
            repository=repository,
            project_id=project_id,
            memory_type=memory_type,
            content=content,
            approved_by=approved_by,
        )
        if any(pattern.search(memory.content) for pattern in _SECRET_PATTERNS):
            raise ValueError("Memory content appears to contain a credential")

        now = datetime.now(timezone.utc)
        row = MemoryRow(
            user_id=memory.user_id,
            repository=memory.repository,
            project_id=memory.project_id,
            memory_type=memory.memory_type,
            content=memory.content,
            approved_by=memory.approved_by,
            approved_at=now,
            created_at=now,
            expires_at=now + timedelta(days=self._retention_days),
        )
        async with self._sessions() as session:
            async with session.begin():
                session.add(row)
                session.add(
                    self._audit_row(
                        user_id=memory.user_id,
                        repository=memory.repository,
                        project_id=memory.project_id,
                        event_type="memory_store",
                        outcome="success",
                        item_count=1,
                        occurred_at=now,
                    )
                )
                await session.flush()
        return self._stored_memory(row)

    async def retrieve_memories(
        self,
        *,
        user_id: str,
        repository: str,
        project_id: str | None = None,
        limit: int = 20,
    ) -> list[StoredMemory]:
        scope = MemoryScope(
            user_id=user_id,
            repository=repository,
            project_id=project_id,
        )
        self._validate_limit(limit)
        statement = (
            select(MemoryRow)
            .where(
                MemoryRow.user_id == scope.user_id,
                MemoryRow.repository == scope.repository,
                MemoryRow.project_id == scope.project_id,
                MemoryRow.expires_at > datetime.now(timezone.utc),
            )
            .order_by(MemoryRow.created_at.desc())
            .limit(limit)
        )
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
        return [self._stored_memory(row) for row in rows]

    async def delete_project_memories(
        self,
        *,
        user_id: str,
        repository: str,
        project_id: str,
    ) -> int:
        scope = MemoryScope(
            user_id=user_id,
            repository=repository,
            project_id=project_id,
        )
        return await self._delete_memories(scope, repository_wide=False)

    async def delete_repository_memories(self, *, user_id: str, repository: str) -> int:
        scope = MemoryScope(user_id=user_id, repository=repository)
        return await self._delete_memories(scope, repository_wide=True)

    async def purge_expired_memories(self) -> int:
        now = datetime.now(timezone.utc)
        async with self._sessions() as session:
            async with session.begin():
                expired_scopes = (
                    await session.execute(
                        select(
                            MemoryRow.user_id,
                            MemoryRow.repository,
                            MemoryRow.project_id,
                            func.count(MemoryRow.id),
                        )
                        .where(MemoryRow.expires_at <= now)
                        .group_by(
                            MemoryRow.user_id,
                            MemoryRow.repository,
                            MemoryRow.project_id,
                        )
                    )
                ).all()
                result = await session.execute(
                    delete(MemoryRow).where(MemoryRow.expires_at <= now)
                )
                deleted_count = int(result.rowcount or 0)
                for user_id, repository, project_id, count in expired_scopes:
                    session.add(
                        self._audit_row(
                            user_id=user_id,
                            repository=repository,
                            project_id=project_id,
                            event_type="memory_purge",
                            outcome="success",
                            item_count=int(count),
                            occurred_at=now,
                        )
                    )
        return deleted_count

    async def record_audit_event(self, event: AuditEventInput) -> StoredAuditEvent:
        occurred_at = datetime.now(timezone.utc)
        row = self._audit_row(**event.model_dump(), occurred_at=occurred_at)
        async with self._sessions() as session:
            async with session.begin():
                session.add(row)
                await session.flush()
        return self._stored_audit_event(row)

    async def list_audit_events(
        self,
        *,
        user_id: str,
        repository: str,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[StoredAuditEvent]:
        scope = MemoryScope(
            user_id=user_id,
            repository=repository,
            project_id=project_id,
        )
        self._validate_limit(limit)
        statement = (
            select(AuditRow)
            .where(
                AuditRow.user_id == scope.user_id,
                AuditRow.repository == scope.repository,
            )
            .order_by(AuditRow.occurred_at.desc())
            .limit(limit)
        )
        if scope.project_id is not None:
            statement = statement.where(AuditRow.project_id == scope.project_id)
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
        return [self._stored_audit_event(row) for row in rows]

    async def _delete_memories(self, scope: MemoryScope, repository_wide: bool) -> int:
        conditions = [
            MemoryRow.user_id == scope.user_id,
            MemoryRow.repository == scope.repository,
        ]
        if not repository_wide:
            conditions.append(MemoryRow.project_id == scope.project_id)

        now = datetime.now(timezone.utc)
        async with self._sessions() as session:
            async with session.begin():
                result = await session.execute(delete(MemoryRow).where(*conditions))
                deleted_count = int(result.rowcount or 0)
                session.add(
                    self._audit_row(
                        user_id=scope.user_id,
                        repository=scope.repository,
                        project_id=None if repository_wide else scope.project_id,
                        event_type="memory_delete",
                        outcome="success",
                        item_count=deleted_count,
                        occurred_at=now,
                    )
                )
        return deleted_count

    @staticmethod
    def _audit_row(
        *,
        user_id: str,
        repository: str,
        event_type: str,
        outcome: str,
        occurred_at: datetime,
        project_id: str | None = None,
        request_id: uuid.UUID | None = None,
        item_count: int | None = None,
        error_code: str | None = None,
    ) -> AuditRow:
        return AuditRow(
            user_id=user_id,
            repository=repository,
            project_id=project_id,
            request_id=request_id,
            event_type=event_type,
            outcome=outcome,
            item_count=item_count,
            error_code=error_code,
            occurred_at=occurred_at,
        )

    @staticmethod
    def _stored_memory(row: MemoryRow) -> StoredMemory:
        return StoredMemory(
            id=row.id,
            user_id=row.user_id,
            repository=row.repository,
            project_id=row.project_id,
            memory_type=row.memory_type,
            content=row.content,
            approved_by=row.approved_by,
            approved_at=row.approved_at,
            created_at=row.created_at,
            expires_at=row.expires_at,
        )

    @staticmethod
    def _stored_audit_event(row: AuditRow) -> StoredAuditEvent:
        return StoredAuditEvent(
            id=row.id,
            request_id=row.request_id,
            user_id=row.user_id,
            repository=row.repository,
            project_id=row.project_id,
            event_type=row.event_type,
            outcome=row.outcome,
            item_count=row.item_count,
            error_code=row.error_code,
            occurred_at=row.occurred_at,
        )

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")


def async_database_url(settings: Settings) -> URL:
    if settings.database_url is None:
        raise ValueError("DATABASE_URL must be configured before using persistence")
    url = make_url(settings.database_url.get_secret_value())
    if url.drivername == "postgresql":
        return url.set(drivername="postgresql+asyncpg")
    if url.drivername in {"postgresql+asyncpg", "sqlite+aiosqlite"}:
        return url
    raise ValueError("DATABASE_URL must use PostgreSQL asyncpg or SQLite aiosqlite")


def create_database_engine(settings: Settings) -> AsyncEngine:
    database_url = async_database_url(settings)
    return create_async_engine(
        database_url,
        pool_pre_ping=database_url.drivername.startswith("postgresql"),
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)