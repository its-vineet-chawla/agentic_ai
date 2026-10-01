from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agentic_ai.models import AnalysisResult, GitHubIssue, GitHubPullRequest, SourceReference


def work_item_data(**overrides):
    data = {
        "repository": "octo/project",
        "number": 42,
        "title": "Improve search",
        "body": "Search should be faster.",
        "url": "https://github.com/octo/project/issues/42",
        "labels": ["performance"],
        "created_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 9, 2, tzinfo=timezone.utc),
    }
    return data | overrides


def test_github_issue_accepts_valid_issue_data():
    issue = GitHubIssue(**work_item_data(state="open"))

    assert issue.repository == "octo/project"
    assert issue.number == 42
    assert issue.state == "open"


def test_github_issue_rejects_invalid_state():
    with pytest.raises(ValidationError):
        GitHubIssue(**work_item_data(state="merged"))


def test_github_pull_request_accepts_merged_state():
    pull_request = GitHubPullRequest(**work_item_data(state="merged"))

    assert pull_request.state == "merged"
    assert pull_request.is_draft is False


def test_analysis_result_requires_source_references():
    with pytest.raises(ValidationError):
        AnalysisResult(summary="Recent project changes", sources=[])


def test_analysis_result_defaults_timestamp_and_accepts_source():
    source = SourceReference(
        kind="pull_request",
        identifier="42",
        title="Improve search",
        url="https://github.com/octo/project/pull/42",
    )

    result = AnalysisResult(summary="Search performance improved.", sources=[source])

    assert result.sources == [source]
    assert result.created_at.tzinfo is timezone.utc