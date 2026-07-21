# Runtime Event Contract Handoff

Date: 2026-07-19

## Delivered baseline

- Canonical `EventEnvelope 1.1` and `EventContext` Pydantic contracts.
- Public `DecisionRecord` with evidence, alternatives, expected result, risk, actual result, and
  reproducibility metadata.
- Frozen event vocabulary for Agent control, tool terminal states, verifier, loop guard, circuit
  breaker, Skill, Todo, Notes, and context compression.
- Typed GraphQL fields for event context, decisions, and verification verdicts.
- Alembic revision `20260719_0003` for durable event correlation fields.
- Normative ordering, terminal-state, replay, and compatibility rules in
  `docs/contracts/runtime-event-contract.md`.

## Interfaces for implementation workstreams

Import from `app.schemas.runtime`:

```python
from app.schemas.runtime import (
    DECISION_REQUIRED_EVENT_TYPES,
    TOOL_TERMINAL_EVENT_TYPES,
    DecisionRecord,
    EventContext,
    EventEnvelope,
    RuntimeEventType,
    VerificationVerdict,
)
```

Event producers append correlation metadata through the existing ledger:

```python
ledger.append(
    run_id,
    RuntimeEventType.TOOL_STARTED,
    payload,
    actor="tool_gateway",
    context=EventContext(
        flow_id=flow_id,
        correlation_id=operation_id,
        decision_id=decision_id,
        agent_instance_id=agent_instance_id,
        tool_invocation_id=invocation_id,
    ),
)
```

The Event Projector and Live Feed consume `RuntimeEvent` from the frozen GraphQL query and
subscription. They must not define a second public event DTO.

## Deferred implementation, not deferred design

The following behaviors are specified but remain owned by their feature workstreams:

- emitting `decision.recorded` before every controlled action;
- completing every tool lifecycle with exactly one terminal event;
- Event Projector and Live Feed rendering;
- Agent message/wait/stop controls;
- circuit breaker, loop detector, and Scope Guard enforcement;
- independent verifier execution;
- Skill, Todo, Notes, and structured context compression.

## Verification

- Focused contract/migration suite: 13 passed.
- Backend suite excluding the separately managed Prompt candidate checksum test: 116 passed,
  1 skipped.
- Ruff: all checks passed.
- Full suite has five existing Prompt candidate checksum failures because candidate file hashes do
  not match `prompts/candidates/zh-CN/manifest.json`; this handoff does not alter those files.
