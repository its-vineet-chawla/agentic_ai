from agentic_ai.models import AnalysisResult, SourceReference
from agentic_ai.app import main


def test_main_shows_help_when_no_command_is_given(capsys):
    main([])

    output = capsys.readouterr().out
    assert "usage: agentic-ai" in output
    assert "status" in output


def test_status_command_outputs_source_linked_workflow_result(monkeypatch, capsys):
    source = SourceReference(
        kind="repository",
        identifier="octo/project",
        title="octo/project",
        url="https://github.com/octo/project",
    )

    class FakeWorkflow:
        def __init__(self, github_client, model_client):
            pass

        async def run(self, repository):
            assert repository == "octo/project"
            return AnalysisResult(
                summary="No open work items.",
                sources=[source],
                summary_sources=[source],
            )

    monkeypatch.setattr("agentic_ai.app.Settings", lambda: object())
    monkeypatch.setattr("agentic_ai.app.configure_logging", lambda settings: None)
    monkeypatch.setattr("agentic_ai.app.GitHubMCPClient", lambda settings: object())
    monkeypatch.setattr("agentic_ai.app.GoogleModelClient", lambda settings: object())
    monkeypatch.setattr("agentic_ai.app.RepositoryStatusWorkflow", FakeWorkflow)

    main(["status", "octo/project"])

    output = capsys.readouterr().out
    assert "No open work items." in output
    assert "https://github.com/octo/project" in output