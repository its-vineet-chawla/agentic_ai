# Agentic AI: What This Project Does

---

## Slide 1: Title

Agentic AI

Turning GitHub Repository Health into Executive Insight

---

## Slide 2: What This Project Is

This project is an AI-assisted engineering operations tool.

It helps teams answer one core question:
- What is happening in our GitHub repositories right now?

It gathers repository signals from:
- open issues
- open pull requests
- repository metadata
- project context

Then it turns that activity into a structured summary for technical and leadership review.

---

## Slide 3: The Business Problem

Engineering teams generate a large volume of GitHub activity every day.

Typical challenges:
- too many issues and pull requests to review manually
- fragmented status updates across repositories
- inconsistent communication to leadership
- slow decisions caused by missing repo context

Teams need a faster, more reliable way to understand repo health.

---

## Slide 4: What the Project Does

The project accepts a repository in the format:
- owner/repository

It then:
- validates the repo against an allowlist
- reads only approved GitHub metadata via MCP
- fetches open issues and pull requests
- converts the evidence into a structured JSON payload
- sends the payload to a model for summarization

The result is a clearer, more actionable view of repository health.

---

## Slide 5: Core Workflow

1. Load configuration and environment settings
2. Connect to GitHub using a read-only MCP interface
3. Validate the repository against approved access rules
4. Pull metadata, open issues, and open pull requests
5. Gather evidence with source references
6. Send the evidence to a model for analysis
7. Return a structured response with findings and source links

---

## Slide 6: Output Format

The system produces structured outputs such as:
- summary
- findings
- sources
- summary_sources
- finding_sources

This is important because it is not just chat output.

It is evidence-backed reporting that can be reviewed, traced, and used for decision-making.

---

## Slide 7: Why It Is Different

This is not a generic AI chatbot.

It is built as a grounded operational agent with safety controls.

Key characteristics:
- allowlist-based repository access
- read-only GitHub tools
- source-backed evidence before model output
- structured reporting instead of free-form summaries
- auditability through stored context and memory

This makes it much more suitable for engineering operations and leadership reporting.

---

## Slide 8: Architecture Overview

Main components:
- app.py — CLI entry point
- config.py — configuration and validation logic
- github_mcp.py — read-only GitHub access layer
- workflows.py — orchestration for status and drafting flows
- google_model.py — model analysis and summarization
- models.py — structured schemas for outputs
- persistence.py — audit and memory tracking
- wiki_publishing.py — approval-gated publishing workflow

The design keeps data retrieval, validation, and model reasoning clearly separated.

---

## Slide 9: Business Value

This project helps teams:
- triage repository health faster
- identify issue and PR risk earlier
- reduce manual status gathering
- create more consistent engineering updates
- improve leadership visibility into real project signals

Result:
- less manual reporting
- faster awareness of repo status
- better prioritization of engineering work

---

## Slide 10: Closing Message

Agentic AI is a practical example of using AI for engineering operations.

It takes noisy GitHub activity and turns it into:
- actionable insights
- grounded summaries
- evidence-based reporting
- better decision support for teams and leaders

In short, this project helps organizations understand repository health faster, more clearly, and with safer AI controls.

---

End of deck
