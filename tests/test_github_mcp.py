from types import SimpleNamespace
from typing import cast

import pytest
from mcp import Client
from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from agentic_ai.config import Settings
from agentic_ai.github_mcp import GitHubMCPClient, GitHubMCPError


def configured_settings(**overrides):
    values = {
        "github_mcp_url": "https://api.githubcopilot.com/mcp/",
        "github_mcp_token": "test-token",
        "github_allowed_repositories": ["octo/project"],
        "_env_file": None,
    }
    return Settings(**(values | overrides))


@pytest.mark.anyio
async def test_verify_connection_checks_identity_and_only_reports_read_tools():
    server = MCPServer("GitHub test")

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    def get_me() -> dict[str, str]:
        return {"login": "octo"}

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    def read_repository() -> str:
        return "repository metadata"

    @server.tool(annotations=ToolAnnotations(read_only_hint=False))
    def create_issue() -> str:
        return "created"

    client = GitHubMCPClient(
        configured_settings(),
        client_factory=lambda: Client(server),
    )

    status = await client.verify_connection()

    assert status.server_name == "GitHub test"
    assert status.read_only_tools == ("get_me", "read_repository")


def test_validate_repository_is_case_insensitive_and_enforces_allowlist():
    client = GitHubMCPClient(configured_settings())

    assert client.validate_repository("Octo/Project") == "octo/project"

    with pytest.raises(GitHubMCPError, match="allowlist"):
        client.validate_repository("octo/private-project")


@pytest.mark.anyio
async def test_verify_connection_requires_endpoint_token_and_allowlist():
    client = GitHubMCPClient(
        configured_settings(github_mcp_token=None),
        client_factory=lambda: Client(MCPServer("unused")),
    )

    with pytest.raises(GitHubMCPError, match="GITHUB_MCP_TOKEN"):
        await client.verify_connection()


@pytest.mark.anyio
async def test_verify_connection_reports_authentication_tool_failures():
    class FailedIdentityClient:
        server_info = SimpleNamespace(name="GitHub test")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

        async def list_tools(self, cursor=None):
            tool = SimpleNamespace(
                name="get_me",
                annotations=SimpleNamespace(read_only_hint=True),
            )
            return SimpleNamespace(tools=[tool], next_cursor=None)

        async def call_tool(self, name, arguments):
            return SimpleNamespace(is_error=True)

    client = GitHubMCPClient(
        configured_settings(),
        client_factory=lambda: cast(Client, FailedIdentityClient()),
    )

    with pytest.raises(GitHubMCPError, match="authentication check failed"):
        await client.verify_connection()


@pytest.mark.anyio
async def test_tool_discovery_follows_pagination_cursors():
    class PaginatedClient:
        def __init__(self):
            self.cursors = []

        async def list_tools(self, cursor=None):
            self.cursors.append(cursor)
            next_cursor = "page-2" if cursor is None else None
            return SimpleNamespace(tools=[], next_cursor=next_cursor)

    paginated_client = PaginatedClient()
    client = GitHubMCPClient(configured_settings())

    tools = await client._list_all_tools(cast(Client, paginated_client))

    assert tools == []
    assert paginated_client.cursors == [None, "page-2"]


@pytest.mark.anyio
async def test_get_repository_matches_exact_allowlisted_repository():
    server = MCPServer("GitHub test")

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    def search_repositories(query: str, minimal_output: bool = True) -> dict:
        return {
            "items": [
                {
                    "full_name": "octo/project-tools",
                    "html_url": "https://github.com/octo/project-tools",
                    "description": "Not the requested project",
                    "default_branch": "main",
                },
                {
                    "full_name": "octo/project",
                    "html_url": "https://github.com/octo/project",
                    "description": "Requested project",
                    "default_branch": "trunk",
                },
            ]
        }

    client = GitHubMCPClient(
        configured_settings(),
        client_factory=lambda: Client(server),
    )

    repository = await client.get_repository("Octo/Project")

    assert repository.full_name == "octo/project"
    assert repository.default_branch == "trunk"
    assert str(repository.url) == "https://github.com/octo/project"


