import hashlib
import inspect
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from agentic_ai.models import (
    ProposedWikiChange,
    WikiApproval,
    WikiCapabilities,
    WikiPageSnapshot,
    WikiPublicationResult,
    WikiWriteReceipt,
)
from agentic_ai.persistence import (
    AuditEventInput,
    DuplicateWikiWriteAttempt,
    MemoryAuditStore,
    WikiWriteAttemptStore,
)


class WikiPublishingError(RuntimeError):
    pass


class WikiIntegrationUnavailable(WikiPublishingError):
    pass


class WikiApprovalRejected(WikiPublishingError):
    pass


class WikiPageConflict(WikiPublishingError):
    pass


class WikiDuplicatePublication(WikiPublishingError):
    pass


class WikiWriteUncertain(WikiPublishingError):
    pass


class WikiAdapter(Protocol):
    async def capabilities(self) -> WikiCapabilities: ...

    async def read_page(self, repository: str, target_page: str) -> WikiPageSnapshot: ...

    async def create_page(
        self,
        proposal: ProposedWikiChange,
        idempotency_key: UUID,
    ) -> WikiWriteReceipt: ...

    async def update_page(
        self,
        proposal: ProposedWikiChange,
        expected_version: str,
        idempotency_key: UUID,
    ) -> WikiWriteReceipt: ...


ReviewerAuthorizer = Callable[[str], Awaitable[bool] | bool]


class UnavailableWikiAdapter:
    async def capabilities(self) -> WikiCapabilities:
        return WikiCapabilities(
            adapter_name="unconfigured",
            verified=False,
            can_read_pages=False,
            can_create_pages=False,
            can_update_pages=False,
        )

    async def read_page(self, repository: str, target_page: str) -> WikiPageSnapshot:
        raise WikiIntegrationUnavailable("No GitHub wiki adapter is configured.")

    async def create_page(
        self,
        proposal: ProposedWikiChange,
        idempotency_key: UUID,
    ) -> WikiWriteReceipt:
        raise WikiIntegrationUnavailable("No GitHub wiki adapter is configured.")

    async def update_page(
        self,
        proposal: ProposedWikiChange,
        expected_version: str,
        idempotency_key: UUID,
    ) -> WikiWriteReceipt:
        raise WikiIntegrationUnavailable("No GitHub wiki adapter is configured.")


class ApprovalGatedWikiPublisher:
    def __init__(
        self,
        adapter: WikiAdapter,
        attempt_store: WikiWriteAttemptStore,
        audit_store: MemoryAuditStore,
        allowed_repositories: set[str],
        reviewer_authorizer: ReviewerAuthorizer,
    ) -> None:
        self._adapter = adapter
        self._attempt_store = attempt_store
        self._audit_store = audit_store
        self._allowed_repositories = {repository.casefold() for repository in allowed_repositories}
        self._reviewer_authorizer = reviewer_authorizer

    async def publish(
        self,
        proposal: ProposedWikiChange,
        approval: WikiApproval,
    ) -> WikiPublicationResult:
        repository = proposal.repository.casefold()
        if repository not in self._allowed_repositories:
            await self._record_event(proposal, approval, "denied", "scope_denied")
            raise WikiApprovalRejected("Repository is not in the configured wiki allowlist.")

        expected_digest = self.proposal_digest(proposal)
        if not approval.approved or approval.proposal_digest != expected_digest:
            await self._record_event(proposal, approval, "denied", "validation_failed")
            raise WikiApprovalRejected("Approval does not match this exact wiki proposal.")

        authorized = self._reviewer_authorizer(approval.reviewer_id)
        if inspect.isawaitable(authorized):
            authorized = await authorized
        if not authorized:
            await self._record_event(proposal, approval, "denied", "scope_denied")
            raise WikiApprovalRejected("Reviewer is not authorized to publish wiki changes.")

        capabilities = await self._adapter.capabilities()
        can_write = (
            capabilities.can_create_pages
            if proposal.operation == "create"
            else capabilities.can_update_pages
        )
        if not capabilities.verified or not capabilities.can_read_pages or not can_write:
            await self._record_event(
                proposal,
                approval,
                "denied",
                "dependency_unavailable",
            )
            raise WikiIntegrationUnavailable(
                "The configured GitHub MCP integration has no verified wiki capability; "
                "the draft was not written."
            )

        try:
            current_page = await self._adapter.read_page(repository, proposal.target_page)
        except Exception as error:
            await self._record_event(proposal, approval, "failure", "dependency_unavailable")
            raise WikiIntegrationUnavailable(
                "Could not read the target wiki page; no change was written."
            ) from error
        if proposal.operation == "create":
            if current_page.exists or approval.expected_page_version is not None:
                await self._record_event(proposal, approval, "denied", "conflict")
                raise WikiPageConflict("The wiki page already exists or the approval is stale.")
        elif (
            not current_page.exists
            or not approval.expected_page_version
            or current_page.version != approval.expected_page_version
        ):
            await self._record_event(proposal, approval, "denied", "conflict")
            raise WikiPageConflict("The wiki page changed after review; request a new approval.")

        try:
            await self._attempt_store.claim(
                idempotency_key=approval.idempotency_key,
                proposal_digest=expected_digest,
                repository=repository,
                target_page=proposal.target_page,
                operation=proposal.operation,
            )
        except DuplicateWikiWriteAttempt as error:
            await self._record_event(proposal, approval, "denied", "conflict")
            raise WikiDuplicatePublication(str(error)) from error

        try:
            if proposal.operation == "create":
                receipt = await self._adapter.create_page(proposal, approval.idempotency_key)
            else:
                receipt = await self._adapter.update_page(
                    proposal,
                    approval.expected_page_version,
                    approval.idempotency_key,
                )
        except Exception as error:
            await self._attempt_store.complete(
                approval.idempotency_key,
                status="uncertain",
            )
            await self._record_event(proposal, approval, "failure", "dependency_unavailable")
            raise WikiWriteUncertain(
                "Wiki write outcome is uncertain. Do not retry this proposal automatically."
            ) from error

        if (
            receipt.repository.casefold() != repository
            or receipt.target_page != proposal.target_page
        ):
            await self._attempt_store.complete(
                approval.idempotency_key,
                status="uncertain",
                remote_version=receipt.version,
            )
            await self._record_event(proposal, approval, "failure", "validation_failed")
            raise WikiWriteUncertain("Wiki adapter returned a receipt for a different target.")

        await self._attempt_store.complete(
            approval.idempotency_key,
            status="succeeded",
            remote_version=receipt.version,
        )
        await self._record_event(proposal, approval, "success", None)
        return WikiPublicationResult(
            proposal=proposal,
            reviewer_id=approval.reviewer_id,
            idempotency_key=approval.idempotency_key,
            outcome="success",
            receipt=receipt,
            completed_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def proposal_digest(proposal: ProposedWikiChange) -> str:
        canonical_proposal = json.dumps(
            proposal.model_dump(mode="json"),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical_proposal.encode("utf-8")).hexdigest()

    async def _record_event(
        self,
        proposal: ProposedWikiChange,
        approval: WikiApproval,
        outcome: str,
        error_code: str | None,
    ) -> None:
        await self._audit_store.record_audit_event(
            AuditEventInput(
                user_id=approval.reviewer_id,
                repository=proposal.repository,
                request_id=approval.idempotency_key,
                event_type="wiki_write",
                outcome=outcome,
                item_count=1 if outcome == "success" else None,
                error_code=error_code,
            )
        )