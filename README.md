# Deadline Relay

Preview and approve a release-date change across Notion, a GitHub milestone, and Google Calendar. The local app includes deterministic scheduling, exact before/after review, a durable SQLite execution journal, and read-back verification.

**Current state:** working local simulator; direct provider adapters tested with mocked HTTP. Live model integration, real three-app verification, and the submission recording are pending user setup. Simulated interpretation uses a conservative date parser and does not call an LLM.

## Run locally

Prerequisites: `uv` and Node.js/npm. Python 3.13+ is declared; this build was verified with uv-managed Python 3.14.3 and Node 24.14.1.

```powershell
cd F:\Projects\MultiAgentHack\deadline-relay
uv sync --locked
Push-Location frontend
npm.cmd ci
npm.cmd run build
Pop-Location
uv run uvicorn relay.main:app --host 127.0.0.1 --port 8000
```

Open [Deadline Relay](http://127.0.0.1:8000). Use one server process and one worker. `scripts/start.ps1` performs these setup/build/start steps and stops if a command fails.

## Try the workflow

1. Analyze the prefilled request for **September 18, 2026**. It is infeasible; no write is permitted.
2. Select **Plan for September 24** and review five exact operations: move M2, T4, T5, the GitHub milestone deadline, and the Notion release date/plan marker.
3. Approve the displayed version and hash. The run becomes **Verified** only after read-back and final preservation/constraint checks.
4. Reloading preserves the SQLite journal. Interrupted runs appear for review; resuming reconciles uncertain writes before retrying. Exhausted retries require review and approval of a new recovery plan.

For a new simulated demonstration, with no unfinished run:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/demo/reset -ContentType 'application/json' -Body '{"confirm":true}'
```

Reset preserves run evidence and creates a new fixture generation, making old unexecuted plans stale. It never resets live resources.

## Validate

```powershell
.\scripts\test.ps1
```

See [evaluation evidence](docs/EVALUATION.md), [runtime setup](docs/SETUP.md), [reliability brief](docs/RELIABILITY.md), [API contract](docs/CONTRACT.md), and [original PRD](docs/PRD.md). The PRD is the approved design baseline; the evaluation report describes actual implementation coverage and remaining work.

## Architecture and limits

React → FastAPI → deterministic planner → version/hash approval → SQLite executor → provider adapters → read-back verification. Models will interpret a request only; they will not select writable resources or execute changes.

This is one configured fictional project in Asia/Kolkata, Monday–Friday, a 30-working-day horizon, supplied task estimates, and one movable non-recurring meeting. It does not model holidays, task resource capacity, multiple attendee calendars, recurring-event edits, or distributed execution. Notion/GitHub writes are not an atomic transaction; the journal exposes partial results. Local files containing credentials, state, build outputs, or browser captures are ignored by Git.
