# GraphQL Integration Handoff

This package implements the frozen contract in `schema.graphql` with Strawberry. It is an
unwired application boundary: resolvers depend only on injected service ports and never read ORM
sessions, repositories, or application globals directly.

## Public exports

- `create_graphql_router(backend_provider, graphql_ide="graphiql")` creates the FastAPI router.
- `graphql_schema` exposes the compiled Strawberry schema.
- `GraphQLBackend` composes the eight required ports from `ports.py`: flows, agents, tools, MCP,
  prompts, audit, analytics, and events.

The provider receives the current Starlette `HTTPConnection`, may be synchronous or asynchronous,
and must return a `GraphQLBackend`. A new `GraphQLContext` and DataLoader set is created for every
HTTP request or WebSocket connection.

## Integration wiring

The integration branch owns the concrete adapters and application mounting. The expected shape is:

```python
from starlette.requests import HTTPConnection

from app.graphql import create_graphql_router
from app.graphql.ports import GraphQLBackend


def provide_graphql_backend(connection: HTTPConnection) -> GraphQLBackend:
    services = connection.app.state.services
    return GraphQLBackend(
        flows=GraphQLFlowAdapter(services),
        agents=GraphQLAgentAdapter(services),
        tools=GraphQLToolAdapter(services),
        mcp=GraphQLMCPAdapter(services),
        prompts=GraphQLPromptAdapter(services),
        audit=GraphQLAuditAdapter(services),
        analytics=GraphQLAnalyticsAdapter(services),
        events=GraphQLEventAdapter(services.runtime_events),
    )


app.include_router(
    create_graphql_router(provide_graphql_backend),
    prefix=resolved_settings.graphql_path,
)
```

The event adapter must consume the same runtime event hub/ledger as REST and the legacy WebSocket
endpoint. It must honor the `run_id` and `after_sequence` filters forwarded by subscriptions so
replay ordering remains `run_id + sequence`.

Flow adapters provide `list_tasks(flow_id)` and `list_subtasks(task_id)` as batchable reads. The
request-scoped loaders use those methods to hydrate `Flow -> Task -> Subtask` without resolver-level
repository access.

Nullable input members without an SDL default use `strawberry.UNSET` when omitted and `None` when
the client explicitly sends `null`. Concrete mutation adapters must preserve that distinction when
applying partial updates. Fields with declared defaults continue to receive their SDL value.

## Integration impact

- Database migrations: none.
- New configuration: none; mounting reads the existing `SECMIND_GRAPHQL_PATH` setting.
- New dependencies: none; the backend already declares `strawberry-graphql[fastapi]`.
- Shared-file changes required: mount the router and compose adapters in the integration branch.

Contract and API coverage lives in `tests/test_graphql_contract.py` and
`tests/test_graphql_api.py`.
