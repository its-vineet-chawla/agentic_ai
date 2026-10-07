import asyncio
import json
import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agentic_ai.github_mcp import GitHubMCPClient
from agentic_ai.google_model import GoogleModelClient
from agentic_ai.models import (
    AnalysisResult,
    DocumentationDraftRequest,
    GeneratedDocumentContent,
    ProposedWikiChange,
    SourceReference,
)


class RepositoryStatusError(RuntimeError):
    pass


class DocumentationDraftError(RuntimeError):
    pass


class _StatusState(TypedDict, total=False):
    repository: str
    limit: int
    evidence: str
    sources: list[SourceReference]
    result: AnalysisResult


class _DraftState(TypedDict, total=False):
    request: DocumentationDraftRequest
    document: GeneratedDocumentContent
    proposal: ProposedWikiChange


class RepositoryStatusWorkflow:
    def __init__(
        self,
        github_client: GitHubMCPClient,
        model_client: GoogleModelClient,
        item_limit: int = 30,
    ) -> None:
        self._validate_limit(item_limit)
        self._github_client = github_client
        self._model_client = model_client
        self._item_limit = item_limit
        graph = StateGraph(_StatusState)
        graph.add_node("retrieve_open_status", self._retrieve_status)
        graph.add_node("analyze_status", self._analyze_status)
        graph.add_edge(START, "retrieve_open_status")
        graph.add_edge("retrieve_open_status", "analyze_status")
        graph.add_edge("analyze_status", END)
        self._graph = graph.compile()

    async def run(
        self,
        repository: str,
        item_limit: int | None = None,
    ) -> AnalysisResult:
        limit = self._item_limit if item_limit is None else item_limit
        self._validate_limit(limit)
        state = await self._graph.ainvoke({"repository": repository, "limit": limit})
        return state["result"]

    async def _retrieve_status(self, state: _StatusState) -> dict[str, Any]:
        repository_name = state["repository"]
        limit = state["limit"]
        try:
            repository, issues, pull_requests = await asyncio.gather(
                self._github_client.get_repository(repository_name),
                self._github_client.list_issues(
                    repository_name,
                    state="open",
                    limit=limit,
                ),
                self._github_client.list_pull_requests(
                    repository_name,
                    state="open",
                    limit=limit,
                ),
            )
        except Exception as error:
            raise RepositoryStatusError(
                "GitHub retrieval failed; no status summary was generated."
            ) from error

        sources = [
            SourceReference(
                kind="repository",
                identifier=repository.full_name,
                title=repository.full_name,
                url=repository.url,
            )
        ]
        sources.extend(
            SourceReference(
                kind="issue",
                identifier=str(issue.number),
                title=issue.title,
                url=issue.url,
            )
            for issue in issues
        )
        sources.extend(
            SourceReference(
                kind="pull_request",
                identifier=str(pull_request.number),
                title=pull_request.title,
                url=pull_request.url,
            )
            for pull_request in pull_requests
        )

        evidence = json.dumps(
            {
                "repository": repository.model_dump(mode="json"),
                "open_issues": [issue.model_dump(mode="json") for issue in issues],
                "open_pull_requests": [
                    pull_request.model_dump(mode="json")
                    for pull_request in pull_requests
                ],
            },
            ensure_ascii=True,
        )
        return {"evidence": evidence, "sources": sources}

    async def _analyze_status(self, state: _StatusState) -> dict[str, AnalysisResult]:
        try:
            analysis = await self._model_client.analyze(
                state["evidence"],
                state["sources"],
            )
        except Exception as error:
            raise RepositoryStatusError(
                "Google analysis failed; no status summary was generated."
            ) from error
        return {"result": analysis.model_copy(update={"sources": state["sources"]})}

    @staticmethod
    def _validate_limit(item_limit: int) -> None:
        if item_limit < 1:
            raise ValueError("item_limit must be at least 1")


class DocumentationDraftWorkflow:
    def __init__(self, model_client: GoogleModelClient) -> None:
        self._model_client = model_client
        graph = StateGraph(_DraftState)
        graph.add_node("generate_document_draft", self._generate_draft)
        graph.add_node("attach_verified_source_links", self._attach_source_links)
        graph.add_edge(START, "generate_document_draft")
        graph.add_edge("generate_document_draft", "attach_verified_source_links")
        graph.add_edge("attach_verified_source_links", END)
        self._graph = graph.compile()

    async def run(
        self,
        *,
        document_type: str,
        operation: str,
        repository: str,
        target_page: str,
        evidence: str,
        sources: list[SourceReference],
        scope_description: str | None = None,
    ) -> ProposedWikiChange:
        request = DocumentationDraftRequest(
            document_type=document_type,
            operation=operation,
            repository=repository,
            target_page=target_page,
            evidence=evidence,
            sources=sources,
            scope_description=scope_description,
        )
        state = await self._graph.ainvoke({"request": request})
        return state["proposal"]

    async def _generate_draft(self, state: _DraftState) -> dict[str, GeneratedDocumentContent]:
        request = state["request"]
        try:
            document = await self._model_client.generate_document(
                document_type=request.document_type,
                evidence=request.evidence,
                sources=request.sources,
                scope_description=request.scope_description,
            )
        except Exception as error:
            raise DocumentationDraftError(
                "Document drafting failed; no wiki change was created."
            ) from error
        return {"document": document}

    @staticmethod
    def _attach_source_links(state: _DraftState) -> dict[str, ProposedWikiChange]:
        request = state["request"]
        document = state["document"]
        source_by_id = {
            f"{source.kind}:{source.identifier}": source for source in request.sources
        }
        try:
            sources = [source_by_id[source_id] for source_id in document.source_ids]
        except KeyError as error:
            raise DocumentationDraftError(
                "Document draft cited a source outside the supplied evidence."
            ) from error

        unique_sources: list[SourceReference] = []
        for source in sources:
            if source not in unique_sources:
                unique_sources.append(source)
        citations = "\n".join(
            f"- [{DocumentationDraftWorkflow._escape_markdown_label(source.title)}]"
            f"(<{source.url}>)"
            for source in unique_sources
        )
        content = f"{document.markdown.rstrip()}\n\n## Sources\n{citations}"
        return {
            "proposal": ProposedWikiChange(
                operation=request.operation,
                repository=request.repository,
                target_page=request.target_page,
                content=content,
                sources=unique_sources,
            )
        }

    @staticmethod
    def _escape_markdown_label(title: str) -> str:
        safe_title = re.sub(r"[\r\n]+", " ", title)
        return safe_title.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")