from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.graphql.adapters import NativeGraphQLEventAdapter
from app.services.event_stream import RuntimeEventStream
from app.services.runtime import RuntimeEventHub
from ledger.runtime_store import RuntimeLedgerStore


def build_stream(tmp_path, *, batch_size: int = 2, poll_interval: float = 0.01):
    ledger = RuntimeLedgerStore(f"sqlite:///{tmp_path / 'events.db'}")
    hub = RuntimeEventHub()
    stream = RuntimeEventStream(
        ledger,
        hub,
        batch_size=batch_size,
        poll_interval_seconds=poll_interval,
    )
    return ledger, hub, stream


async def test_stream_replays_then_delivers_live_events_without_duplicates(tmp_path) -> None:
    ledger, hub, stream = build_stream(tmp_path)
    first = ledger.append("run-1", "run.queued", {"objective": "audit"})
    second = ledger.append("run-1", "run.started", {})
    subscription = stream.subscribe("run-1", after_sequence=1)

    assert (await anext(subscription)).event_id == second.event_id

    third = ledger.append("run-1", "plan.created", {"steps": []})
    await hub.publish(third.model_dump(mode="json"))
    delivered = await asyncio.wait_for(anext(subscription), timeout=1)

    assert delivered.event_id == third.event_id
    assert [second.sequence, delivered.sequence] == [2, 3]
    assert first.sequence == 1
    await subscription.aclose()


async def test_stream_recovers_an_unnotified_append_by_polling_ledger(tmp_path) -> None:
    ledger, _hub, stream = build_stream(tmp_path, poll_interval=0.01)
    first = ledger.append("run-1", "run.queued", {})
    subscription = stream.subscribe("run-1", after_sequence=first.sequence)
    pending = asyncio.create_task(anext(subscription))
    await asyncio.sleep(0.02)

    second = ledger.append("run-1", "run.started", {})
    delivered = await asyncio.wait_for(pending, timeout=1)

    assert delivered.event_id == second.event_id
    await subscription.aclose()


async def test_hub_coalesces_wakeups_but_stream_reads_every_fact(tmp_path) -> None:
    ledger, hub, stream = build_stream(tmp_path, batch_size=3)
    initial = ledger.append("run-1", "run.queued", {})

    async with hub.subscribe("run-1") as notifications:
        appended = []
        for index in range(8):
            event = ledger.append("run-1", "step.selected", {"index": index})
            appended.append(event)
            await hub.publish(event.model_dump(mode="json"))

        assert notifications.qsize() == 1
        stats = await hub.stats()
        assert stats["coalesced_notifications"] == 7

    subscription = stream.subscribe("run-1", after_sequence=initial.sequence)
    delivered = [await asyncio.wait_for(anext(subscription), timeout=1) for _ in appended]

    assert [event.event_id for event in delivered] == [event.event_id for event in appended]
    await subscription.aclose()


async def test_global_stream_preserves_each_run_cursor(tmp_path) -> None:
    ledger, hub, stream = build_stream(tmp_path)
    run_a = ledger.append("run-a", "agent.started", {"flow_id": "flow-a"})
    run_b = ledger.append("run-b", "agent.started", {"flow_id": "flow-b"})
    subscription = stream.subscribe_all(after_sequences={"run-a": run_a.sequence})

    assert (await anext(subscription)).event_id == run_b.event_id

    next_a = ledger.append("run-a", "agent.completed", {"flow_id": "flow-a"})
    await hub.publish(next_a.model_dump(mode="json"))
    assert (await asyncio.wait_for(anext(subscription), timeout=1)).event_id == next_a.event_id
    await subscription.aclose()


async def test_graphql_adapter_uses_same_replay_and_live_stream(tmp_path) -> None:
    ledger, hub, stream = build_stream(tmp_path)
    replayed = ledger.append("run-1", "run.queued", {"objective": "audit"})
    adapter = NativeGraphQLEventAdapter(SimpleNamespace(runtime_event_stream=stream))
    subscription = adapter.subscribe(
        "runtime.event",
        run_id="run-1",
        after_sequence=0,
    )

    first = await anext(subscription)
    assert first.event_id == replayed.event_id
    assert first.sequence == 1

    live = ledger.append("run-1", "run.started", {})
    await hub.publish(live.model_dump(mode="json"))
    second = await asyncio.wait_for(anext(subscription), timeout=1)
    assert second.event_id == live.event_id
    assert second.schema_version == "1.1"
    await subscription.aclose()
