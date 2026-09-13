# Connected deployment target

This document records the owner's September 13 scope correction and supersedes the local-demo delivery assumptions in the original PRD and implementation plan.

## Required result

Deadline Relay must run as a Vercel project with an authenticated owner, a real LLM, and working Notion, GitHub, and Google Calendar connections. Product requests, planning inputs, writes, verification, and failure messages must come from actual services. Missing access blocks the action and identifies the missing connection. No fixture-backed runtime, fake connected status, prefilled fictional project, or parser presented as a model is acceptable.

The owner explicitly authorized creating mock project data **inside the actual apps** for final acceptance testing. Test data is content; reads, model calls, approvals, writes, and read-back are real. Automated unit-test doubles may still isolate failure cases, but their results do not count as live end-to-end acceptance.

## Architecture revision

Retain the Python deterministic scheduler and narrow provider adapters, and the React approval interface. Host frontend assets and FastAPI endpoints on Vercel, with shared origin routing. Vercel documents FastAPI support and recommends queues/workflows for deferred or multi-step work. [Official FastAPI deployment guide](https://vercel.com/kb/guide/ship-a-fastapi-app-on-vercel)

Replace the local SQLite journal with hosted PostgreSQL for projects, snapshots, immutable plans, approvals, runs, operations, and audit events. Use database transactions, unique idempotency constraints, and project-level execution ownership shared across function instances. Application memory and local files must not be the durable source of truth.

Replace FastAPI BackgroundTasks and the in-memory execution lock with durable queued execution. Approval and an outbox event are committed in one transaction. The dispatcher and queue consumer tolerate duplicate delivery. A worker claims a bounded lease, persists operation intent, performs one bounded unit of work, rereads external state, and commits evidence. Reconciliation must precede retries after lost responses. Delays and retries are scheduled durably; no long sleeping request or browser tab is required for completion. Cold start must not mark another worker's valid lease interrupted. Deploy-version compatibility must preserve or deliberately migrate existing run contracts.

Use authenticated owner sessions and project authorization on every API read and write. Bind approval to the owner and exact plan hash/version. The first hosted release is a private single-owner workspace; public signup, billing, and broad SaaS tenancy are outside this change. Provider secrets stay server-side. Browser OAuth uses the deployed callback origin, state/PKCE where applicable, and encrypted persisted refresh tokens. The current Desktop OAuth token-file helper is a local diagnostic and must not serve as hosted connection management.

Implement the selected real model provider behind a strict structured interpretation interface. Record the actual model, request identifier, token usage where available, and latency. Model output supplies interpreted intent/date/clarification only; configured IDs and deterministic validation control execution. Calendar and task data are untrusted input. Do not invent estimates, resources, permission results, or successful writes.

Prefer this migration because it preserves the verified scheduling and recovery behavior. A full TypeScript rewrite would fit Vercel but would unnecessarily replace tested Python logic. A separate always-on backend remains a fallback only if a measured platform constraint requires it; it is not the current deployment target.

## Real acceptance run

1. Select the owner's Vercel account/project, repository, hosted database, model account, and dedicated provider destinations. No account or destination is inferred from an unrelated project.
2. Create a uniquely named `Deadline Relay E2E <run-id>` project using real Notion rows, real GitHub issues/milestone, and real owned-calendar events. Record every created resource ID in a manifest. Use dedicated destinations and no external attendees or notifications to other people.
3. Anchor the canonical dependency pattern to an agreed future working week. Preserve the impossible-date and earliest-feasible-date relationship without depending on September 2026 forever. Seed an unrelated task/event as preservation controls.
4. Drive the deployed UI: connect, read, request an infeasible date, inspect evidence, choose the feasible alternative, approve exact changes, and wait for verified results.
5. Independently reread all provider records and compare the exact approved fields and protected fields. Check source links, actual model usage, duplicate approval, stale-plan rejection, interruption/recovery, and token expiry handling.
6. Record the deployed URL, commit, fixture manifest, run/plan IDs, timings, actual request/error evidence and pass/fail results. Do not count mocked unit tests as successful live runs.
7. Retain test records for owner review. Any later cleanup uses only manifest-owned IDs; do not clear calendars, databases, or repositories.

## Current implementation checkpoint

- Normal local startup now requires live mode. Environment configuration cannot enable the fixture provider, and normal runtime has no simulator reset endpoint.
- Empty request field, missing project metadata, and blocked connection setup replace the fictional ready-to-use app state.
- Existing scheduling/recovery unit tests continue to use explicit isolated factory overrides.
- Hosted database, durable queue, owner authentication, hosted OAuth, real LLM, deployed packaging, and real acceptance remain implementation work. No deployment or provider data creation has happened yet.

Next owner input: LLM provider/model and access to the dedicated provider destinations. Hosted database and Vercel destination credentials will be requested when their setup becomes necessary. Keep secrets in local environment files or the deployment's server-side environment configuration.
