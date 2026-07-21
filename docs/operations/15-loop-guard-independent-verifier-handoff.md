# Loop Guard and Independent Verifier Handoff

Date: 2026-07-20

## Delivered behavior

- Native Agent loops fingerprint canonical tool calls, delegations, and normalized results.
- The guard detects repeated calls, repeated results, and alternating no-progress cycles.
- New Evidence, Finding, or Artifact references reset the current progress epoch.
- A detected loop is returned to the model as a public structured strategy-change instruction.
- Switching tool, arguments, evidence source, or delegation emits `strategy.changed`.
- Repeatedly ignoring interventions terminates the Agent with `AGENT_LOOP_DETECTED`.
- The independent verifier re-executes the target probe through the unified Native/MCP gateway,
  then executes a baseline and optional negative control using fresh invocation identifiers.
- Verification uses typed predicates and emits only `confirmed`, `rejected`, or `inconclusive`.
- The verifier is registered as the native `native:independent_verify` tool.

## Loop Guard defaults

| Setting | Default |
| --- | --- |
| repeated call threshold | 3 |
| repeated result threshold | 3 |
| no-progress threshold | 4 |
| allowed interventions before terminal failure | 2 |

`LoopGuardConfig` can be supplied to `build_native_agent_registry`. Detection uses SHA-256 over
canonical structured actions/results; invocation IDs, timestamps, and durations do not affect
result equality. Sensitive values are redacted before fingerprint material is canonicalized.

The model-visible intervention contains no private reasoning:

```json
{
  "loop_guard": "switch_required",
  "reason": "repeated_result",
  "blocked_action_fingerprint": "...",
  "required_change": "选择不同工具、参数、证据来源或委派策略；不要再次提交相同动作。",
  "terminal": false
}
```

## Independent verification request

The native verifier tool injects `run_id`, `flow_id`, and `verifier_agent_instance_id` from the
calling Agent. Arguments provide:

- `finding_id`, `claim`, `subject_agent_instance_id`, and original `evidence_ids`;
- `reproduction`, `baseline`, and optional `negative_control` probes;
- `confirm_when` and optional `reject_when` predicates;
- declared `scope` applied to every probe by the unified tool gateway.

All probes must use the same tool. Baseline arguments must differ from reproduction arguments, and
the verifier Agent must differ from the subject Agent. The independent-verifier tool cannot select
itself as its reproduction tool.

Predicates use RFC 6901 JSON Pointer paths into `UnifiedToolResult` and the operators
`exists/equals/not_equals/contains/truthy`.

Example:

```json
{
  "confirm_when": {
    "pointer": "/data/vulnerable",
    "operator": "equals",
    "expected": true
  },
  "reject_when": {
    "pointer": "/data/state",
    "operator": "equals",
    "expected": "safe"
  }
}
```

## Verdict rules

- `confirmed`: source Evidence belongs to the Finding, every probe completed, the confirmation
  predicate matches reproduction, and it does not match baseline/negative control.
- `rejected`: the same validity and control checks pass, and an explicit rejection predicate
  matches reproduction. A `tool-call:{invocation_id}` counterevidence reference is recorded.
- `inconclusive`: missing Evidence, failed probes, non-discriminating controls, conflicting
  predicates, or non-reproduction without explicit counterevidence.

Failure to reproduce alone is never `rejected`.

## Audit events

- `loop.detected`: reason, action/result fingerprints, counts, intervention, and required change.
- `strategy.changed`: previous and replacement action fingerprints linked by `detection_id`.
- `verification.started`: Finding, Evidence, tool, and control-plan metadata.
- `verification.completed`: complete typed result with top-level `verdict`, Evidence, limitations,
  probe fingerprints, and confidence.

Verifier probes also retain the normal `decision.recorded -> tool.started -> terminal` lifecycle.

## Implementation surface

- `secmind/backend/agents/loop_guard.py`
- `secmind/backend/agents/verifier.py`
- `secmind/backend/agents/native.py`
- `secmind/backend/agents/dispatcher.py`
- `secmind/backend/agents/registry.py`
- `secmind/backend/app/services/context.py`
- `secmind/backend/tests/test_loop_guard_verifier.py`

The legacy LangGraph verifier remains a compatibility evidence-reference check. New native Agent
workflows use `IndependentVerifier`; legacy results must not be interpreted as independently
reproduced verdicts.
