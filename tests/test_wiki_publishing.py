from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from agentic_ai.models import (
    ProposedWikiChange,
    SourceReference,
    WikiApproval,
    WikiCapabilities,
    WikiPageSnapshot,
    WikiWriteReceipt,
)
from agentic_ai.persistence import (
    Base,
    MemoryAuditStore,
    WikiWriteAttemptStore,
    create_session_factory,
)
from agentic_ai.wiki_publishing import (
    ApprovalGatedWikiPublisher,
    UnavailableWikiAdapter,
    WikiApprovalRejected,
    WikiDuplicatePublication,
    WikiIntegrationUnavailable,
    WikiPageConflict,
    WikiWriteUncertain,
)


def make_proposal(operation="create"):
    return ProposedWikiChange(
        operation=operation,
        repository="octo/project",
        target_page="Release-notes",
        content="# Release notes\n\n- Faster search.",
        sources=[
            SourceReference(
                kind="pull_request",
                identifier="17",
                title="Faster search",
                url="https://github.com/octo/project/pull/17",
            )
        ],
    )


def make_approval(publisher, proposal, expected_page_version=None):
    return WikiApproval(
        reviewer_id="maintainer-a",
        approved=True,
        approved_at=datetime.now(timezone.utc),
        proposal_digest=publisher.proposal_digest(proposal),
        idempotency_key=uuid4(),
        expected_page_version=expected_page_version,
    )


class FakeWikiAdapter:
    def __init__(self, *, capabilities=None, page=None):
        self._capabilities = capabilities or WikiCapabilities(
            adapter_name="test-wiki",
            verified=True,
            can_read_pages=True,
            can_create_pages=True,
            can_update_pages=True,
        )
        self._page = page
        self.create_calls = 0
        self.update_calls = 0

    async def capabilities(self):
        return self._capabilities

    async def read_page(self, repository, target_page):
        return self._page or WikiPageSnapshot(
            repository=repository,
            target_page=target_page,
            exists=False,
        )

    async def create_page(self, proposal, idempotency_key):
        self.create_calls += 1
        return WikiWriteReceipt(
            repository=proposal.repository,
            target_page=proposal.target_page,
            url="https://github.com/octo/project/wiki/Release-notes",
            version="wiki-v2",
        )

    async def update_page(self, proposal, expected_version, idempotency_key):
        self.update_calls += 1
        return WikiWriteReceipt(
            repository=proposal.repository,
            target_page=proposal.target_page,
            url="https://github.com/octo/project/wiki/Release-notes",
            version="wiki-v3",
        )


async def make_publisher(adapter, authorized=True):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = create_session_factory(engine)
    publisher = ApprovalGatedWikiPublisher(
        adapter,
        WikiWriteAttemptStore(sessions),
        MemoryAuditStore(sessions),
        {"octo/project"},
        lambda reviewer_id: authorized and reviewer_id == "maintainer-a",
    )
    return publisher, engine


@pytest.mark.anyio
async def test_unavailable_wiki_capability_fails_closed_and_preserves_proposal():
    proposal = make_proposal()
    adapter = UnavailableWikiAdapter()
    publisher, engine = await make_publisher(adapter)
    approval = make_approval(publisher, proposal)

    with pytest.raises(WikiIntegrationUnavailable, match="draft was not written"):
        await publisher.publish(proposal, approval)

    attempt = await publisher._attempt_store.get(approval.idempotency_key)
    audit_events = await publisher._audit_store.list_audit_events(
        user_id=approval.reviewer_id,
        repository=proposal.repository,
    )
    assert attempt is None
    assert audit_events[0].outcome == "denied"
    await engine.dispose()


