# Agent Graph Control Handoff

Date: 2026-07-20

## Outcome

Agent Graph create/message/wait/stop is implemented as an additive control plane over the existing
15-role native collaboration model. No role, delegation depth rule, parent/child relationship,
Prompt action format, or MCP/tool contract was replaced.

## Runtime APIs

- `AgentDispatcher.start_root`: asynchronous root creation.
- `AgentDispatcher.start_delegation`: asynchronous first-class child delegation.
- `AgentDispatcher.send_message`: durable same-run/same-flow Agent communication.
- `AgentDispatcher.wait_for_message`: cooperative Agent inbox wait.
- `AgentDispatcher.wait_for_agent`: terminal-state wait without changing execution state.
- `AgentDispatcher.stop_agent`: cooperative downward subtree stop.

The original blocking `dispatch_root` and `delegate_from` APIs remain compatible.

## GraphQL APIs

- `createAgent`
- `delegateAgent` (now returns after durable delegation creation)
- `sendAgentMessage`
- `waitAgent`
- `stopAgent`

Queries `agentInstances`, `agentDelegations`, and `agentMessages` remain the graph snapshot API.

The Workbench Agent Network heading now exposes a `控制` modal with Create, Message, Wait, and
Stop tabs. Cancelled Agents are rendered as `已停止`, not as failures.

## Persistence and audit

- Agent status updates persist to `agent_instances`.
- Public messages persist to `agent_messages` and the receiver message chain.
- `agent.waiting`, `agent.resumed`, `agent.stop_requested`, and `agent.cancelled` are emitted through
  the common EventEnvelope ledger.
- Delegate, complete, and stop actions are preceded by correlated `decision.recorded` events.
- A stop request propagates only to descendants; a child cancellation returns an `AgentResult` to
  the parent.

## Verification

- Agent Graph, native Agent, GraphQL, and contract tests: 32 passed.
- Full backend suite excluding the separately managed Prompt checksum tests: 136 passed, 1 skipped.
- Ruff: all checks passed.
- Frontend: 24 tests passed and the Vite production build completed.
- Live GraphQL smoke test at `http://127.0.0.1:8002/graphql`: create and wait completed; audit replay
  showed the correlated completion decision and action.
- Browser verification at `http://127.0.0.1:5175/workbench`: desktop and 390x844 mobile layouts
  rendered without horizontal overflow; all four control tabs were accessible.
- Integrated preview: `http://127.0.0.1:5176/workbench` targets the current backend on port 8002.

## Known boundary

The graph and audit history survive restart, but live inbox queues and Python coroutines do not.
Controlling a pre-restart active Agent requires a future dispatcher recovery coordinator backed by
the existing checkpoint subsystem. The implementation does not pretend that a stale `RUNNING` row
is still controllable.
