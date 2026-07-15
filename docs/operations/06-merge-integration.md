# Merge Integration Operation Report

Date: 2026-07-15
Branch: `codex/merge-integration`
Baseline commit: `bdd4ff6`

## Integrated behavior

- FastAPI lifespan owns the configured LangGraph checkpointer.
- PostgreSQL and SQLite checkpointers use async state access and application namespaces.
- Runtime ledger events incrementally update disposable projections.
- Qdrant knowledge retrieval and verified episodic-memory commits are injected when enabled.
- HTTP and interactive WebSocket replay use the same `after_sequence` cursor.
- CI installs production extras and validates Alembic upgrade plus schema drift.
- Compose runs frontend, backend, migration, PostgreSQL, and Qdrant services.

## Verification

- Backend tests: 55 passed, 1 PostgreSQL-environment test skipped locally.
- Ruff and compileall: passed.
- Frontend transport tests: 6 passed.
- Frontend production build: passed.
- Alembic SQLite upgrade and check: passed.
- Compose migration on PostgreSQL: passed.
- Compose health: frontend, backend, PostgreSQL, and Qdrant healthy.
- API task through Nginx: completed with 15 events and a valid hash chain.
- Projection row: completed at sequence 15.
- Nginx WebSocket task: completed.
- Backend restart during approval interrupt: resumed from PostgreSQL checkpoint.

## Issues found during container verification

- Qdrant required a writable `/qdrant/snapshots` volume with a read-only root filesystem.
- The migration service referenced the wrong Alembic configuration path and silently skipped
  PostgreSQL DDL. It now runs the checked-in migration directly and fails closed.
- The frontend build context lacked `.dockerignore` and included local dependencies.

## Residual verification boundary

The Compose run used `SECMIND_QDRANT_ENABLED=false` because no real Qwen embedding credential
was used during infrastructure verification. Qdrant itself was healthy and reachable from the
backend network; Qdrant store, embedding parsing, and verified-memory behavior are covered by
isolated tests. Enable Qdrant only after configuring the local LLM API key.
