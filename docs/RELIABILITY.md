# Reliability brief

Deadline Relay coordinates one bounded release across three sources. Notion owns task scheduling and dependencies; GitHub owns milestone issue membership/state and delivery date; Google Calendar owns meeting times and busy intervals. Configured IDs determine resource access. Source text is data, never execution authority.

Planning is deterministic and write-free. A plan includes exact field patches, source snapshot, assumptions, version, and a canonical hash. An atomic SQLite transaction binds approval and an idempotency key to one durable run. A repeated request returns that run rather than creating another. Only one unfinished execution is allowed.

The executor rereads the complete bounded snapshot before writing and rereads each target immediately before its patch. Calendar also enforces its ETag at the provider. A write attempt and intended values are persisted before the network call. Responses alone are not proof of success: each patch is read back, and all protected normalized fields are compared after execution. Final scheduling validation must produce no outstanding changes.

After timeout or interruption, the executor compares observed values with the approved before/after values. Already-applied changes are verified without another write. Unchanged targets may be retried within three attempts and the run time budget. Divergent or unreadable state stops the run. Exhausted attempts require a fresh reviewable recovery plan and approval; earlier verified work remains visible.

There is no distributed transaction across providers and no automatic rollback. A concurrent Notion/GitHub edit can race the final pre-write read because those patches lack the Calendar conditional-write guarantee. Read-back catches observed discrepancies but cannot guarantee future state. Single-process, loopback-only operation is part of the supported deployment boundary.

The simulator exercises fault scenarios through injected provider failures. Live adapters have HTTP-boundary tests, including incomplete Notion responses, relation pagination, timestamp normalization, field allowlists and Calendar preconditions. Real credentials, live model extraction, end-to-end provider behavior, write permissions, and the submission recording remain unverified.
