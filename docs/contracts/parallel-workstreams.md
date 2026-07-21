# Parallel Workstream Briefs

These briefs are the starting context for independent Codex conversations. Each conversation
uses its own Git worktree and branch created from the integration baseline.

## Common Rules

1. Read `docs/integration-contracts.md`, `docs/contracts/native-data-model.md`, and
   `docs/contracts/runtime-event-contract.md`, then read
   `secmind/backend/app/graphql/schema.graphql` before implementation.
2. Do not edit shared files owned by the integration branch.
3. Use canonical models from `app.schemas.agents`, `app.schemas.mcp`, `app.schemas.prompts`, and
   `app.schemas.tools`; do not create parallel public models.
4. Add focused unit and integration tests in the implementation-owned package.
5. Finish with the handoff report required by `docs/integration-contracts.md`.

## Database Workstream

Branch: `codex/native-database`.

Implement SQLAlchemy models, repositories, and Alembic migrations for the tables frozen in
`native-data-model.md`. Replace the in-memory behavior behind an exported Flow repository, but do
not wire it into `AppServices`. Provide SQLite-compatible tests where practical and PostgreSQL
migration tests for production behavior.

## Prompt Workstream

Branch: `codex/native-prompts`.

Implement Jinja2 rendering, Prompt Registry, version activation, Go Template conversion, and
workbook import. Consume `PromptTemplateRecord`, `PromptVersionRecord`, and `PromptWorkbookRow`.
The returned workbook uses `Prompt键` and `修改后Prompt` as authoritative columns. Export a
service constructor without modifying shared startup or configuration.

## MCP Workstream

Branch: `codex/native-mcp`.

Implement stdio, Streamable HTTP, and SSE clients; server lifecycle; Tools/Resources/Prompts
discovery; and conversion to the unified tool contract. Export an MCP manager and tool gateway.
Connected capabilities are visible by default. Do not add a subsystem enable flag or alternate
MCP configuration names.

## Agent Workstream

Branch: `codex/native-agents`.

Implement native Agent base classes, the 15-role registry, dispatcher, delegation lifecycle,
independent message chains, and reusable Agent subgraphs. Consume the shared Agent, Prompt, and
tool contracts. Emit canonical `agent.*` events through an injected publisher; do not instantiate
the global runtime or modify application wiring.

## GraphQL Workstream

Branch: `codex/native-graphql`.

Implement the frozen Strawberry GraphQL SDL using injected service protocols. Provide Query,
Mutation, and Subscription router construction. Resolver code does not directly construct Agent,
MCP, or database global objects. Subscription ordering and replay use `run_id + sequence`.

## Frontend Workstream

Branch: `codex/native-frontend`.

Add Apollo Client, generated GraphQL types, dynamic Agent nodes, true delegation edges, native/MCP
tool views, Prompt version management, and event replay. Keep the existing REST/WebSocket path
usable until the integration branch mounts GraphQL and accepts the frontend handoff.

## Integration Acceptance Order

1. Database and Prompt repositories.
2. MCP manager and unified tool gateway.
3. Agent registry/dispatcher and graph subgraphs.
4. GraphQL router and subscriptions.
5. Frontend Apollo migration.
6. Compose, startup, recovery, and end-to-end verification.
