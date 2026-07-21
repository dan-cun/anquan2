# Runtime Event Stream Handoff

Date: 2026-07-20

## Delivered

- `RuntimeEventStream`: gap-free replay/live delivery from the append-only runtime ledger.
- `RuntimeEventHub`: coalesced wake notifications, global/run subscriptions, and stream metrics.
- GraphQL `runtimeEventAdded` now consumes the common stream without a replay-to-live race.
- Typed GraphQL events use the common global stream rather than scanning all runs every 200 ms.
- `/api/v1/runs/{run_id}/events` uses the same cursor stream and validates negative cursors.
- `/ws/flows/{flow_id}` mirrors runtime events while LangGraph is running, then drains the final
  cursor before terminal messages.
- `/health` exposes event stream subscriber, notification, delivery, and recovery-poll counters.

## Delivery semantics

- Delivery order is `run_id + sequence`.
- Delivery is at-least-once across transport reconnects; clients deduplicate by `event_id`.
- One active stream instance does not emit duplicate Ledger rows for a cursor.
- Notifications may be coalesced, but committed Ledger events are never dropped.
- `after_sequence` is the last event acknowledged by the client, not the next desired sequence.

## Configuration

- `SECMIND_EVENT_STREAM_BATCH_SIZE`, default `500`.
- `SECMIND_EVENT_STREAM_POLL_INTERVAL_SECONDS`, default `1.0` second.

## Verification

- Five focused stream tests cover replay/live handoff, lost-notification recovery, slow-consumer
  notification coalescing, independent multi-run cursors, and the GraphQL adapter path.
- Runtime WebSocket test verifies ordered `EventEnvelope 1.1` replay and live delivery.
- Flow WebSocket test verifies `runtime.run.queued` arrives before the first completed-node status.
- Full backend suite excluding the separately managed Prompt candidate checksum test:
  136 passed, 1 skipped.
- Full frontend suite: 22 passed.
- Ruff: all checks passed.
