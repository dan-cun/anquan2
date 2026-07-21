# Tool Safety and Stability Handoff

Date: 2026-07-20

## Delivered behavior

- Native and MCP tools execute through the same `UnifiedToolGateway` safety boundary.
- Ordinary handler exceptions become `UnifiedToolResult(status=failed)` values visible to the
  calling Agent; caller cancellation remains a control signal and is re-raised after audit closure.
- The gateway enforces invocation/definition timeouts and returns `timed_out` results.
- Scope Guard evaluates declared path, host/CIDR, and target patterns before execution.
- Tool and MCP server circuit breakers use closed/open/half-open states, a single half-open probe,
  and concurrency-safe transitions.
- Recursive telemetry redaction covers credential-shaped keys, authorization values, inline
  secrets, private keys, URL user-info, and sensitive query strings.
- The legacy `RuntimeToolBroker` also wraps exceptions, applies manifest timeouts, redacts results,
  and uses per-tool circuit breakers.

## Scope semantics

Scope is additive configuration, not an MCP capability allow-list. An invocation without a
declared scope remains available and emits `SCOPE-OPEN`. When scope is declared, every applicable
policy must allow the target, so invocation metadata cannot widen a tool definition's fixed scope.

Definition example:

```python
annotations={
    "timeout_seconds": 120,
    "scope": {
        "workspace": "C:/authorized/project",
        "allowed_paths": ["C:/authorized/project"],
        "allowed_hosts": ["*.authorized.example", "10.10.0.0/16"],
        "allowed_targets": ["staging-*"],
    },
}
```

The same `scope` object may be supplied in `UnifiedToolInvocation.metadata`. Native workspace tools
register their controlled workspace as a definition scope automatically.

## Circuit breaker defaults

- Failure threshold: 3 consecutive failed or timed-out results.
- Reset timeout: 30 seconds.
- Native circuit key: `tool:{tool_id}`.
- MCP circuit keys: `tool:{tool_id}` and `server:{server_id}`.
- Cancelled and scope-blocked calls do not increment failure counts.
- A successful call resets all associated failure counts.

Constructors accept custom `CircuitBreakerRegistry` instances for environment-specific thresholds
without introducing a subsystem enable flag.

## Audit lifecycle

`PersistedToolGateway` now guarantees this sequence for each invocation:

1. `decision.recorded`
2. `tool.started`
3. `guardrail.evaluated` and optional `guardrail.denied`
4. zero or more `circuit.*` transitions
5. exactly one terminal event:
   `tool.completed|failed|timed_out|cancelled|blocked`

All events share `run_id`, `correlation_id`, `decision_id`, `agent_instance_id`, and
`tool_invocation_id`. Stored invocation arguments and event payloads are redacted before database
or ledger writes.

## Stable error codes

| Code | Meaning |
| --- | --- |
| `unknown_tool` | No Native or MCP definition exists |
| `scope_violation` | Declared scope rejected the target |
| `circuit_open` | Tool or MCP server circuit rejected the call |
| `tool_timeout` | Unified gateway deadline elapsed |
| `native_tool_error` | Native handler raised an ordinary exception |
| `mcp_gateway_error` | MCP dispatch failed outside its normalized result path |
| `tool_cancelled` | Persisted caller cancellation terminal result |
| `TOOL_RUNTIME_ERROR` | Legacy Runtime Tool raised an exception |
| `TOOL_CIRCUIT_OPEN` | Legacy Runtime Tool circuit is open |

## Changed implementation surface

- `secmind/backend/tools/safety/`: redaction, Scope Guard, and circuit breaker primitives.
- `secmind/backend/tools/mcp/gateway.py`: unified execution boundary.
- `secmind/backend/tools/mcp/manager.py`: MCP result/error/event redaction.
- `secmind/backend/tools/runtime.py`: legacy Native Tool boundary.
- `secmind/backend/app/services/collaboration.py`: durable decisions and terminal events.
- `secmind/backend/app/services/runtime.py`: accurate legacy terminal event mapping.
- `secmind/backend/app/services/context.py`: configured unified timeout wiring.
- `secmind/backend/tests/test_tool_safety.py`: focused safety and lifecycle tests.

## Verification

- Tool safety suite: 8 passed.
- MCP runtime suite: 17 passed.
- Agent/LangGraph/Runtime/Event integration selection: 23 passed.
- Ruff: all touched files passed before final full-suite verification.
