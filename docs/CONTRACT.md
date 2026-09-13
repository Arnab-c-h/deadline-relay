# Internal contract v1

Authoritative PRD: `../../PRD.md`. Python module root `relay/`. JSON-compatible dictionaries at adapter/planner boundaries; Pydantic models validate HTTP requests in main.py. All operations concern project `demo` only. No external resources or credentials are created during development.

## Snapshot

`{id?:str, captured_at?:str, mode:'simulated'|'live', project:{id:'demo',name:'Atlas Release 1.0',timezone:'Asia/Kolkata',planning_start:'2026-09-14',horizon_days:30,deadline:'2026-09-25'}, nodes:list[Node], records:dict[str,Record], config_hash:str}`

Node: `{id,name,kind:'task'|'meeting'|'release',record_key,predecessors:list[str],start:str,end:str,duration_days:int|null,fixed:bool,completed:bool,not_before:str|null,issue_state:'open'|'closed'|null,source_url:str|null}`. Tasks use ISO dates inclusive, meetings offset datetimes, release start=end=date. U1 unrelated task and U2 unrelated calendar meeting have no path to REL. U2 fixed true. T1 historical completed fixed. Nodes include T1-T5, M1-M2, REL, U1-U2. Recurring/all-day flags optional on busy records; planner reject only if edits required, busy handling read-only.

Record: `{key,provider:'notion'|'github'|'calendar',resource_id,name,source_url:str|null,fields:dict,etag:str|null}`. Record keys `notion:T1` through T5, `notion:REL`, `notion:U1`, `calendar:M1`, `calendar:M2`, `calendar:U2`, `github:REL`, `github:T1` through T5 and `github:U1`. Fields are normalized **user-controlled business values**: Notion task `{Schedule:{start:date,end:date},EstimateDays:int,Fixed:bool,Status:str,Predecessors:list[str],NotBefore:date|null,Name:str}`; release `{DeliveryDate:date,AcceptedPlan:str,Name:str}`; calendar `{start:offset-datetime,end:offset-datetime,summary,description,location,transparency:'opaque'|'transparent',recurring:bool,all_day:bool,fixed:bool}`; GitHub milestone `{due_on:UTC-string,title,description}`; issues `{state,milestone:int|null,title}`. Provider-managed timestamps ignored. Record field comparison checks full stored fields. Extra user fields allowed and preserved. Calendar busy records may be added beyond U2. Adapter builds nodes from fresh records.

## Scheduling

`relay.scheduler.propose(snapshot:dict, requested_date:str) -> dict`: no writes; return `{status:'ready'|'infeasible'|'blocked'|'unsupported',requested_date,proposed_date:str|null,explanation:str,conflicts:list[str],operations:list[Operation],items:list[dict],assumptions:list[str]}`. Infeasible result has proposed_date earliest alternative but operations=[]; caller must explicitly propose again for alternative. items `{id,name,kind,before:str,after:str,disposition:'changed'|'constraint'|'unchanged'|'unrelated',source_url}`.

Operation `{id:str,record_key,provider,resource_id,name,source_url,before:dict,after:dict}`. before/after contain only changed top-level fields; operation ID stable within plan (e.g. op-1). Required ready September24 operations, in order: calendar:M2 start/end, notion:T4 Schedule, notion:T5 Schedule, github:REL due_on, notion:REL DeliveryDate. Executor service adds AcceptedPlan marker to final release operation before computing immutable plan hash. Scheduler fixture expects five operations; dates Sep24 15-16, T4 Sep22, T5 Sep23, milestone 2026-09-24T00:00:00Z. GitHub milestone due dates use date-only semantics encoded at midnight UTC; the scheduler's business release cutoff remains 18:00 in the project timezone. Midnight is not the release-time constraint. Sept18 impossible due M1. T2/T3 unchanged.

## Adapter

`relay.providers.base.ProviderError(message, *, kind='permanent', retry_after=0)` where kind is transient/uncertain/stale/permanent/auth.

`provider.snapshot() -> Snapshot`, `provider.read(record_key:str) -> Record`, `provider.write(record_key:str, changes:dict, etag:str|None=None) -> None`, `provider.health() -> list[{provider,status:'simulated'|'ready'|'missing'|'error',detail}]`. Adapter rejects unknown resource keys and writable field paths before issuing calls. Live provider lives relay/providers/live.py; config validates actual resource IDs/properties, no guessed mapping. No simulator implementation in live.py. Fixture simulation implemented by root using fixture snapshot builder and SQLite, never silent fallback from live.

Notion dependencies default to `notion.predecessors_type='relation'`: page UUIDs must map to configured allowlisted Notion records. Explicit `notion.predecessors_type='rich_text'` instead accepts comma-separated logical IDs such as `T1, M1`; blank text means no predecessors. Both the data-source schema and page property must match the selected type, with no automatic fallback. IDs must exist in both the configured Notion records and node mapping. Unknown IDs, duplicates, self references, and empty comma-separated entries are rejected. Both representations normalize to `Predecessors:list[str]`; dependencies remain read-only.

`relay.fixtures.build_fixture() -> Snapshot` owns complete canonical fixture. Scheduler agent owns fixtures.py, scheduler.py, tests/test_scheduler.py ONLY.

## HTTP (frontend root /api)

GET /projects/demo/health => `{mode,project:{name,timezone},connections:list,model:{status,detail},runs:list[{id,status,updated_at}],setup_required:list[str]}`.
POST /projects/demo/snapshots body {} => Snapshot with id.
POST /projects/demo/plans body `{snapshot_id,request,alternative_date?:ISO-date}` => Plan `{id,version:1,hash,snapshot_id,request,status,requested_date,proposed_date,explanation,conflicts,operations,items,assumptions,created_at,mode,interpretation:{method,model?,usage?}}`. alternative_date accepted only from prior server-computed alternative with parent_plan_id; send parent_plan_id when selecting.
GET /plans/{id} => Plan.
GET /snapshots/{id} => stored Snapshot for review and restored-run context.
POST /plans/{id}/approve body `{version,hash,idempotency_key}` => `{run_id}` (202). GET /runs/{id} => `{id,plan_id,status,mode,created_at,updated_at,reason,operations:list[Operation+{status,attempts,evidence?,error?}],verification?:dict}`.
POST /runs/{id}/resume body `{idempotency_key}` => `{run_id}` (202).
POST /runs/{id}/recovery-plan body `{}` => a new Plan after EXHAUSTED retries. It contains only remaining edits, a fresh snapshot/version/hash, and requires a separate approval. This endpoint never executes writes.
POST /demo/reset body `{confirm:true}` => `{ok:true}` only simulated, blocked while unfinished runs exist. No browser fault injection controls in first UI; tests use provider test helper hooks.
Errors `{detail:str}`. Frontend polls run 750ms while status QUEUED/PREFLIGHT/EXECUTING/VERIFYING, stops on pause/final. Resume visible PARTIAL/UNCERTAIN/FAILED (server controls eligibility); stale/mismatch requires new snapshot/plan. Every mutation stores idempotency key per action stable across retries. No auto approval; choose alternative fetches a new plan then requires human approval.
Successful terminal status is VERIFIED. EXHAUSTED permits recovery-plan review, not blind resume. Request parsing may return clarification with a null requested_date; the UI must not fabricate a date or offer an executable alternative.
