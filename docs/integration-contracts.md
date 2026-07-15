# SecMind Integration Contracts

This document freezes the shared contracts used by parallel implementation branches.

## Ownership

Only the integration branch may modify these shared files:

- `secmind/backend/pyproject.toml`
- `secmind/backend/app/core/config.py`
- `secmind/backend/app/services/context.py`
- `secmind/backend/app/main.py`
- `secmind/backend/app/api/router.py`
- `secmind/backend/app/schemas/runtime.py`
- `secmind/backend/app/schemas/events.py`
- `secmind/backend/app/websocket/router.py`

Other branches must report required configuration or contract changes instead of editing
these files directly.

## Agent State

`AgentState` is the durable public state model. LangGraph nodes may use an internal typed
state wrapper, but persisted snapshots and API responses must validate as `AgentState`.

The stable execution fields are:

- Identity: `schema_version`, `run_id`, `task`.
- Routing: `scenario`, `status`, `current_step_index`, `active_step_id`.
- Context: `input_artifacts`, `knowledge_hits`.
- Execution: `plan`, `completed_step_ids`, `observations`, `retry_counts`.
- Audit: `evidence`, `findings`, `decisions`, `approvals`.
- Control: `pending_approval`, `budget`, `reflection_count`, `verification_passed`.
- Persistence: `state_revision`, `started_at`, `updated_at`, `completed_at`.

New fields must have defaults while schema version 1.x is active. Removing or changing the
meaning of a field requires a major schema version and a migration.

## Runtime Events

Canonical event names are defined by `RuntimeEventType`. The ledger stores the string value,
not the enum object, so historical and extension events remain readable. Every event is
identified by `run_id + sequence`; consumers must not order events by arrival time.

The event ledger is the audit source of truth. LangGraph checkpoints are only execution-resume
state, and projections are rebuildable query views.

## WebSocket Protocol

Interactive endpoint: `WS /ws/flows/{flow_id}`.

Client message types:

- `client.user_message`: `payload.content` and optional `payload.metadata`.
- `client.approval_response`: `approval_id`, `approved`, optional `reason`.
- `client.ping`.

Server message types:

- `server.connected`, `server.status`, `server.ledger_entry`.
- `server.interrupt`, `server.done`, `server.error`, `server.pong`.

The envelope contains `schema_version`, `type`, `payload`, `flow_id`, `request_id`, optional
`sequence`, and `timestamp`. Unknown envelope fields are accepted for compatible extensions.

Audit stream endpoint: `WS /api/v1/runs/{run_id}/events?after_sequence=N`.
It is server-only and emits serialized `LedgerEvent` objects, not interactive `WSMessage`
envelopes. Reconnected clients resume from the last processed sequence.

## Configuration

- `SECMIND_DATABASE_URL` is the canonical SQL DSN. The legacy
  `SECMIND_RUNTIME_DATABASE_URL` remains accepted temporarily, with the canonical value taking
  precedence when both are set.
- `SECMIND_CHECKPOINT_BACKEND` is `memory`, `sqlite`, or `postgres`.
- `SECMIND_CHECKPOINT_DATABASE_URL` falls back to `SECMIND_DATABASE_URL`.
- All model configuration uses `SECMIND_LLM_*`; `SECMIND_QWEN_*` must not be introduced.
- Qdrant configuration uses `SECMIND_QDRANT_*`.
- Projection configuration uses `SECMIND_PROJECTION_*`.

Secrets use direct environment variables for local development or the matching `_FILE`
setting in containers. APIs must never return secret values.

## Branch Handoff Requirements

Parallel branches must expose implementations without wiring them into shared application files:

- LangGraph branch: a runtime constructor that accepts a checkpointer and uses `run_id` as
  `configurable.thread_id`.
- Persistence branch: a checkpointer async context manager and a projection service with
  `startup`, `shutdown`, and `rebuild` operations.
- Knowledge branch: a store compatible with the existing knowledge API plus async retrieval and
  verified-memory methods for graph nodes.
- Compose branch: required environment values and secret mount paths, without adding alternate
  configuration names.
- Frontend branch: no new message names; protocol additions must be requested in its report.

Each handoff report must list changed files, exported interfaces, requested configuration fields,
tests, and unresolved risks. The integration branch performs all dependency injection changes.
