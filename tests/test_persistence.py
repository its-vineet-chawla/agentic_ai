import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine

from agentic_ai.persistence import (
    AuditEventInput,
    Base,
    MemoryAuditStore,
    MemoryRow,
    create_session_factory,
)


@pytest.mark.anyio
async def test_memory_retrieval_and_deletion_are_exactly_scoped():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    store = MemoryAuditStore(create_session_factory(engine), retention_days=30)

    approved_memory = await store.store_approved_memory(
        user_id="user-a",
        repository="Octo/Project",
        project_id="sprint-12",
        memory_type="decision",
        content="Keep the status summary concise.",
        approved_by="maintainer-a",
    )
    await store.store_approved_memory(
        user_id="user-b",
        repository="octo/project",
        project_id="sprint-12",
        memory_type="preference",
        content="Use detailed reports.",
        approved_by="maintainer-b",
    )
    await store.store_approved_memory(
        user_id="user-a",
        repository="octo/project",
        project_id="sprint-13",
        memory_type="project_fact",
        content="The next sprint starts Monday.",
        approved_by="maintainer-a",
    )

    scoped_memories = await store.retrieve_memories(
        user_id="user-a",
        repository="octo/project",
        project_id="sprint-12",
    )
    assert [memory.id for memory in scoped_memories] == [approved_memory.id]
    assert await store.retrieve_memories(
        user_id="user-b",
        repository="octo/project",
        project_id="sprint-12",
    )

    deleted_count = await store.delete_project_memories(
        user_id="user-a",
        repository="octo/project",
        project_id="sprint-12",
    )
    assert deleted_count == 1
    remaining = await store.retrieve_memories(
        user_id="user-a",
        repository="octo/project",
        project_id="sprint-13",
    )
    assert len(remaining) == 1
    await engine.dispose()


@pytest.mark.anyio
async def test_expired_memory_is_not_retrieved_and_purge_is_audited():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    store = MemoryAuditStore(create_session_factory(engine), retention_days=1)
    memory = await store.store_approved_memory(
        user_id="user-a",
        repository="octo/project",
        memory_type="workflow_note",
        content="Do not retain this after expiry.",
        approved_by="maintainer-a",
    )
    async with store._sessions() as session:
        async with session.begin():
            await session.execute(
                update(MemoryRow)
                .where(MemoryRow.id == memory.id)
                .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
            )

    assert await store.retrieve_memories(user_id="user-a", repository="octo/project") == []
    assert await store.purge_expired_memories() == 1
    events = await store.list_audit_events(user_id="user-a", repository="octo/project")
    assert [event.event_type for event in events] == ["memory_purge", "memory_store"]
    await engine.dispose()


@pytest.mark.anyio
async def test_memory_rejects_common_credential_formats_and_audit_has_no_free_form_payload():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    store = MemoryAuditStore(create_session_factory(engine))

    with pytest.raises(ValueError, match="credential"):
        await store.store_approved_memory(
            user_id="user-a",
            repository="octo/project",
            memory_type="decision",
            content="The API key is AIza123456789012345678901234567890123456789.",
            approved_by="maintainer-a",
        )

    with pytest.raises(ValueError):
        AuditEventInput.model_validate(
            {
                "user_id": "user-a",
                "repository": "octo/project",
                "event_type": "analysis",
                "outcome": "success",
                "details": "raw GitHub content must not be audited",
            }
        )

    request_id = uuid4()
    event = await store.record_audit_event(
        AuditEventInput(
            user_id="user-a",
            repository="octo/project",
            request_id=request_id,
            event_type="analysis",
            outcome="success",
            item_count=3,
        )
    )
    assert event.item_count == 3
    assert event.request_id == request_id
    assert not hasattr(event, "details")
    await engine.dispose()


@pytest.mark.anyio
async def test_repository_deletion_removes_project_memory_and_audits_scope():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    store = MemoryAuditStore(create_session_factory(engine))
    for project_id in ("sprint-1", "sprint-2"):
        await store.store_approved_memory(
            user_id="user-a",
            repository="octo/project",
            project_id=project_id,
            memory_type="decision",
            content=f"Decision for {project_id}.",
            approved_by="maintainer-a",
        )

    assert await store.delete_repository_memories(
        user_id="user-a",
        repository="octo/project",
    ) == 2
    assert await store.retrieve_memories(
        user_id="user-a",
        repository="octo/project",
        project_id="sprint-1",
    ) == []
    audit_events = await store.list_audit_events(user_id="user-a", repository="octo/project")
    assert audit_events[0].event_type == "memory_delete"
    assert audit_events[0].item_count == 2
    await engine.dispose()


def test_alembic_initial_migration_creates_postgresql_schema_on_sqlite(tmp_path, monkeypatch):
    database_file = tmp_path / "migration-test.sqlite3"
    database_url = f"sqlite+aiosqlite:///{database_file.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.upgrade(Config("alembic.ini"), "head")

    with sqlite3.connect(database_file) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {"memory_records", "audit_records", "wiki_write_attempts", "alembic_version"} <= tables

    command.downgrade(Config("alembic.ini"), "base")
    with sqlite3.connect(database_file) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "memory_records" not in tables
    assert "audit_records" not in tables
    assert "wiki_write_attempts" not in tables