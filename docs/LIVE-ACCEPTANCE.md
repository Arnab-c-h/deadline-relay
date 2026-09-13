# Live integration acceptance — September 14, 2026

Tested the local Deadline Relay application against the owner's actual Notion, GitHub, Google Calendar, and OpenAI accounts. The fictional records are real application content in dedicated test destinations. No provider or model responses were simulated in these acceptance runs.

## Destinations

- [Notion schedule](https://app.notion.com/p/3da38db2744b81399a87d24f91cafd1e): nine rows.
- [GitHub test repository](https://github.com/Arnab-c-h/deadline-relay-test): six issues and [milestone 1](https://github.com/Arnab-c-h/deadline-relay-test/milestone/1).
- [Google Calendar test calendar](https://calendar.google.com/calendar/u/0/r/settings/calendar/41104eb84b85bd3d2f395c8b515fd2e2b4fd25f39ae09933e93cd793921542e1%40group.calendar.google.com): fixed review, movable sign-off, and unrelated appointment. Owner: arnabc.kgp@gmail.com. No attendees or invitations.

## Primary UI-driven run

Plan `cb8ab02b2dfd4a3cad409eac9ab4ff79`, run `953fb4d48dce4d09bf2c873e8a658ee7`.

The UI requested September 18, showed the fixed September 21 review conflict, proposed September 24, displayed the exact five edits, accepted the test operator's approval, and reached **Verified**. Real OpenAI interpretation used `gpt-5-mini-2025-08-07`, 521 tokens, and 5,070 ms. The server-generated alternative reused this interpretation.

Execution took approximately 41 seconds. Every operation succeeded with one write attempt.

Across the primary request, guard cases, and two interruption/restoration requests, six real model calls consumed 3,882 tokens. Individual model latency ranged from 3,445 to 8,831 ms. Alternatives reused saved interpretation evidence.

| Source | Record | Before | Approved result |
| --- | --- | --- | --- |
| Calendar | M2 release sign-off | September 25, 15:00–16:00 | September 24, 15:00–16:00 |
| Notion | T4 review checklist | September 23 | September 22 |
| Notion | T5 release validation | September 24 | September 23 |
| GitHub | Release milestone | September 25 | September 24 |
| Notion | Release | September 25, baseline marker | September 24, approved plan marker |

All dates are 2026; meeting times use Asia/Kolkata. GitHub stores date-only milestone deadlines at midnight UTC.

## Independent verification

Fresh direct GET requests captured all 19 provider records before and after execution, separately from the run's own verification. Comparison checked full raw records, excluding request IDs and provider-maintained revision metadata. GitHub issues embed the milestone's current deadline, so that derived projection was accounted for separately.

Exactly five approved records changed. The other fourteen records were preserved, including fixed/completed tasks, the security review, the unrelated Notion task and GitHub issue, and the unrelated Calendar appointment. Unchanged Notion page revisions and unchanged Calendar events were compared exactly, excluding Notion's per-request ID. Descriptions, task metadata, attendee lists, reminders, recurrence, event IDs, and non-approved fields were preserved.

## Guardrails exercised against the live app

| Case | Observed result |
| --- | --- |
| Infeasible date | No operations; September 24 alternative |
| Approve infeasible plan | HTTP 409 |
| Wrong approval hash | HTTP 409 |
| Wrong approval version | HTTP 409 |
| Duplicate approval, including repeated idempotency key | Same run; all original write-attempt counts remained one |
| Ambiguous “next Friday” request | Real model requested clarification; zero operations |
| Request including emailing the team | Real model rejected unsupported action; zero operations |
| Request already-applied September 24 deadline | Ready with zero operations |
| Approve plan from the original snapshot after the real records changed | STALE at preflight; zero write attempts |
| Google refresh token exchange | Real Google token refresh succeeded; access token valid |

## Interruption and recovery

Run `06e7d92f8b7943eabf334d57b80c72a6` temporarily moved only the two release records to September 25. The actual local uvicorn process was stopped while its GitHub write was recorded as IN_FLIGHT. On restart, the persisted run became UNCERTAIN and appeared in the UI's unfinished-run list.

Resuming read GitHub first and found the requested value already present. It reconciled that operation without a second write, then applied the remaining Notion change. Both operations finished VERIFIED with one attempt each. This was a real process interruption and real provider reconciliation.

The test also found a status race: the resume endpoint could return while the persisted run still said UNCERTAIN, causing the UI to stop polling despite active background execution. The fix persists QUEUED before returning, while retaining operation-level uncertainty for read-before-retry. Three regression cases cover UNCERTAIN, PARTIAL, and FAILED runs. All 87 backend tests pass.

The repeat test used restoration plan `8657873dc6354a6c90963b77348651fd` and run `0f6d34f22705442484069a0f32f8ba3d`. The backend was stopped again during the GitHub write and restarted with the fix. Clicking Resume immediately showed Preflight, continued polling, and automatically reached Verified. GitHub was again reconciled with one attempt; Notion completed with one attempt. The final release date is September 24. Task and meeting dates remain as shown in the primary-run table; the release's Accepted plan marker identifies the restoration plan.

A final independent capture of all 19 raw provider records passed comparison against the original baseline plus the approved primary/restoration fields. All fourteen protected records remained preserved after the complete test sequence.

## Evidence and reproduction

Raw evidence stays in ignored `data/acceptance-*.json`; credentials stay in ignored `.env` and `secrets/`.

- `python -m scripts.capture_live_records before|after|final`: read-only raw provider captures.
- `python -m scripts.verify_live_acceptance`: compare the primary run's captures and approved plan. Add `--final` to compare the final restoration state against the original baseline.
- `python -m scripts.check_live_guards`: real model calls and approval guard checks after the primary run.
- `python -m scripts.check_live_interruption --server-pid <verified-local-uvicorn-pid>`: intentional process interruption; requires the documented dedicated fixture. Never run against an arbitrary PID or production deployment.

Retain the fixture for review. Do not recreate duplicate pages/events or delete unrelated content.

## Verification boundary

This validates the local connected workflow, not production readiness. Vercel deployment, hosted persistence and durable jobs, owner authentication, hosted OAuth, public-app verification, sustained load, revoked credentials, and exhausted provider-rate-limit retries remain outside this live acceptance. Automated isolated fault tests are separate from these real-service results.
