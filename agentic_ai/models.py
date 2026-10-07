from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    field_validator,
    model_validator,
)


DocumentType = Literal["sprint_status", "project_documentation", "release_notes"]


class GitHubModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceReference(GitHubModel):
    kind: Literal["repository", "issue", "pull_request", "commit"]
    identifier: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: AnyHttpUrl


class GitHubRepository(GitHubModel):
    full_name: str = Field(min_length=1)
    description: str | None = None
    url: AnyHttpUrl
    default_branch: str = Field(min_length=1)


class GitHubCommit(GitHubModel):
    sha: str = Field(min_length=1)
    message: str = Field(min_length=1)
    url: AnyHttpUrl
    author: str | None = None
    committed_at: datetime | None = None


class GitHubWorkItem(GitHubModel):
    repository: str = Field(min_length=1)
    number: PositiveInt
    title: str = Field(min_length=1)
    body: str | None = None
    url: AnyHttpUrl
    labels: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class GitHubIssue(GitHubWorkItem):
    state: Literal["open", "closed"]


class GitHubPullRequest(GitHubWorkItem):
    state: Literal["open", "closed", "merged"]
    is_draft: bool = False


class AnalysisResult(GitHubModel):
    summary: str = Field(min_length=1, max_length=2000)
    findings: list[str] = Field(default_factory=list, max_length=20)
    sources: list[SourceReference] = Field(min_length=1, max_length=100)
    summary_sources: list[SourceReference] = Field(min_length=1, max_length=10)
    finding_sources: list[list[SourceReference]] = Field(default_factory=list, max_length=20)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_finding_sources(self) -> "AnalysisResult":
        if len(self.finding_sources) != len(self.findings):
            raise ValueError("Each finding must have an aligned source list")
        cited_sources = self.summary_sources + [
            source for finding_source_list in self.finding_sources for source in finding_source_list
        ]
        if any(not finding_source_list for finding_source_list in self.finding_sources):
            raise ValueError("Each finding must cite at least one source")
        if any(source not in self.sources for source in cited_sources):
            raise ValueError("Citations must be included in the analysis source list")
        return self


class ProposedWikiChange(GitHubModel):
    operation: Literal["create", "update"]
    repository: str = Field(min_length=3, max_length=255)
    target_page: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=20000)
    sources: list[SourceReference] = Field(min_length=1)

    @field_validator("repository")
    @classmethod
    def normalize_repository(cls, value: str) -> str:
        repository = value.casefold()
        if repository.count("/") != 1 or not all(repository.split("/")):
            raise ValueError("Repository must use the owner/name format")
        return repository


class WikiApproval(GitHubModel):
    reviewer_id: str = Field(min_length=1, max_length=255)
    approved: bool
    approved_at: datetime
    proposal_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: UUID
    expected_page_version: str | None = Field(default=None, max_length=255)


class WikiCapabilities(GitHubModel):
    adapter_name: str = Field(min_length=1, max_length=100)
    verified: bool
    can_read_pages: bool
    can_create_pages: bool
    can_update_pages: bool


class WikiPageSnapshot(GitHubModel):
    repository: str = Field(min_length=3, max_length=255)
    target_page: str = Field(min_length=1, max_length=255)
    exists: bool
    version: str | None = Field(default=None, max_length=255)
    url: AnyHttpUrl | None = None
    content: str | None = Field(default=None, max_length=20000)


class WikiWriteReceipt(GitHubModel):
    repository: str = Field(min_length=3, max_length=255)
    target_page: str = Field(min_length=1, max_length=255)
    url: AnyHttpUrl
    version: str = Field(min_length=1, max_length=255)


class WikiPublicationResult(GitHubModel):
    proposal: ProposedWikiChange
    reviewer_id: str = Field(min_length=1, max_length=255)
    idempotency_key: UUID
    outcome: Literal["success"]
    receipt: WikiWriteReceipt
    completed_at: datetime


class GeneratedDocumentContent(GitHubModel):
    markdown: str = Field(min_length=1, max_length=12000)
    source_ids: list[str] = Field(min_length=1, max_length=50)


class DocumentationDraftRequest(GitHubModel):
    document_type: DocumentType
    operation: Literal["create", "update"]
    repository: str = Field(min_length=3, max_length=255)
    target_page: str = Field(min_length=1, max_length=255)
    evidence: str = Field(min_length=1, max_length=100000)
    sources: list[SourceReference] = Field(min_length=1, max_length=100)
    scope_description: str | None = Field(default=None, max_length=500)

    @field_validator("repository")
    @classmethod
    def normalize_repository(cls, value: str) -> str:
        repository = value.casefold()
        if repository.count("/") != 1 or not all(repository.split("/")):
            raise ValueError("Repository must use the owner/name format")
        return repository

    @model_validator(mode="after")
    def validate_document_scope(self) -> "DocumentationDraftRequest":
        if self.document_type in {"sprint_status", "release_notes"} and not self.scope_description:
            raise ValueError("Sprint status and release notes require an explicit scope description")
        return self