@pytest.mark.anyio
async def test_list_issues_uses_cursor_pagination_and_preserves_source_links():
    server = MCPServer("GitHub test")
    received_cursors = []

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    def list_issues(
        owner: str,
        repo: str,
        perPage: int = 30,
        after: str | None = None,
        state: str | None = None,
        fields: list[str] | None = None,
    ) -> dict:
        received_cursors.append(after)
        number = 41 if after is None else 42
        return {
            "issues": [
                {
                    "number": number,
                    "title": f"Issue {number}",
                    "body": "Issue details",
                    "state": "OPEN",
                    "labels": ["bug"],
                    "created_at": "2026-09-01T12:00:00Z",
                    "updated_at": "2026-09-02T12:00:00Z",
                }
            ],
            "pageInfo": {
                "hasNextPage": after is None,
                "endCursor": "cursor-1" if after is None else "cursor-2",
            },
        }

    client = GitHubMCPClient(
        configured_settings(),
        client_factory=lambda: Client(server),
    )

    issues = await client.list_issues("octo/project", state="open", limit=2)

    assert [issue.number for issue in issues] == [41, 42]
    assert [str(issue.url) for issue in issues] == [
        "https://github.com/octo/project/issues/41",
        "https://github.com/octo/project/issues/42",
    ]
    assert received_cursors == [None, "cursor-1"]


@pytest.mark.anyio
async def test_list_pull_requests_normalizes_merged_state_and_source_url():
    server = MCPServer("GitHub test")

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    def list_pull_requests(
        owner: str,
        repo: str,
        page: int = 1,
        perPage: int = 30,
        fields: list[str] | None = None,
    ) -> list[dict]:
        return [
            {
                "number": 17,
                "title": "Improve search",
                "body": "Faster lookup",
                "state": "closed",
                "draft": False,
                "merged": True,
                "html_url": "https://github.com/octo/project/pull/17",
                "labels": ["performance"],
                "created_at": "2026-09-01T12:00:00Z",
                "updated_at": "2026-09-02T12:00:00Z",
            }
        ]

    client = GitHubMCPClient(
        configured_settings(),
        client_factory=lambda: Client(server),
    )

    pull_requests = await client.list_pull_requests("octo/project", limit=5)

    assert pull_requests[0].state == "merged"
    assert str(pull_requests[0].url) == "https://github.com/octo/project/pull/17"


@pytest.mark.anyio
async def test_list_commits_returns_commit_messages_dates_and_source_links():
    server = MCPServer("GitHub test")

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    def list_commits(
        owner: str,
        repo: str,
        page: int = 1,
        perPage: int = 30,
        fields: list[str] | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict]:
        return [
            {
                "sha": "abc123",
                "html_url": "https://github.com/octo/project/commit/abc123",
                "commit": {
                    "message": "Improve search performance",
                    "author": {
                        "name": "Octo User",
                        "date": "2026-09-03T10:00:00Z",
                    },
                },
            }
        ]

    client = GitHubMCPClient(
        configured_settings(),
        client_factory=lambda: Client(server),
    )

    commits = await client.list_commits("octo/project", limit=5)

    assert commits[0].sha == "abc123"
    assert commits[0].message == "Improve search performance"
    assert commits[0].author == "Octo User"
    assert str(commits[0].url) == "https://github.com/octo/project/commit/abc123"


@pytest.mark.anyio
async def test_retrieval_rejects_a_tool_not_marked_read_only():
    class WriteToolClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

        async def list_tools(self, cursor=None):
            tool = SimpleNamespace(
                name="list_pull_requests",
                annotations=SimpleNamespace(read_only_hint=False),
            )
            return SimpleNamespace(tools=[tool], next_cursor=None)

    client = GitHubMCPClient(
        configured_settings(),
        client_factory=lambda: cast(Client, WriteToolClient()),
    )

    with pytest.raises(GitHubMCPError, match="not marked read-only"):
        await client.list_pull_requests("octo/project")