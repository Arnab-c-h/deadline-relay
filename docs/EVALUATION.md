# Evaluation evidence

Verified locally on September 13, 2026. These are measured local results, not live-provider results.

## Automated checks

`scripts/test.ps1` passed: Ruff, **54 Python tests**, **8 frontend tests**, TypeScript checking, and Vite production build. Python tests completed in 8.66 seconds in the final full run. Two upstream TestClient deprecation warnings remain (httpx integration and AnyIO BlockingPortal alias); there were no test failures.

| Layer | Passed | Evidence covered |
| --- | ---: | --- |
| Scheduler | 18 | Canonical five changes; September 18 infeasible; missing estimates; cycles; task/issue contradictions; fixed constraints; busy events; timezone and duration validation; unchanged records and blocker source links |
| Provider HTTP boundary | 13 | Narrow writes; versions; pagination; Notion schema/property validation; relation normalization; missing credentials; read health; Calendar ETags and recurrence restrictions |
| Durable workflow | 18 | No preapproval writes; tamper rejection; idempotency; source drift; partial recovery; applied timeout; wrong read-back; restart; exhausted retries and fresh recovery approval |
| API | 4 | Browser request sequence; explicit alternative approval; blocked external origin; missing live setup; strict approval payload |
| SQLite store | 1 | Persistence after reopening |
| Frontend | 8 | Alternative requires review; explicit approval; polling/retry; restored runs; VERIFIED terminal handling; recovery review without execution |

Providers use httpx MockTransport. Frontend behavior tests mock the HTTP boundary. Workflow tests use real SQLite and persisted fictional records, with injected provider faults. They do not establish real OAuth, write permissions, provider latency, or model quality.

## Actual browser check

Playwright drove the built application at `http://127.0.0.1:8000` through request → infeasible result → explicit September 24 alternative → exact five-operation approval → Verified. Clicks were normal user interactions; no forced clicks or direct API approval substituted for the browser journey.

Run `e092c00451a745de9e4a5c58c1710a38` completed at `2026-09-13T22:49:02.531627+05:30` with five operations, each **VERIFIED** on one attempt. The final journal recorded both `constraints_passed=true` and `preservation_passed=true`, in **simulated** mode.

Desktop approval and phone verification screenshots were captured and visually inspected:

- `output/playwright/approval-desktop.png` — 1280px viewport.
- `output/playwright/verified-mobile.png` — 390×844 viewport.

At phone width, document scroll width and viewport width were both 390px. Wide tables and dependency paths scroll inside their containers. Browser console after the final reload contained zero errors and zero warnings. The initial favicon 404 and a sidebar overlap blocking the alternative button were corrected before this successful check.

## Review changes

Independent scoped reviews prompted fixes for stale Calendar ETags, fixture-generation invalidation, mutable task coverage, fixed-release handling, invalid meeting/task intervals, immutable alternative requests, reload recovery, polling failures, exhausted retry recovery, fresh Notion metadata, incomplete response rejection, working-day busy horizon, and health probe scope. Relevant regressions passed after the changes. A final source-evidence regression ensures non-node busy blockers retain their links.

## Remaining acceptance work

- Select and implement a live LLM extraction adapter with strict output validation and real usage/latency reporting. The current date parser is visibly simulated.
- Configure dedicated Notion/GitHub/Calendar resources and runtime credentials. Validate real pagination, OAuth refresh, schema mappings, read access, and write permissions.
- Run the exact five-operation scenario against the real fixture and inspect protected fields in all three apps. Exercise live failure/recovery only within the dedicated demo resources.
- Measure repeated end-to-end success with an explicit denominator; do not extrapolate unit-test counts into production reliability.
- Have a second builder follow the clean-checkout setup. Setup commands are provided, but this independent check has not occurred.
- Record and review the two-minute demonstration; provide a repository remote and submission brief as required by the event.

No real external write, model request, remote push, deployment, or recorded submission was performed in this build phase.
