# Native Data Model Contract

This contract freezes table names, identifiers, ownership, and relationships for the native
multi-agent, MCP, Prompt, and GraphQL migration. The database implementation branch may add
indexes and internal columns, but it must not rename or repurpose the fields listed here.

## Identifier Rules

- Public identifiers are UUID strings and are exposed as GraphQL `ID`.
- `flow_id` is the root tenant boundary for runtime data.
- `run_id` identifies one execution of a Flow input.
- `task_id` and `subtask_id` form the durable planning hierarchy.
- `agent_instance_id` identifies a concrete Agent execution, not only an Agent role.
- `invocation_id` identifies one native or MCP tool call.
- Timestamps are UTC and stored as timezone-aware values.

## Durable Business Tables

### `flows`

Required columns: `id`, `title`, `status`, `created_at`, `updated_at`, `deleted_at`.

`FlowStore` must be backed by this table. Deletion is soft by default so audit relationships
remain readable.

### `tasks`

Required columns: `id`, `flow_id`, `title`, `objective`, `status`, `result_json`, `created_at`,
`updated_at`.

Foreign key: `flow_id -> flows.id`.

### `subtasks`

Required columns: `id`, `task_id`, `title`, `description`, `status`, `agent_role`, `position`,
`dependencies_json`, `result_json`, `created_at`, `updated_at`.

Foreign key: `task_id -> tasks.id`. `position` is ordering metadata; dependency identifiers are
the execution authority.

### `agent_instances`

Required columns: `instance_id`, `run_id`, `flow_id`, `role`, `status`, `task_id`,
`parent_instance_id`, `prompt_version_id`, `model_profile`, `metadata_json`, `started_at`,
`updated_at`, `completed_at`.

Foreign keys: `flow_id -> flows.id`, optional `task_id -> tasks.id`, optional self-reference
`parent_instance_id -> agent_instances.instance_id`.

### `agent_delegations`

Required columns: `delegation_id`, `run_id`, `flow_id`, `from_agent_instance_id`, `to_role`,
`to_agent_instance_id`, `agent_task_json`, `status`, `result_summary`, `created_at`,
`completed_at`.

Every Agent-to-Agent assignment creates one row before the target Agent starts.

### `agent_messages`

Required columns: `message_id`, `run_id`, `flow_id`, `from_agent_instance_id`,
`to_agent_instance_id`, `to_role`, `kind`, `summary`, `payload_ref`, `metadata_json`,
`sequence`, `timestamp`.

`summary` is public structured communication. Hidden model reasoning is not stored.

### `message_chains`

Required columns: `chain_id`, `run_id`, `flow_id`, `task_id`, `subtask_id`,
`agent_instance_id`, `agent_role`, `model_provider`, `model`, `summary`, `created_at`,
`updated_at`.

Every Agent instance owns an independent message chain. A chain may be summarized, but its
identity and usage attribution remain stable.

### `message_entries`

Required columns: `entry_id`, `chain_id`, `role`, `content`, `content_json`, `tool_call_id`,
`sequence`, `created_at`.

Foreign key: `chain_id -> message_chains.chain_id`. Unique constraint: `(chain_id, sequence)`.

### `prompts`

Required columns: `prompt_key`, `name`, `category`, `message_role`, `agent_role`, `source_path`,
`variables_json`, `active_version_id`, `metadata_json`.

`prompt_key` is stable and matches the Prompt workbook. It is never reused for another meaning.

### `prompt_versions`

Required columns: `version_id`, `prompt_key`, `version`, `content`, `variables_json`, `checksum`,
`status`, `source`, `created_at`, `activated_at`.

Unique constraint: `(prompt_key, version)`. Only one active version is allowed per Prompt key.

### `mcp_servers`

Required columns: `server_id`, `name`, `transport`, `command`, `args_json`, `cwd`, `env_refs_json`,
`url`, `header_refs_json`, `enabled`, `status`, `protocol_version`, `metadata_json`, `last_error`,
`created_at`, `updated_at`.

Secret values are never stored. `env_refs_json` and `header_refs_json` contain references only.

### `mcp_capabilities`

Required columns: `capability_id`, `server_id`, `kind`, `name`, `description`, `input_schema_json`,
`metadata_json`, `discovered_at`, `updated_at`.

Foreign key: `server_id -> mcp_servers.server_id`. Unique constraint: `(server_id, kind, name)`.

### `tool_calls`

Required columns: `invocation_id`, `run_id`, `flow_id`, `task_id`, `subtask_id`,
`agent_instance_id`, `tool_id`, `origin`, `server_id`, `arguments_json`, `status`, `text_result`,
`data_json`, `artifact_refs_json`, `evidence_ids_json`, `error_code`, `error_message`,
`duration_ms`, `created_at`, `updated_at`, `completed_at`.

Native and MCP calls share this table and lifecycle.

### Result Tables

- `artifacts`: immutable file and object references with hashes.
- `evidence`: evidence summaries and artifact references.
- `findings`: structured security findings referencing evidence identifiers.
- `reports`: versioned reports associated with `run_id`.
- `approvals`: pending and resolved human decisions.
- `llm_calls`: Agent/model request metadata and sanitized I/O references.
- `llm_usage`: token, cost, duration, Agent role, and model projections.

### Long-term Task Tables

- `skills`: versioned Skill content, checksum, tags, compatible roles, source, and enabled state.
- `skill_loads`: per-run/per-Agent on-demand Skill load history.
- `task_todos`: durable Todo lifecycle, dependencies, priority, and Evidence references.
- `task_notes`: typed fact/hypothesis/constraint/decision/observation/error Notes.
- `context_snapshots`: immutable structured context compression with source sequence cursors.

The complete behavior is frozen in `docs/contracts/long-term-task-capabilities.md`.

## Runtime and Projection Tables

- `runtime_runs` remains the serialized `AgentState` recovery snapshot.
- `runtime_ledger_events` remains the append-only hash-chained runtime fact stream. EventEnvelope
  1.1 adds `schema_version`, `flow_id`, `correlation_id`, `causation_id`, `decision_id`,
  `agent_instance_id`, `task_id`, `tool_invocation_id`, and `visibility`; legacy rows remain 1.0.
- LangGraph checkpoint tables remain execution-resume internals.
- `projection_*` tables are rebuildable GraphQL query views and are never a source of truth.

The append-only `decision.recorded` event is the DecisionRecord fact. A future
`projection_decisions` table may be built for queries, but no mutable decision fact table is
permitted.

## Delete and Retention Semantics

- Business rows use soft deletion where user-visible history matters.
- Runtime events, evidence, tool calls, and Agent messages are not cascade-deleted with a Flow.
- Binary artifact retention may expire independently, but its hash and audit reference remain.
- Projection rows may be dropped and rebuilt from durable business data and runtime events.

## Migration Ownership

The database branch owns SQLAlchemy models, repositories, and Alembic revisions. It must export
repository interfaces and a migration handoff; it must not modify application startup, GraphQL
mounting, shared Pydantic schemas, or dependency configuration.
