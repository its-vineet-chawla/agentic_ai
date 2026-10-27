# Agentic AI Leadership Brief

---

## Slide 1: Executive Summary

Project: Agentic AI

Objective:
- Turn GitHub repository health into an AI-assisted executive summary
- Detect open issues, pull requests, and repo context in a controlled way
- Produce actionable insights without exposing broad repository access

Why it matters:
- Faster repo triage for engineering leaders
- Better prioritization of engineering work
- Structured evidence-backed reporting for technical review

---

## Slide 2: Business Problem We Are Solving

Engineering teams struggle to keep up with:
- Open issues and pull requests across repositories
- Repeated context gathering before decisions
- Inconsistent repo status communication to leadership
- Manual synthesis of noisy GitHub activity

Current pain:
- Leaders often receive fragmented updates
- Teams waste time compiling status manually
- Actions are delayed because context is not consolidated

Solution:
- Build an agent that reads allowlisted GitHub data, summarizes it, and explains the biggest signals

---

## Slide 3: What the Solution Does

Core workflow:
- Accept repository in `owner/repository` format
- Validate the repo against an allowlist
- Read only approved GitHub metadata via MCP
- Fetch open issues and open pull requests
- Package evidence in a structured JSON payload
- Send evidence to a Google model for summarization
- Return a structured result with source references

User experience:
- Command-line interface: `python -m agentic_ai status owner/repository`
- Output is JSON, including summary, findings, and source links

---

## Slide 4: Architecture Overview

Main building blocks:
- `app.py` — CLI entry point
- `config.py` — settings, env configuration, allowlist validation
- `github_mcp.py` — read-only GitHub access layer via MCP
- `workflows.py` — LangGraph orchestration for status and drafting flows
- `google_model.py` — model interactions for analysis and documentation
- `models.py` — Pydantic schemas for structured outputs
- `persistence.py` — audit and memory storage
- `wiki_publishing.py` — approval-gated publishing workflow

System design principle:
- Keep read/write concerns separated
- Use structured evidence + source tracking before model response generation

---

## Slide 5: Key Workflow: Repository Status Analysis

1. Settings are loaded from `.env` / environment
2. GitHub MCP is initialized with endpoint and token
3. Repository is validated against `GITHUB_ALLOWED_REPOSITORIES`
4. Repo metadata, open issues, and open PRs are fetched concurrently
5. Data is converted into evidence with source references
6. Google model analyzes the evidence and returns:
   - summary
   - findings
   - source-backed citations

Output format includes:
- `summary`
- `findings`
- `sources`
- `summary_sources`
- `finding_sources`

---

## Slide 6: Why This Is Different

This project is not a generic chatbot. It is a grounded operational agent with explicit safety controls.

Key characteristics:
- Allowlist-based repository access
- Read-only GitHub tool enforcement
- Source validation before model output is accepted
- Structured evidence rather than free-form model summarization
- Auditability through persistence and memory stores

This makes it more suitable for leadership reporting and engineering operations than an uncontrolled AI assistant.

---

## Slide 7: Additional Capabilities

Beyond status summaries, the project includes:
- documentation drafting workflows
- wiki proposal generation
- approval-gated publishing
- persistence of audit records and scoped memories
- offline evaluation framework for grounding and citation checks

This means the platform is designed not only for reporting but also for operational governance and traceability.

---

## Slide 8: Risks, Constraints, and Maturity

Current realities:
- Status CLI is the main working path; this is the strongest validated flow
- Wiki publishing is intentionally gated and conservative
- Some capabilities are programmatic rather than fully user-facing
- Model output depends on the quality and completeness of GitHub evidence

Key risk areas:
- over-trusting model-generated summaries without evidence validation
- repository access control must remain strict
- token and MCP endpoint configuration are operationally sensitive

---

## Slide 9: Recommended Next Steps

Priority actions for the next 60–90 days:
- Harden the CLI experience for non-technical users
- Add richer dashboards and filtering for trends across repos
- Expand metrics for issue/PR health, congestion, and delivery risk
- Add repository-level reporting for leadership reviews
- Improve production observability and fail-safe warnings
- Validate operational workflows with real repos and real stakeholders

Outcome:
- Move from a promising engineering prototype to a trusted leadership-facing operational agent

---

## Slide 10: Closing Message

This project demonstrates a practical AI architecture for operations: grounded data, controlled access, workflow orchestration, and evidence-driven summarization.

The value is clear:
- less manual status compilation
- faster awareness of repo health
- better executive visibility
- safer AI use in engineering operations

This is not just a demo—it is a foundation for a leadership-grade engineering insight layer.
