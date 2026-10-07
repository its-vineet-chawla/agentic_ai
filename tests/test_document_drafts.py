import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agentic_ai.config import Settings
from agentic_ai.google_model import GoogleModelClient, GoogleModelError
from agentic_ai.models import GeneratedDocumentContent, SourceReference
from agentic_ai.workflows import DocumentationDraftError, DocumentationDraftWorkflow


def document_sources():
    return [
        SourceReference(
            kind="issue",
            identifier="42",
            title="Search [42]\nperformance",
            url="https://github.com/octo/project/issues/42",
        ),
        SourceReference(
            kind="pull_request",
            identifier="17",
            title="Use indexed search",
            url="https://github.com/octo/project/pull/17",
        ),
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("document_type", "scope_description", "instruction"),
    [
        (
            "sprint_status",
            "Sprint 12, 2026-09-01 through 2026-09-14",
            "Do not infer sprint membership",
        ),
        (
            "project_documentation",
            None,
            "do not invent architecture",
        ),
        (
            "release_notes",
            "Release 2.4, changes merged by 2026-09-30",
            "Do not describe unmerged pull requests",
        ),
    ],
)
async def test_google_document_generation_uses_scope_and_source_identifiers(
    document_type,
    scope_description,
    instruction,
):
    captured = {}

    class FakeInteractions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                output_text=json.dumps(
                    {
                        "markdown": "# Project update\n\nVerified change summary.",
                        "source_ids": ["issue:42", "pull_request:17"],
                    }
                )
            )

    class FakeAsyncClient:
        interactions = FakeInteractions()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

    client = GoogleModelClient(
        Settings(_env_file=None, google_api_key="test-key"),
        client_factory=lambda api_key: SimpleNamespace(aio=FakeAsyncClient()),
    )

    draft = await client.generate_document(
        document_type=document_type,
        evidence="A merged PR adds indexed search.",
        sources=document_sources(),
        scope_description=scope_description,
    )

    input_data = json.loads(captured["input"])
    assert input_data["document_type"] == document_type
    assert input_data["scope_description"] == scope_description
    assert input_data["sources"][0]["source_id"] == "issue:42"
    assert captured["store"] is False
    assert instruction in captured["system_instruction"]
    assert draft.source_ids == ["issue:42", "pull_request:17"]


@pytest.mark.anyio
async def test_google_document_generation_rejects_unknown_sources_and_model_links():
    class FakeInteractions:
        output_text = ""

        async def create(self, **kwargs):
            return SimpleNamespace(output_text=self.output_text)

    interactions = FakeInteractions()

    class FakeAsyncClient:
        async def __aenter__(self):
            self.interactions = interactions
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

    client = GoogleModelClient(
        Settings(_env_file=None, google_api_key="test-key"),
        client_factory=lambda api_key: SimpleNamespace(aio=FakeAsyncClient()),
    )

    interactions.output_text = json.dumps(
        {"markdown": "A claim.", "source_ids": ["issue:404"]}
    )
    with pytest.raises(GoogleModelError, match="outside the supplied GitHub evidence"):
        await client.generate_document(
            "project_documentation",
            "Evidence",
            document_sources(),
        )

    interactions.output_text = json.dumps(
        {
            "markdown": "See https://malicious.example for details.",
            "source_ids": ["issue:42"],
        }
    )
    with pytest.raises(GoogleModelError, match="untrusted URL"):
        await client.generate_document(
            "project_documentation",
            "Evidence",
            document_sources(),
        )


@pytest.mark.anyio
async def test_documentation_draft_workflow_returns_reviewable_change_with_trusted_links():
    class FakeModelClient:
        async def generate_document(self, **kwargs):
            return GeneratedDocumentContent(
                markdown="# Sprint 12\n\nTwo active work items.",
                source_ids=["issue:42", "pull_request:17"],
            )

    workflow = DocumentationDraftWorkflow(FakeModelClient())

    proposal = await workflow.run(
        document_type="sprint_status",
        operation="update",
        repository="Octo/Project",
        target_page="Sprint-12",
        evidence="Issue 42 and PR 17 are in Sprint 12.",
        sources=document_sources(),
        scope_description="Sprint 12, 2026-09-01 through 2026-09-14",
    )

    assert proposal.operation == "update"
    assert proposal.repository == "octo/project"
    assert proposal.target_page == "Sprint-12"
    assert "## Sources" in proposal.content
    assert r"Search \[42\] performance" in proposal.content
    assert "https://github.com/octo/project/issues/42" in proposal.content
    assert "https://github.com/octo/project/pull/17" in proposal.content
    assert proposal.sources == document_sources()


@pytest.mark.anyio
async def test_documentation_draft_workflow_rejects_missing_sprint_or_release_scope():
    workflow = DocumentationDraftWorkflow(object())
    common_request = {
        "operation": "create",
        "repository": "octo/project",
        "target_page": "Draft",
        "evidence": "Evidence",
        "sources": document_sources(),
    }

    with pytest.raises(ValidationError, match="explicit scope description"):
        await workflow.run(document_type="sprint_status", **common_request)

    with pytest.raises(ValidationError, match="explicit scope description"):
        await workflow.run(document_type="release_notes", **common_request)


@pytest.mark.anyio
async def test_documentation_draft_workflow_rejects_provider_citations_not_in_request():
    class FakeModelClient:
        async def generate_document(self, **kwargs):
            return GeneratedDocumentContent(
                markdown="Unsupported draft.",
                source_ids=["commit:unknown"],
            )

    workflow = DocumentationDraftWorkflow(FakeModelClient())

    with pytest.raises(DocumentationDraftError, match="outside the supplied evidence"):
        await workflow.run(
            document_type="project_documentation",
            operation="create",
            repository="octo/project",
            target_page="Project-overview",
            evidence="Evidence",
            sources=document_sources(),
        )