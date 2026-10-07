from datetime import datetime, timezone

import pytest

from agentic_ai.config import Settings
from agentic_ai.github_mcp import GitHubMCPClient
from agentic_ai.models import (
    AnalysisResult,
    GitHubIssue,
    GitHubPullRequest,
    GitHubRepository,
    SourceReference,
)
from agentic_ai.workflows import RepositoryStatusError, RepositoryStatusWorkflow


class FakeGitHubClient:
    def __init__(self):
        self.issue_request = None
        self.pull_request_request = None

    async def get_repository(self, repository):
        return GitHubRepository(
            full_name=repository,
            description="Project repository",
            url="https://github.com/octo/project",
            default_branch="main",
        )

    async def list_issues(self, repository, state=None, limit=100):
        self.issue_request = (repository, state, limit)
        return [
            GitHubIssue(
                repository=repository,
                number=42,
                title="Search is slow",
                body="Optimize the search path.",
                url="https://github.com/octo/project/issues/42",
                created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                updated_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
                state="open",
            )
        ]

    async def list_pull_requests(self, repository, state=None, limit=100):
        self.pull_request_request = (repository, state, limit)
        return [
            GitHubPullRequest(
                repository=repository,
                number=17,
                title="Use indexed search",
                body="Adds an index for search queries.",
                url="https://github.com/octo/project/pull/17",
                created_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
                updated_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
                state="open",
                is_draft=False,
            )
        ]


class FakeModelClient:
    def __init__(self):
        self.evidence = None
        self.sources = None
        self.call_count = 0

    async def analyze(self, evidence, sources):
        self.call_count += 1
        self.evidence = evidence
        self.sources = sources
        return AnalysisResult(
            summary="Two active work items.",
            sources=sources,
            summary_sources=sources,
        )


@pytest.mark.anyio
async def test_repository_status_workflow_retrieves_and_summarizes_open_work():
    github_client = FakeGitHubClient()
    model_client = FakeModelClient()
    workflow = RepositoryStatusWorkflow(github_client, model_client, item_limit=12)

    result = await workflow.run("octo/project")

    assert github_client.issue_request == ("octo/project", "open", 12)
    assert github_client.pull_request_request == ("octo/project", "open", 12)
    assert result.summary == "Two active work items."
    assert [source.kind for source in result.sources] == [
        "repository",
        "issue",
        "pull_request",
    ]
    assert [str(source.url) for source in result.sources] == [
        "https://github.com/octo/project",
        "https://github.com/octo/project/issues/42",
        "https://github.com/octo/project/pull/17",
    ]
    assert "Search is slow" in model_client.evidence
    assert "Use indexed search" in model_client.evidence
    assert model_client.sources == result.sources


@pytest.mark.anyio
async def test_repository_status_workflow_does_not_return_success_on_retrieval_failure():
    class FailingGitHubClient(FakeGitHubClient):
        async def list_issues(self, repository, state=None, limit=100):
            raise RuntimeError("GitHub unavailable")

    workflow = RepositoryStatusWorkflow(FailingGitHubClient(), FakeModelClient())

    with pytest.raises(RepositoryStatusError, match="GitHub retrieval failed"):
        await workflow.run("octo/project")


@pytest.mark.anyio
async def test_repository_status_workflow_blocks_unallowlisted_scope_before_model():
    github_client = GitHubMCPClient(
        Settings(
            _env_file=None,
            github_allowed_repositories=["octo/approved"],
        ),
    )
    model_client = FakeModelClient()
    workflow = RepositoryStatusWorkflow(github_client, model_client)

    with pytest.raises(RepositoryStatusError, match="GitHub retrieval failed"):
        await workflow.run("octo/private")

    assert model_client.call_count == 0


def test_repository_status_workflow_rejects_nonpositive_item_limit():
    with pytest.raises(ValueError, match="item_limit"):
        RepositoryStatusWorkflow(FakeGitHubClient(), FakeModelClient(), item_limit=0)