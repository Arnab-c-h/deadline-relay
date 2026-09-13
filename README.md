# Deadline Relay

Preview and approve a release-date change across Notion, a GitHub milestone, and Google Calendar. The local app includes deterministic scheduling, exact before/after review, a durable SQLite execution journal, and read-back verification.

**Current target:** a fully connected Vercel application. Normal startup requires real connections and blocks planning when setup is missing. OpenAI interpretation is implemented and live-tested; dedicated test records exist in all three apps. Server credentials, hosted persistence, durable execution, authentication and hosted OAuth remain in progress. See [the revised deployment requirements](docs/PRODUCTION-TARGET.md).

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

## Connect before planning

Follow [runtime setup](docs/SETUP.md). The app currently shows connection setup requirements; it does not substitute fictional records or simulated model responses. The previous fixture workflow is available only to isolated automated tests. Final acceptance will use uniquely named test records inside the actual apps through the deployed UI.

## Validate

```powershell
.\scripts\test.ps1
```

See [evaluation evidence](docs/EVALUATION.md), [runtime setup](docs/SETUP.md), [reliability brief](docs/RELIABILITY.md), [API contract](docs/CONTRACT.md), and [original PRD](docs/PRD.md). The PRD is the approved design baseline; the evaluation report describes actual implementation coverage and remaining work.

## Architecture and limits

React → FastAPI → deterministic planner → version/hash approval → SQLite executor → provider adapters → read-back verification. Models will interpret a request only; they will not select writable resources or execute changes.

The scheduler currently supports one configured project in Asia/Kolkata, Monday–Friday, a 30-working-day horizon, supplied task estimates, and one movable non-recurring meeting. It does not model holidays, task resource capacity, multiple attendee calendars, recurring-event edits, or distributed execution yet. The current local SQLite/background-task implementation must be migrated before Vercel deployment. Notion/GitHub writes are not an atomic transaction; the journal exposes partial results. Local files containing credentials, state, build outputs, or browser captures are ignored by Git.