@pytest.mark.anyio
async def test_approved_create_publishes_once_and_records_audit():
    proposal = make_proposal()
    adapter = FakeWikiAdapter()
    publisher, engine = await make_publisher(adapter)
    approval = make_approval(publisher, proposal)

    publication = await publisher.publish(proposal, approval)

    assert str(publication.receipt.url) == "https://github.com/octo/project/wiki/Release-notes"
    assert publication.proposal == proposal
    assert publication.reviewer_id == approval.reviewer_id
    assert publication.idempotency_key == approval.idempotency_key
    assert publication.outcome == "success"
    assert publication.completed_at is not None
    assert adapter.create_calls == 1
    attempt = await publisher._attempt_store.get(approval.idempotency_key)
    assert attempt is not None
    assert attempt.status == "succeeded"
    assert attempt.remote_version == "wiki-v2"

    with pytest.raises(WikiDuplicatePublication):
        await publisher.publish(proposal, approval)
    assert adapter.create_calls == 1

    audit_events = await publisher._audit_store.list_audit_events(
        user_id=approval.reviewer_id,
        repository=proposal.repository,
    )
    assert [event.outcome for event in audit_events] == ["denied", "success"]
    await engine.dispose()


@pytest.mark.anyio
async def test_update_conflict_stops_before_persistent_attempt_or_write():
    proposal = make_proposal(operation="update")
    adapter = FakeWikiAdapter(
        page=WikiPageSnapshot(
            repository=proposal.repository,
            target_page=proposal.target_page,
            exists=True,
            version="wiki-v3",
            url="https://github.com/octo/project/wiki/Release-notes",
        )
    )
    publisher, engine = await make_publisher(adapter)
    approval = make_approval(publisher, proposal, expected_page_version="wiki-v2")

    with pytest.raises(WikiPageConflict, match="changed after review"):
        await publisher.publish(proposal, approval)

    assert adapter.update_calls == 0
    assert await publisher._attempt_store.get(approval.idempotency_key) is None
    await engine.dispose()


@pytest.mark.anyio
async def test_unapproved_or_unauthorized_reviewer_cannot_publish():
    proposal = make_proposal()
    adapter = FakeWikiAdapter()
    publisher, engine = await make_publisher(adapter, authorized=False)
    approval = make_approval(publisher, proposal)

    with pytest.raises(WikiApprovalRejected, match="not authorized"):
        await publisher.publish(proposal, approval)

    assert adapter.create_calls == 0
    assert await publisher._attempt_store.get(approval.idempotency_key) is None

    authorized_publisher, authorized_engine = await make_publisher(adapter)
    rejected_approval = make_approval(authorized_publisher, proposal)
    rejected_approval = rejected_approval.model_copy(update={"approved": False})
    with pytest.raises(WikiApprovalRejected, match="does not match"):
        await authorized_publisher.publish(proposal, rejected_approval)
    assert adapter.create_calls == 0
    await authorized_engine.dispose()
    await engine.dispose()


@pytest.mark.anyio
async def test_approval_digest_rejects_modified_proposal():
    proposal = make_proposal()
    publisher, engine = await make_publisher(FakeWikiAdapter())
    approval = make_approval(publisher, proposal)
    modified_proposal = proposal.model_copy(update={"content": "Changed after approval."})

    with pytest.raises(WikiApprovalRejected, match="exact wiki proposal"):
        await publisher.publish(modified_proposal, approval)

    await engine.dispose()


@pytest.mark.anyio
async def test_uncertain_remote_write_is_marked_and_never_retried_automatically():
    class UncertainWikiAdapter(FakeWikiAdapter):
        async def create_page(self, proposal, idempotency_key):
            self.create_calls += 1
            raise TimeoutError("remote response was lost")

    proposal = make_proposal()
    adapter = UncertainWikiAdapter()
    publisher, engine = await make_publisher(adapter)
    approval = make_approval(publisher, proposal)

    with pytest.raises(WikiWriteUncertain, match="Do not retry"):
        await publisher.publish(proposal, approval)

    attempt = await publisher._attempt_store.get(approval.idempotency_key)
    assert attempt is not None
    assert attempt.status == "uncertain"
    with pytest.raises(WikiDuplicatePublication):
        await publisher.publish(proposal, approval)
    assert adapter.create_calls == 1
    await engine.dispose()