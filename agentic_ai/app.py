import argparse
import asyncio
import sys
from collections.abc import Sequence

from agentic_ai.config import Settings
from agentic_ai.github_mcp import GitHubMCPClient
from agentic_ai.google_model import GoogleModelClient
from agentic_ai.logging_config import configure_logging
from agentic_ai.workflows import RepositoryStatusError, RepositoryStatusWorkflow


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="agentic-ai")
    subparsers = parser.add_subparsers(dest="command")
    status_parser = subparsers.add_parser(
        "status",
        help="Summarize open issues and pull requests in an allowlisted repository",
    )
    status_parser.add_argument("repository", help="Repository in owner/name form")
    arguments = parser.parse_args(argv)

    if arguments.command is None:
        parser.print_help()
        return

    settings = Settings()
    configure_logging(settings)
    workflow = RepositoryStatusWorkflow(
        GitHubMCPClient(settings),
        GoogleModelClient(settings),
    )

    try:
        result = asyncio.run(workflow.run(arguments.repository))
    except RepositoryStatusError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(result.model_dump_json(indent=2))