# Real application test data

Prepared September 14, 2026 (Asia/Kolkata). This document describes the original seed baseline. The app subsequently changed those real records during successful live acceptance; see `LIVE-ACCEPTANCE.md` for results and their current dates.

## Resources created

- [Notion test hub](https://app.notion.com/p/Deadline-Relay-Integration-tests-3da38db2744b81e4bcfee2cddb54b928), under the shared “Initial Suggestions by GPT 6 Astra” page in the owner's workspace.
- [Notion schedule database](https://app.notion.com/p/3da38db2744b81399a87d24f91cafd1e), containing nine records.
- [Private GitHub test repository](https://github.com/Arnab-c-h/deadline-relay-test), containing six issues and [release milestone 1](https://github.com/Arnab-c-h/deadline-relay-test/milestone/1).
- [Dedicated Google Calendar](https://calendar.google.com/calendar/u/0/r/settings/calendar/41104eb84b85bd3d2f395c8b515fd2e2b4fd25f39ae09933e93cd793921542e1%40group.calendar.google.com), titled “Deadline Relay · Integration tests”, timezone Asia/Kolkata, containing three events.

The user authorized fictional test content in actual applications. All resources above were created through authenticated provider tools or GitHub CLI. No personal events, pages, or issues were repurposed. Calendar events have no attendees, recurrence, conference links, or reminders.

## Baseline

All dates below are September 2026, with event times in Asia/Kolkata.

| ID | Record | Baseline | Depends on | Constraint |
| --- | --- | --- | --- | --- |
| T1 | Requirements approved | 11 | — | Done, fixed; GitHub issue closed |
| T2 | Implement export API | 16–17 | T1 | 2 business days; not before 14 |
| T3 | Integration testing | 18 | T2 | 1 business day |
| M1 | Security review | 21, 11:00–12:00 | T3 | Fixed |
| T4 | Apply review checklist | 23 | M1 | 1 business day |
| T5 | Release validation | 24 | T4 | 1 business day |
| M2 | Release sign-off | 25, 15:00–16:00 | T5 | Movable after approval |
| REL | Atlas Release 1.0 | 25 | M2 | Accepted plan: baseline |
| U1 | Refresh careers-page copy | 22 | — | Unrelated; outside milestone |
| U2 | Owner appointment | 23, 10:00–11:00 | — | Unrelated; preserve |

Notion holds T1–T5, M1/M2 metadata, REL, and U1. GitHub issues 1–6 map respectively to T1, T2, T3, T4, T5, U1. Google Calendar holds M1, M2, and U2. All open tasks have a not-before date of September 14.

## Findings from actual API responses

GitHub create and update calls both normalized `2026-09-25T12:30:00Z` to `2026-09-25T00:00:00Z`; an independent GET confirmed that value. The scheduler now writes date-only milestone values encoded as midnight UTC. Its delivery cutoff remains 18:00 local. A regression test checks that a normalized read-back does not trigger an extra milestone update.

The Notion connector created a real Status property, but rejected both conversion of the empty Predecessors column to a self-relation and creation of a new self-relation. The seed therefore uses explicit rich-text logical dependency IDs. The adapter accepts this only with `notion.predecessors_type: "rich_text"`; relation remains the default. Types and IDs are validated strictly, including unknown, duplicate, and self references. No implicit fallback is allowed.

Calendar setup encountered transient shared-provider quota errors. Retried operations succeeded after backoff. Independent event reads confirmed the timezone, dates, and disabled reminders.

## Evidence and verification boundary

Ignored local files retain the resource mapping and provider read-backs:

- `data/live-test-manifest.json`
- `data/live-provider-records.json` (creation responses)
- `data/live-readback.json` (independent Notion/Calendar reads)
- `data/github-readback.json` and `data/github-milestone-readback.json`
- `config.local.json` (known resource IDs and dependency mode)

Run `uv run python scripts/check_seed_evidence.py` to check captured baseline evidence. It validates all nine Notion rows, six issues, the milestone, and three events. This checker makes no API calls and cannot claim current live state or agent execution.

The interface has a compact neutral workspace, readable before/after fields, source links, expandable technical evidence, connection refresh, and a baseline deadline label. Browser checks now include populated live infeasibility, alternative review, approval, verified execution, unfinished-run discovery after an actual restart, and resume through verified completion. The live test report records the observed recovery-status bug and its verified fix.

## Next setup checkpoint

The assistant's Notion and Calendar MCP connections and GitHub CLI authentication remain separate from the Deadline Relay server. The server now has its own Notion and GitHub tokens and Google OAuth credentials. OpenAI and all three provider connections have been live-tested.

Required next:

1. Completed: OpenAI `gpt-5-mini` with the owner's key in ignored `.env`; strict structured interpretation passed three real API smoke cases. Evidence is in `data/openai-smoke.json`.
2. Completed: server-owned Notion/GitHub tokens and Google Calendar OAuth. Secrets remain ignored and local.
3. Completed: the Notion **data source ID** was discovered using the runtime token and saved in ignored local configuration. It differs from the database ID.
4. Hosted storage, durable execution, owner authentication, OAuth callbacks, and Vercel deployment described in `PRODUCTION-TARGET.md`.
5. Drive the actual deployed UI through infeasible September 18 → reviewed September 24 → approval → verified changes. Independently check only M2, T4, T5, milestone date, and REL changed; preserve T1/T2/T3/M1/U1/U2 and unrelated fields.

If this fixture is used after its planning dates pass, reseed or shift the dedicated records coherently before acceptance. Keep the dependency pattern and preservation controls intact. Retain existing records for owner review; cleanup must use only manifest-owned IDs.
