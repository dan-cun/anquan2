# SecMind Native Migration Integration Contracts

This document is the shared authority for parallel database, Prompt, MCP, Agent, GraphQL, and
frontend work. Contract changes are integrated here before implementation branches consume them.

## Integration Ownership

Only the integration branch may modify these shared files:

- `secmind/backend/pyproject.toml`
- `secmind/backend/.env.example`
- `secmind/backend/app/core/config.py`
- `secmind/backend/app/services/context.py`
- `secmind/backend/app/main.py`
- `secmind/backend/app/api/router.py`
- `secmind/backend/app/schemas/*`
- `secmind/backend/app/graphql/schema.graphql`
- `secmind/backend/app/websocket/router.py`
- `docs/integration-contracts.md`
- `docs/contracts/*`

Implementation branches report requested changes to the integration branch instead of editing
these files.

## Branch Ownership

| Branch | Owns | Must export |
| --- | --- | --- |
| database | SQLAlchemy models, repositories, Alembic | Repository interfaces, migrations |
| prompts | Jinja2 renderer, registry, workbook importer | Prompt service and validation report |
| mcp | transports, client manager, capability registry, gateway adapter | MCP manager and tool gateway |
| agents | Agent implementations, registry, dispatcher, Agent subgraphs | Agent registry and dispatcher |
| graphql | Strawberry types, resolvers, subscriptions | GraphQL router constructor |
| frontend | Apollo client, dynamic network, MCP/Prompt UI | Production frontend bundle/tests |

No branch wires itself into `AppServices`, application startup, Compose, or shared routers. The
integration branch performs dependency injection after accepting a handoff.

## Contract Versions

- Runtime state schema: `app.schemas.runtime.SCHEMA_VERSION`.
- WebSocket protocol: `app.schemas.events.WS_PROTOCOL_VERSION`.
- Native Agent contract: `NATIVE_AGENT_CONTRACT_VERSION`.
- Unified tool contract: `NATIVE_TOOL_CONTRACT_VERSION`.
- MCP contract: `MCP_CONTRACT_VERSION`.
- Prompt contract: `PROMPT_CONTRACT_VERSION`.
- GraphQL contract: `app/graphql/schema.graphql` tracked in Git.

All 1.x changes are additive. Removing a field, changing a field meaning, or reusing an event
name requires a major contract version and an explicit database migration.

## Agent Contract

Canonical Pydantic models are defined in `app/schemas/agents.py`:

- `AgentDescriptor`: stable role registration and Prompt/model binding.
- `AgentTask`: complete unit passed through a delegation.
- `AgentInstance`: one concrete Agent execution.
- `AgentDelegation`: durable Agent-to-Agent assignment.
- `AgentMessage`: public structured Agent communication.
- `AgentResult`: normalized Agent completion or failure.

The native role set contains 15 roles and is frozen as `AgentRole`. Implementations may register
additional roles only through an additive contract proposal.

Agent delegation is a first-class operation, not a synthetic tool call. Every delegation must
create an `AgentDelegation`, emit `agent.delegated`, and eventually produce an `AgentResult`.

## MCP and Unified Tool Contract

Canonical models are defined in `app/schemas/mcp.py` and `app/schemas/tools.py`.

- Native and MCP tools share `UnifiedToolDefinition`, `UnifiedToolInvocation`, and
  `UnifiedToolResult`.
- `tool_id` is globally unique and namespaced by the registry implementation.
- MCP Tools, Resources, and Prompts are represented by `MCPCapability`.
- MCP configs store environment/header references; they never contain resolved secret values.
- All connected MCP capabilities are visible to the native registry by default. Optional Agent
  scoping is implementation configuration, not a contract requirement.

Supported transports are `stdio`, `streamable_http`, and `sse`.

## Prompt Contract

Canonical models are defined in `app/schemas/prompts.py`.

- `prompt_key` matches the key in the delivered Prompt workbook.
- The returned workbook's `modified_prompt` is the import source.
- Prompt content is versioned; overwriting an existing version is forbidden.
- One Prompt key has at most one active version.
- Imported Go Template syntax is converted and validated by the Prompt implementation branch.
- Runtime Agent records store the selected `prompt_version_id` for reproducibility.

## Database Contract

Table names, required fields, foreign keys, retention, and migration ownership are frozen in
`docs/contracts/native-data-model.md`.

PostgreSQL business tables are queryable facts. `runtime_ledger_events` is the append-only audit
stream. LangGraph checkpoint tables are resume internals. `projection_*` tables are rebuildable
GraphQL read models.

## GraphQL Contract

The canonical SDL is `secmind/backend/app/graphql/schema.graphql`.

- HTTP and WebSocket endpoint: `SECMIND_GRAPHQL_PATH`, default `/graphql`.
- Query reads Service/repository interfaces and never raw global state.
- Mutation delegates to Services and returns persisted domain objects.
- Subscription reads the common runtime event stream.
- Subscription replay and REST/WebSocket replay use `run_id + sequence` ordering.
- GraphQL field names use camelCase; database and Pydantic names remain snake_case.

Schema implementation may add internal resolver helpers but may not rename SDL operations or
change nullability without integration approval.

## Runtime Events

Canonical event names are `RuntimeEventType` values. The ledger stores the string value so
historical and extension events remain readable.

New native groups include:

- `flow.*`, `task.*`, `subtask.*`
- `agent.created|started|delegated|message|completed|failed|cancelled`
- `plan.revised`
- `tool.started|completed|failed|cancelled`
- `mcp.connected|disconnected|capabilities_updated|call_*`
- `prompt.version_created|version_activated|imported`
- `evidence.recorded`, `finding.recorded`, `report.generated`

Events are identified and ordered by `run_id + sequence`; arrival time is not an ordering key.

## WebSocket Compatibility

The existing interactive endpoint remains `WS /ws/flows/{flow_id}` during frontend migration.
Native domain events are sent inside `server.ledger_entry`, so existing clients tolerate them.

GraphQL Subscription becomes the primary frontend stream after the Apollo migration. Both paths
must consume the same event hub and ledger sequence.

## Shared Configuration

- `SECMIND_DATABASE_URL`: canonical application SQL DSN.
- `SECMIND_GRAPHQL_PATH`: GraphQL HTTP/WebSocket path.
- `SECMIND_AGENT_MAX_PARALLEL`: configurable native Agent concurrency.
- `SECMIND_AGENT_MAX_DELEGATION_DEPTH`: configurable delegation recursion boundary.
- `SECMIND_MCP_CONFIG_FILE`: optional native MCP server configuration.
- `SECMIND_MCP_*_TIMEOUT_SECONDS`: connection/call runtime timeouts.
- `SECMIND_MCP_REFRESH_INTERVAL_SECONDS`: capability refresh interval.
- `SECMIND_PROMPT_OVERRIDE_DIR`: optional Prompt source override.
- `SECMIND_PROMPT_WORKBOOK_PATH`: optional workbook import source.
- `SECMIND_PROMPT_AUTO_RELOAD`: Prompt override reload behavior.

No `*_ENABLED` flag is defined for native Agent, MCP, Prompt, or GraphQL subsystems. An empty MCP
configuration means zero external servers, not a disabled subsystem.

## Handoff Requirements

Every implementation branch hands off:

```text
branch and commit:
changed files:
exported interfaces:
database migrations:
requested configuration/dependencies:
tests and results:
integration wiring required:
unresolved risks:
```

A handoff is rejected when it modifies shared files, invents alternate contract models, stores
resolved secrets, bypasses the common event stream, or lacks focused tests.
