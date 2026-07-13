# Backend Architecture

The backend is intentionally scaffold-first:

- FastAPI exposes stable REST and WebSocket contracts.
- `MockOrchestrator` proves streaming, ledger writes, and interrupt handling.
- `JsonlLedgerStore` records append-only events with a hash chain.
- `ToolRegistry`, `LLMProvider`, `AgentPlugin`, `SandboxBackend`, and
  knowledge-store classes are extension points for future implementation.

The current `fronted` project remains a visual transition page. It can later
route users to feature pages that consume `/api/v1/*` and `/ws/flows/{flow_id}`.

