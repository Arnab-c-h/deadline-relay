# Runtime setup checkpoint

The application requires real provider connections and model access. See PRODUCTION-TARGET.md for the required Vercel migration. A Codex connector gives the assistant access; it does not give the independently running Python app credentials. This app uses direct provider APIs.

## Information needed from the owner

1. OpenAI is implemented and configured with `LLM_PROVIDER=openai`, `LLM_MODEL=gpt-5-mini`, and the owner's `LLM_API_KEY` in `.env`. `OPENAI_API_KEY` is accepted only when `LLM_API_KEY` is empty. Health verifies model access; actual generation can still fail on billing or rate limits.
2. Dedicated GitHub, Notion and Google Calendar test records have been created and read back. See `LIVE-TEST-SETUP.md` for their links and verification boundary.
3. The Python server still needs runtime credentials with access to those resources. The OAuth helper below is for local diagnostics; deployed OAuth callbacks and encrypted credential persistence are required before hosted acceptance.

## OpenAI verification

Run `uv run python -m scripts.check_openai` for three real API calls: complete date, ambiguous relative date, and an unsupported extra action. This consumes API tokens but never writes to the connected applications. Results, actual model version, token usage, request IDs and latency are stored in ignored `data/openai-smoke.json`. The September 14 run passed all three cases.

Interpretation uses [OpenAI Responses structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs) with strict local schema and calendar-date validation. The model has no tools and receives only the request and timezone. Refusals, incomplete responses, malformed output and API errors block planning without a parser fallback. The deterministic scheduler produces operations; approval remains bound to the saved plan hash. Selecting a server-proposed alternative reuses the original interpretation evidence without another model call.

## Local files

From the repository root, copy only if you have not already configured these files:

```powershell
Copy-Item .env.example .env
Copy-Item config.example.json config.local.json
New-Item -ItemType Directory -Force secrets
```

Both local configuration files and `secrets/` are ignored. Use `RELAY_MODE=live`. Startup rejects a simulated environment setting. Until real connections and the model adapter are ready, the application displays setup requirements and blocks planning.

## GitHub

Set `GITHUB_TOKEN` in `.env`. Use a token limited to the dedicated repository with the issue/milestone read and write access needed by the app. Read health does not prove write permissions.

In `config.local.json`, set owner, repository, milestone number, and issue numbers for T1–T5 and U1. T1 must be closed; T2–T5 must be open and belong to the configured milestone. U1 remains unrelated. The milestone initially has a September 25, 2026 due date (`2026-09-25T00:00:00Z`). GitHub normalizes milestone dates to midnight UTC; use that representation for writes and read-back verification. The project's business release cutoff remains 18:00 Asia/Kolkata and is evaluated independently of the milestone timestamp. The adapter only writes its `due_on` field; it never changes issues.

## Notion

Set `NOTION_TOKEN` in `.env` and give the integration access to the dedicated data source and pages. Configure the **data source ID**, plus page IDs for T1–T5, M1, M2, REL, and U1. Relations refer to these actual page IDs, not display names. Cross-app resource lookup comes from the allowlisted local configuration.

Required mapped properties:

| Property | Type |
| --- | --- |
| Name | title |
| Schedule | date |
| Estimate days | number |
| Fixed | checkbox |
| Status | status |
| Predecessors | relation to the same data source (default), or explicitly configured rich_text |
| Not before | date |
| Delivery date | date |
| Accepted plan | rich_text |

Create all properties in the data source; relevant fields must also be present with correct types in each returned page. Empty relation/date values are different from missing properties. Use `Done` for T1 and `Not started` for mutable tasks. In-progress tasks are unsupported. Notion owns task dates, estimates, fixed/completed flags, and dependencies. M1/M2 Notion rows carry dependency/fixed metadata; Calendar owns their actual start/end timestamps.

If the connector cannot create a self-relation, explicitly set `"predecessors_type": "rich_text"` inside the `notion` configuration object and make the mapped Predecessors property a rich-text property. Enter comma-separated logical IDs, for example `T1, M1`, rather than page UUIDs or display names. Whitespace around IDs is trimmed; blank text means no predecessors. Every ID must exist in both `notion.records` and `nodes`. Duplicate IDs, self references, unknown IDs, and empty entries such as `T1,,M1` block snapshot creation. Schema and page types must match the explicit setting; the adapter never falls back from a failed relation read. Omitting this setting keeps relation mode and its allowlisted page-ID validation.

Set the dependency chain to T1 → T2 → T3 → M1 → T4 → T5 → M2 → REL. U1 has no predecessors. Fixture dates and estimates are in PRD §11 and `relay/fixtures.py`. The API version headers implemented in `relay/providers/live.py` and schema behavior still require live validation.

## Google Calendar

Use a dedicated calendar owned by the authorizing Google account. Enable the Calendar API in your Google project, configure your OAuth consent/test-user access, and place a downloaded **Desktop OAuth client JSON** at `secrets/google-client.json`.

Run the supplied helper when ready to authorize:

```powershell
uv run python scripts/google_auth.py --client-secrets secrets/google-client.json --token secrets/google-token.json
```

The helper opens the Google consent flow and writes a local token. It requests `calendar.events.owned` and `calendar.freebusy`. Set `GOOGLE_TOKEN_PATH=secrets/google-token.json` in `.env`. The helper does not create calendars or events.

Configure the calendar ID and existing M1, M2, and U2 event IDs. All use Asia/Kolkata:

| Event | Baseline | Rule |
| --- | --- | --- |
| M1 Security review | September 21, 11:00–12:00 | Fixed |
| M2 Release sign-off | September 25, 15:00–16:00 | Movable; non-recurring, timed event |
| U2 Owner appointment | September 23, 10:00–11:00 | Unrelated; preserved |

Other opaque events in the configured horizon constrain meeting availability. The app reads and preserves their source evidence. Calendar writes use `If-Match` with the observed ETag; stale responses stop execution.

## Live acceptance gate

After model selection, finish its structured extraction adapter and tests, then restart the server with the live configuration. Confirm authentication and read access independently for each app, inspect the full snapshot, and test only the dedicated fixture. Verify every approved value and every protected field in all three real apps. Record actual request latency, model usage/cost, retry outcomes, and screenshots. Do not label the submission live-ready before these checks pass.

Configuration is read at process start. Restart after changing resource mappings or credentials. Secrets must not be pasted into source files, screenshots, or the submission recording.
