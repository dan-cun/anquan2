# Native MCP Runtime Handoff

## Branch And Commit

- Branch: `codex/native-mcp`
- Commit: this commit, `feat: add native MCP connection runtime`
- Baseline: `bdcae5a feat: freeze native migration contracts`

## Changed Files

- `secmind/backend/tools/mcp/config.py`
- `secmind/backend/tools/mcp/transports.py`
- `secmind/backend/tools/mcp/manager.py`
- `secmind/backend/tools/mcp/gateway.py`
- `secmind/backend/tools/mcp/__init__.py`
- `secmind/backend/tests/fixtures/mcp_test_server.py`
- `secmind/backend/tests/test_mcp_runtime.py`
- `docs/handoffs/native-mcp.md`

No integration-owned schema, configuration, startup, GraphQL, or dependency file is changed.

## Exported Interfaces

Import the public API from `tools.mcp`:

- `load_mcp_server_configs(path)` loads canonical `MCPServerConfig` records.
- `MCPManager` owns server connections, capability discovery, refresh, and calls.
- `UnifiedToolGateway` routes canonical `UnifiedToolInvocation` objects to native or MCP tools.
- `MCPConfigError`, `MCPConnectionError`, `MCPManagerError`, and
  `MCPToolNotFoundError` are the public error types.

The manager supports stdio, Streamable HTTP, and legacy SSE transports. It discovers paginated
Tools, Resources, and Prompts, exposes all connected capabilities by default, and does not use an
MCP feature flag.

## Canonical JSON Configuration

`SECMIND_MCP_CONFIG_FILE` should point to a UTF-8 JSON file. The root can be the server array
itself or an object containing a `servers` array.

```json
{
  "servers": [
    {
      "server_id": "local-tools",
      "name": "Local Tools",
      "transport": "stdio",
      "command": "python",
      "args": ["C:/path/to/server.py"],
      "cwd": "C:/path/to",
      "env_refs": {
        "UPSTREAM_API_KEY": "SECMIND_UPSTREAM_API_KEY"
      }
    },
    {
      "server_id": "remote-tools",
      "name": "Remote Tools",
      "transport": "streamable_http",
      "url": "https://mcp.example.test/mcp",
      "header_refs": {
        "Authorization": "SECMIND_MCP_AUTHORIZATION"
      },
      "connect_timeout_seconds": 30,
      "call_timeout_seconds": 300
    },
    {
      "server_id": "legacy-sse",
      "name": "Legacy SSE",
      "transport": "sse",
      "url": "https://mcp.example.test/sse"
    }
  ]
}
```

`env_refs` and `header_refs` map the child environment variable or HTTP header name to the name
of a process environment variable. Resolved secret values remain in memory and are not copied
into `MCPServerConfig` or snapshots.

## Integration Wiring Required

The integration branch owns these changes:

1. Add the frozen MCP settings to `Settings`: config path, connect timeout, call timeout, and
   capability refresh interval. Do not add `MCP_ENABLED`; an absent or empty file means zero
   configured servers.
2. In `build_services`, load the configs, construct one `MCPManager`, then construct one
   `UnifiedToolGateway` around it. Register existing native tools with the gateway.
3. Add the manager and gateway to `AppServices`. Call `mcp_manager.startup()` during service
   startup and `mcp_manager.shutdown()` before database/event infrastructure is disposed.
4. Inject a publisher that persists run-scoped `mcp.call_*` events to the common runtime ledger
   and then publishes the persisted event through `RuntimeEventHub`. Route connection and
   capability lifecycle events through the integration branch's application-scoped event path.
5. Make the Agent runtime and GraphQL resolvers consume the gateway and manager interfaces;
   neither consumer should create its own MCP sessions.

Minimal construction shape:

```python
configs = load_mcp_server_configs(settings.mcp_config_file)
mcp_manager = MCPManager(
    configs,
    connect_timeout_seconds=settings.mcp_connect_timeout_seconds,
    call_timeout_seconds=settings.mcp_call_timeout_seconds,
    refresh_interval_seconds=settings.mcp_refresh_interval_seconds,
    publisher=publish_mcp_event,
)
tool_gateway = UnifiedToolGateway(mcp_manager)
```

The publisher must redact or reject sensitive values beyond the manager's built-in argument
redaction if an integration adapter enriches payloads. Never log resolved environment variables
or request headers.

## Dependencies And Migrations

- New dependencies: none. The baseline already declares `mcp>=1.12,<2` and `httpx>=0.27.0`.
- Database migrations: none.

## Tests And Results

The focused integration tests use a real MCP fixture server and cover:

- all three transports;
- initialization, pagination-aware discovery, Tool invocation, Resource reads, and Prompt reads;
- configuration and environment/header reference resolution;
- protocol failures, timeouts, caller cancellation, failed server visibility, and shutdown;
- native/MCP routing through `UnifiedToolGateway`.

Final verification:

```text
python -m ruff check .
All checks passed!

python -m pytest -q
88 passed, 1 skipped, 1 warning in 51.53s

python -m pytest -q tests/test_mcp_runtime.py
17 passed, 1 warning in 28.14s

git diff --check
passed
```

The warning is the existing Starlette deprecation warning for the installed `httpx` compatibility
shim; it is unrelated to MCP behavior.

## Unresolved Risks

- The integration branch must define persistence semantics for application-scoped connection and
  capability events because they do not naturally have a run ID.
- MCP progress notifications are handled by the SDK but are not surfaced as a separate canonical
  event because the frozen runtime event contract has no `mcp.call_progress` value.
- HTTP authentication refresh beyond environment-backed static headers is not implemented; a
  future credential provider should remain injected and must not persist resolved secrets.
