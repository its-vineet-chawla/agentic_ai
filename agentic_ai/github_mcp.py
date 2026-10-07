from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any, AsyncIterator, Callable, Literal

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent, Tool
from pydantic import ValidationError

from agentic_ai.config import Settings
from agentic_ai.models import (
    GitHubCommit,
    GitHubIssue,
    GitHubPullRequest,
    GitHubRepository,
)


class GitHubMCPError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitHubMCPStatus:
    server_name: str | None
    read_only_tools: tuple[str, ...]


DEFAULT_GITHUB_WEB_URL = "https://github.com"
MAX_PAGE_SIZE = 100


class GitHubMCPClient:
    def __init__(
        self,
        settings: Settings,
        client_factory: Callable[[], AbstractAsyncContextManager[Client]] | None = None,
    ) -> None:
        self._settings = settings
        self._allowed_repositories = settings.github_allowed_repositories
        self._client_factory = client_factory or self._remote_client

    def validate_repository(self, repository: str) -> str:
        normalized_repository = repository.strip().casefold()
        if normalized_repository not in self._allowed_repositories:
            raise GitHubMCPError("Repository is not in the configured GitHub allowlist.")
        return normalized_repository

    async def get_repository(self, repository: str) -> GitHubRepository:
        owner, repo = self._split_repository(repository)
        async with self._client_factory() as client:
            payload = await self._call_read_tool(
                client,
                "search_repositories",
                {"query": f"{owner}/{repo}", "minimal_output": False},
            )

        repositories = self._result_items(payload, "items")
        matching_repository = next(
            (
                item
                for item in repositories
                if str(item.get("full_name", "")).casefold() == f"{owner}/{repo}"
            ),
            None,
        )
        if matching_repository is None:
            raise GitHubMCPError("The allowlisted GitHub repository was not found.")

        try:
            return GitHubRepository(
                full_name=matching_repository["full_name"],
                description=matching_repository.get("description"),
                url=matching_repository["html_url"],
                default_branch=matching_repository["default_branch"],
            )
        except (KeyError, ValidationError) as error:
            raise GitHubMCPError("GitHub returned incomplete repository metadata.") from error

    async def list_issues(
        self,
        repository: str,
        state: Literal["open", "closed"] | None = None,
        limit: int = 100,
    ) -> list[GitHubIssue]:
        owner, repo = self._split_repository(repository)
        self._validate_limit(limit)
        page_size = min(limit, MAX_PAGE_SIZE)
        issues: list[GitHubIssue] = []
        after: str | None = None
        seen_cursors: set[str] = set()
        web_base_url = self._github_web_base_url()

        async with self._client_factory() as client:
            await self._require_read_only_tool(client, "list_issues")
            while len(issues) < limit:
                arguments: dict[str, Any] = {
                    "owner": owner,
                    "repo": repo,
                    "perPage": min(page_size, limit - len(issues)),
                    "fields": [
                        "number",
                        "title",
                        "body",
                        "state",
                        "labels",
                        "created_at",
                        "updated_at",
                    ],
                }
                if state is not None:
                    arguments["state"] = state.upper()
                if after is not None:
                    arguments["after"] = after
                payload = await self._call_tool(client, "list_issues", arguments)
                items = self._result_items(payload, "issues")
                for item in items:
                    if len(issues) >= limit:
                        break
                    try:
                        number = int(item["number"])
                        issues.append(
                            GitHubIssue(
                                repository=f"{owner}/{repo}",
                                number=number,
                                title=item["title"],
                                body=item.get("body"),
                                url=item.get(
                                    "html_url",
                                    f"{web_base_url}/{owner}/{repo}/issues/{number}",
                                ),
                                labels=self._string_list(item.get("labels")),
                                created_at=item["created_at"],
                                updated_at=item["updated_at"],
                                state=str(item["state"]).lower(),
                            )
                        )
                    except (KeyError, TypeError, ValueError, ValidationError) as error:
                        raise GitHubMCPError("GitHub returned incomplete issue data.") from error

                page_info = payload.get("pageInfo", {})
                if not page_info.get("hasNextPage"):
                    return issues
                next_cursor = page_info.get("endCursor")
                if not isinstance(next_cursor, str) or not next_cursor:
                    raise GitHubMCPError("GitHub issue pagination returned no next cursor.")
                if next_cursor in seen_cursors:
                    raise GitHubMCPError("GitHub issue pagination returned a repeated cursor.")
                seen_cursors.add(next_cursor)
                after = next_cursor

        return issues

    async def list_pull_requests(
        self,
        repository: str,
        state: Literal["open", "closed"] | None = None,
        limit: int = 100,
    ) -> list[GitHubPullRequest]:
        owner, repo = self._split_repository(repository)
        self._validate_limit(limit)
        page_size = min(limit, MAX_PAGE_SIZE)
        pull_requests: list[GitHubPullRequest] = []
        page_number = 1

        async with self._client_factory() as client:
            await self._require_read_only_tool(client, "list_pull_requests")
            while len(pull_requests) < limit:
                arguments: dict[str, Any] = {
                    "owner": owner,
                    "repo": repo,
                    "page": page_number,
                    "perPage": min(page_size, limit - len(pull_requests)),
                    "fields": [
                        "number",
                        "title",
                        "body",
                        "state",
                        "draft",
                        "merged",
                        "html_url",
                        "labels",
                        "created_at",
                        "updated_at",
                    ],
                }
                if state is not None:
                    arguments["state"] = state
                payload = await self._call_tool(client, "list_pull_requests", arguments)
                items = self._result_items(payload)
                for item in items:
                    if len(pull_requests) >= limit:
                        break
                    try:
                        pull_requests.append(
                            GitHubPullRequest(
                                repository=f"{owner}/{repo}",
                                number=int(item["number"]),
                                title=item["title"],
                                body=item.get("body"),
                                url=item["html_url"],
                                labels=self._string_list(item.get("labels")),
                                created_at=item["created_at"],
                                updated_at=item["updated_at"],
                                state=(
                                    "merged"
                                    if item.get("merged")
                                    else str(item["state"]).lower()
                                ),
                                is_draft=bool(item.get("draft", False)),
                            )
                        )
                    except (KeyError, TypeError, ValueError, ValidationError) as error:
                        raise GitHubMCPError(
                            "GitHub returned incomplete pull request data."
                        ) from error
                if len(items) < arguments["perPage"]:
                    return pull_requests
                page_number += 1

        return pull_requests

    async def list_commits(
        self,
        repository: str,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[GitHubCommit]:
        owner, repo = self._split_repository(repository)
        self._validate_limit(limit)
        page_size = min(limit, MAX_PAGE_SIZE)
        commits: list[GitHubCommit] = []
        page_number = 1

        async with self._client_factory() as client:
            await self._require_read_only_tool(client, "list_commits")
            while len(commits) < limit:
                arguments: dict[str, Any] = {
                    "owner": owner,
                    "repo": repo,
                    "page": page_number,
                    "perPage": min(page_size, limit - len(commits)),
                    "fields": ["sha", "html_url", "commit"],
                }
                if since is not None:
                    arguments["since"] = since.isoformat()
                if until is not None:
                    arguments["until"] = until.isoformat()
                payload = await self._call_tool(client, "list_commits", arguments)
                items = self._result_items(payload)
                for item in items:
                    if len(commits) >= limit:
                        break
                    commit_details = item.get("commit") or {}
                    author_details = commit_details.get("author") or {}
                    try:
                        commits.append(
                            GitHubCommit(
                                sha=item["sha"],
                                message=commit_details["message"],
                                url=item["html_url"],
                                author=author_details.get("name"),
                                committed_at=author_details.get("date"),
                            )
                        )
                    except (KeyError, TypeError, ValueError, ValidationError) as error:
                        raise GitHubMCPError("GitHub returned incomplete commit data.") from error
                if len(items) < arguments["perPage"]:
                    return commits
                page_number += 1

        return commits

    async def verify_connection(self) -> GitHubMCPStatus:
        if self._settings.github_mcp_url is None:
            raise GitHubMCPError("GITHUB_MCP_URL must be configured before connecting.")
        if self._settings.github_mcp_token is None:
            raise GitHubMCPError("GITHUB_MCP_TOKEN must be configured before connecting.")
        if not self._allowed_repositories:
            raise GitHubMCPError("At least one GitHub repository must be allowlisted.")

        try:
            async with self._client_factory() as client:
                tools = await self._list_all_tools(client)
                read_only_tools = tuple(
                    sorted(
                        tool.name
                        for tool in tools
                        if tool.annotations is not None
                        and tool.annotations.read_only_hint is True
                    )
                )
                if "get_me" not in read_only_tools:
                    raise GitHubMCPError(
                        "The GitHub MCP server does not expose the read-only get_me tool."
                    )

                try:
                    identity_result = await client.call_tool("get_me", {})
                except Exception as error:
                    raise GitHubMCPError(
                        "GitHub MCP authentication check failed."
                    ) from error
                if identity_result.is_error:
                    raise GitHubMCPError("GitHub MCP authentication check failed.")

                server_name = (
                    client.server_info.name if client.server_info is not None else None
                )
                return GitHubMCPStatus(
                    server_name=server_name,
                    read_only_tools=read_only_tools,
                )
        except GitHubMCPError:
            raise
        except Exception as error:
            raise GitHubMCPError(
                "GitHub MCP connection failed; verify the endpoint, token, and permissions."
            ) from error

    async def _list_all_tools(self, client: Client) -> list[Tool]:
        tools: list[Tool] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()

        while True:
            page = await client.list_tools(cursor=cursor)
            tools.extend(page.tools)
            if page.next_cursor is None:
                return tools
            if page.next_cursor in seen_cursors:
                raise GitHubMCPError("GitHub MCP returned a repeated tool-list cursor.")
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor

    async def _call_read_tool(
        self,
        client: Client,
        name: str,
        arguments: dict[str, Any],
    ) -> Any:
        await self._require_read_only_tool(client, name)
        return await self._call_tool(client, name, arguments)

    async def _require_read_only_tool(self, client: Client, name: str) -> None:
        tools = await self._list_all_tools(client)
        tool = next((item for item in tools if item.name == name), None)
        if tool is None:
            raise GitHubMCPError(f"GitHub MCP does not provide the required {name} tool.")
        if tool.annotations is None or tool.annotations.read_only_hint is not True:
            raise GitHubMCPError(f"GitHub MCP tool {name} is not marked read-only.")

    async def _call_tool(
        self,
        client: Client,
        name: str,
        arguments: dict[str, Any],
    ) -> Any:
        try:
            result = await client.call_tool(name, arguments)
        except Exception as error:
            raise GitHubMCPError(f"GitHub MCP {name} request failed.") from error
        if result.is_error:
            raise GitHubMCPError(f"GitHub MCP {name} request failed.")
        if result.structured_content is not None:
            return result.structured_content
        for content in result.content:
            if isinstance(content, TextContent):
                try:
                    return json.loads(content.text)
                except json.JSONDecodeError as error:
                    raise GitHubMCPError(
                        f"GitHub MCP {name} returned invalid JSON data."
                    ) from error
        raise GitHubMCPError(f"GitHub MCP {name} returned no readable data.")

    def _split_repository(self, repository: str) -> tuple[str, str]:
        normalized_repository = self.validate_repository(repository)
        owner, repo = normalized_repository.split("/", maxsplit=1)
        return owner, repo

    def _github_web_base_url(self) -> str:
        configured_url = self._settings.github_web_url
        return str(configured_url).rstrip("/") if configured_url else DEFAULT_GITHUB_WEB_URL

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")

    @staticmethod
    def _result_items(payload: Any, key: str | None = None) -> list[dict[str, Any]]:
        if isinstance(payload, dict) and "result" in payload:
            payload = payload["result"]
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            if key is None:
                items = payload.get("items", payload.get("pull_requests", payload.get("commits", [])))
            else:
                items = payload.get(key, [])
        else:
            raise GitHubMCPError("GitHub MCP returned an unexpected response shape.")
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise GitHubMCPError("GitHub MCP returned an unexpected item list.")
        return items

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise GitHubMCPError("GitHub returned an invalid label list.")
        return [item if isinstance(item, str) else item["name"] for item in value]

    @asynccontextmanager
    async def _remote_client(self) -> AsyncIterator[Client]:
        endpoint = self._settings.github_mcp_url
        token = self._settings.github_mcp_token
        if endpoint is None or token is None:
            raise GitHubMCPError("GitHub MCP endpoint and token are required.")

        headers = {
            "Authorization": f"Bearer {token.get_secret_value()}",
            "X-MCP-Toolsets": "context,repos,issues,pull_requests",
            "X-MCP-Readonly": "true",
        }
        timeout = httpx2.Timeout(30.0, read=300.0)
        async with httpx2.AsyncClient(headers=headers, timeout=timeout) as http_client:
            transport = streamable_http_client(str(endpoint), http_client=http_client)
            async with Client(transport) as client:
                yield client