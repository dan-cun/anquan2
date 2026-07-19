# Native Database Handoff

Date: 2026-07-19

## Branch and commit

- Branch: `codex/native-database`
- Base contract commit: `bdcae5a`
- Handoff commit: recorded after this document is committed

## Changed files

- `secmind/backend/app/database/models.py`: native SQLAlchemy business models.
- `secmind/backend/app/database/repositories.py`: repository implementations and aggregate factory.
- `secmind/backend/app/database/__init__.py`: public database exports.
- `secmind/backend/alembic/versions/20260719_0002_native_business_schema.py`: reversible business schema migration.
- `secmind/backend/alembic/env.py`: registers native model metadata for Alembic checks.
- `secmind/backend/tests/test_native_database.py`: focused persistence and migration coverage.

## Exported interfaces

Import `create_native_repositories` or `NativeRepositories` from `app.database`.

```python
repositories = create_native_repositories(settings.database_url)
```

The aggregate exposes `flows`, `tasks`, `agents`, `prompts`, `mcp`, `tool_calls`, `results`,
`approvals`, and `llm` repositories, plus the SQLAlchemy `engine` and session factory.

The schema contains 20 durable business tables for Flow planning, Agent instances and
delegations, independent message chains, Prompt versions, MCP servers and capabilities, unified
native/MCP tool calls, artifacts, evidence, findings, reports, approvals, and LLM calls/usage.

## Database migration

- Revision: `20260719_0002`
- Parent: `20260715_0001`
- Upgrade creates all 20 native business tables, foreign keys, uniqueness constraints, and query
  indexes.
- Downgrade removes only the tables and indexes owned by this revision.
- SQLite enables foreign-key enforcement on connection; PostgreSQL remains the production target.

## Requested configuration and dependencies

- No new dependency is required; the backend already provides SQLAlchemy and Alembic.
- The integration branch must construct repositories from `SECMIND_DATABASE_URL`.
- The integration branch must run `alembic upgrade head` before serving requests.

## Integration wiring required

- Replace the in-memory `FlowStore` dependency in `AppServices` with `repositories.flows`.
- Inject the relevant repositories into GraphQL, Agent, Prompt, and MCP services.
- Persist runtime-created Agent instances, delegations, messages, tool calls, results, approvals,
  and LLM accounting through these repositories.
- Keep `runtime_ledger_events` as the append-only audit stream and LangGraph checkpoint tables as
  resume internals; the new tables are durable queryable business facts.
- Do not cascade-delete runtime facts when a Flow is soft-deleted.

## Verification

```text
Ruff: passed
database and migration tests: 11 passed
full backend regression: 80 passed, 1 skipped
Alembic upgrade/downgrade and metadata drift checks: passed
git diff --check: passed
```

## Residual risks

- Repository wiring is intentionally deferred to the integration branch by the shared ownership
  contract, so the running application still uses its existing service wiring until integration.
- JSON columns accept contract-shaped dictionaries but do not independently run Pydantic schema
  validation; service boundaries remain responsible for validation.
- PostgreSQL deployment should run the migration against a staging copy before production rollout,
  even though SQLite and Alembic regression coverage is green.
