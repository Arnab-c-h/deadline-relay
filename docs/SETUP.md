# Runtime setup checkpoint

The application requires real provider connections and model access. See PRODUCTION-TARGET.md for the required Vercel migration. A Codex connector gives the assistant access; it does not give the independently running Python app credentials. This app uses direct provider APIs.

## Information needed from the owner

1. LLM provider and model to use, plus the location of its local API key. The model adapter is deliberately pending this choice. `LLM_PROVIDER`, `LLM_MODEL`, and `LLM_API_KEY` are reserved placeholders, not implemented switches.
2. Dedicated GitHub, Notion and Google Calendar destinations. The owner has authorized creating clearly named test records inside these actual apps for final acceptance; destination access is still required. Send resource links/IDs in chat; keep secrets in local files.
3. Runtime credentials with access to those resources. No live resource has been created or edited during this implementation. The OAuth helper below is for local diagnostics; deployed OAuth callbacks and encrypted credential persistence are required before hosted acceptance.

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

In `config.local.json`, set owner, repository, milestone number, and issue numbers for T1–T5 and U1. T1 must be closed; T2–T5 must be open and belong to the configured milestone. U1 remains unrelated. The milestone initially has a September 25, 2026, 18:00 Asia/Kolkata deadline (`2026-09-25T12:30:00Z`). The adapter only writes its `due_on` field; it never changes issues.

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
| Predecessors | relation to the same data source |
| Not before | date |
| Delivery date | date |
| Accepted plan | rich_text |

Create all properties in the data source; relevant fields must also be present with correct types in each returned page. Empty relation/date values are different from missing properties. Use `Done` for T1 and `Not started` for mutable tasks. In-progress tasks are unsupported. Notion owns task dates, estimates, fixed/completed flags, and dependencies. M1/M2 Notion rows carry dependency/fixed metadata; Calendar owns their actual start/end timestamps.

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
