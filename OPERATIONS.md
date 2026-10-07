# Operations

## Local Setup

Use the project virtual environment and install the declared dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set only the credentials and repository scope needed for the feature being exercised. `.env` is ignored by Git. Never put API keys or PATs in command arguments, test fixtures, audit metadata, or logs.

## Routine Checks

Run the unit, workflow, persistence, and deterministic quality checks:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m agentic_ai.evaluations
.\.venv\Scripts\python.exe -m pip check
```

The versioned offline dataset is `tests/fixtures/grounded_analysis_v1.json`. Its provisional release gates require 100% citation coverage, 100% source precision and per-claim citation alignment, at least 80% required-term coverage, exact required tool selection, no write tools, and no prompt-injection sentinel leakage. These thresholds are development baselines, not approved production quality thresholds. A maintainer must ratify them before release. The offline evaluator does not call Google or GitHub and does not replace live-service verification.

## External Services

Before a live status run, configure `GOOGLE_API_KEY`, `GITHUB_MCP_URL`, `GITHUB_MCP_TOKEN`, and `GITHUB_ALLOWED_REPOSITORIES` in `.env`. Verify GitHub access with `GitHubMCPClient.verify_connection()` and verify the Google key/model with a controlled test that uses non-sensitive sample evidence. Provider errors are surfaced as failed operations; they must not be reported as successful analyses.

Run the local status workflow with:

```powershell
.\.venv\Scripts\python.exe -m agentic_ai status owner/repository
```

## Database

Set `DATABASE_URL` to a PostgreSQL async URL, then apply migrations:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe heads
```

`MEMORY_RETENTION_DAYS` defaults to 90 days for development. Approve a production retention period, backup/restore process, and access policy before deploying. Schedule `MemoryAuditStore.purge_expired_memories()` as a controlled maintenance job. Back up PostgreSQL before schema changes; downgrading the initial migrations drops the memory, audit, and wiki-attempt tables.

## Wiki Publishing Status

The official GitHub MCP server does not document Wiki page tools. `UnavailableWikiAdapter` therefore remains the default/fail-closed behavior. Do not enable writes until a separate adapter is selected and verifies page read, create/update capability, atomic version checks, reviewer identity, and idempotency. If a write result is uncertain, inspect the persisted attempt and the remote page before taking any manual recovery action; do not retry automatically.

## Recovery

- GitHub authentication or permission error: verify the PAT scopes and repository allowlist; do not broaden the allowlist as a diagnostic shortcut.
- Google quota/model error: verify AI Studio access, model availability, and quota; the CLI should return a failure rather than a partial success.
- Database unavailable: stop memory and audit writes, preserve fresh GitHub reads as non-persistent, restore connectivity, then inspect migrations with `alembic current` and `alembic heads`.
- Wiki page conflict: keep the proposal, re-read the page, regenerate/review the change, and obtain a new approval bound to the new proposal digest and page version.
- Uncertain wiki write: use the idempotency key and remote page version to reconcile; never repeat the same write blindly.
