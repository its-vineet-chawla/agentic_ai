from datetime import datetime, timezone
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, PositiveInt


class GitHubModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceReference(GitHubModel):
    kind: Literal["repository", "issue", "pull_request", "commit"]
    identifier: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: AnyHttpUrl


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
    summary: str = Field(min_length=1)
    findings: list[str] = Field(default_factory=list)
    sources: list[SourceReference] = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))