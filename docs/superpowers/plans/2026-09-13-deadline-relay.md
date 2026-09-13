# Deadline Relay Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development task-by-task. Track progress with checkboxes. Review spec compliance and quality before live setup.

**Goal:** Implement the PRD's local deadline workflow and pause for credentials before live verification.
**Architecture:** React calls FastAPI; deterministic planner and SQLite executor use narrow provider adapters. Simulated mode is explicit and persisted; live mode fails closed when configuration is missing.
**Tech Stack:** Python 3.13+ (verified on 3.14.3), FastAPI, SQLite, React/TypeScript/Vite.
**Spec:** `F:/Projects/MultiAgentHack/PRD.md`; shared exact interfaces in `docs/CONTRACT.md`.

## Global constraints

- One project, Asia/Kolkata, 30 working days, one movable non-recurring meeting.
- Approval version/hash, stale-state rejection, no writes before approval, no blind retries.
- No external resource creation or live writes during initial implementation.
- One worker, explicit simulated/live modes. No model key means clearly labeled simulated interpretation; never pretend a model ran.
- Feature branch in fresh isolated project directory; preserve sibling video-polish.

## Task 1: Deterministic fixture and scheduling

Files: relay/fixtures.py, relay/scheduler.py, tests/test_scheduler.py. Produces build_fixture() and propose(snapshot, requested_date) per CONTRACT.
- [x] Write failing behavior tests for Sep18 infeasibility, Sep24 five changes, fixed meeting busy conflict, missing estimate, cycle, weekend/timezone, preservation.
- [x] Run `uv run pytest tests/test_scheduler.py -q`; observe missing feature failure.
- [x] Implement candidate domain generation, earliest/topological and reverse preservation schedule, exact normalized patches.
- [x] Run tests; inspect literal expected dates independently of planner helpers.

## Task 2: React interface

Files: frontend/* only. Consumes CONTRACT HTTP JSON; produces four UI states and accessible actions.
- [x] Define typed API and request/alternative/approval/run lifecycle; write behavior tests for no automatic approval and polling/resume UI with mocked HTTP boundary.
- [x] Run frontend tests to observe missing behavior.
- [x] Implement minimal light editorial interface, before/after table, small dependency chain, explicit simulation labels, source/evidence and operation statuses.
- [x] Run tests and `npm.cmd run build`; real browser check after backend integration.

## Task 3: Live direct provider adapters

Files: relay/providers/base.py, relay/providers/live.py, config.example.json, scripts/google_auth.py, tests/test_providers.py. Consumes normalized CONTRACT records; implements snapshot/read/write/health.
- [x] Write HTTP-boundary tests for field allowlists, Calendar If-Match/412, Notion data-source/version/property handling, GitHub due_on.
- [x] Observe tests fail; implement strict mapping and pagination, owned-calendar OAuth refresh, canonical timestamp handling.
- [x] Verify no network calls for missing config and no unauthorized write bodies.
- [x] Document exact missing credential/resource setup; do not create external resources.

## Task 4: Durable workflow and HTTP service

Files: relay/store.py, relay/simulation.py, relay/service.py, relay/main.py, relay/intent.py, tests/test_workflow.py, tests/test_api.py. Consumes Tasks1/3 interfaces; produces HTTP contract for Task2.
- [x] Write tests demonstrating approval prevents writes, tamper rejection, duplicate idempotency, stale approval, partial failure, applied timeout, mismatch, restart reconciliation, preserved unrelated records.
- [x] Run failing tests before implementations. Use real SQLite and stateful simulated provider; inject provider faults only at tests' transport boundary.
- [x] Implement SQLite records, atomic approval/one-run guard, serialized workflow, intent/date parsing labeled simulated, fail-closed live model dependency.
- [x] Run `uv run pytest -q` and API smoke checks against actual fixture.

## Task 5: Integration verification and handoff

Files: README.md, docs/EVALUATION.md, docs/SETUP.md, scripts/start.ps1, scripts/test.ps1.
- [x] Run full backend/frontend suites and production build; visually verify request→conflict→alternative→approval→verified.
- [x] Independent code review concentrating on approval, source mutation, timeouts, and frontend repeated actions; fix load-bearing findings and rerun relevant checks.
- [x] Record actual test evidence and explicitly unverified live/model checks.
- [x] Pause for user runtime credentials/resources and provider/model choice. Do not claim hackathon-complete until live three-app verification and recording exist.

## Handoff checkpoint

Local implementation and checks are complete. See docs/EVALUATION.md for actual evidence. Live model adapter, credentials/resources, real three-app acceptance, clean-checkout peer check, and demo recording remain pending. No live writes or remote pushes were performed.
