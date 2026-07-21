from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping

from app.schemas.runtime import LedgerEvent
from app.services.runtime import RuntimeEventHub
from ledger.runtime_store import RuntimeLedgerStore


class RuntimeEventStream:
    """Gap-free replay/live stream backed by the append-only runtime ledger.

    Hub notifications only wake readers. Every delivered event is read from the ledger, so
    notification coalescing, reconnects, and slow consumers cannot lose audit facts.
    """

    def __init__(
        self,
        ledger: RuntimeLedgerStore,
        hub: RuntimeEventHub,
        *,
        batch_size: int = 500,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self.ledger = ledger
        self.hub = hub
        self.batch_size = batch_size
        self.poll_interval_seconds = poll_interval_seconds
        self._delivered = 0
        self._notifications = 0
        self._poll_timeouts = 0

    async def subscribe(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
    ) -> AsyncIterator[LedgerEvent]:
        if after_sequence < 0:
            raise ValueError("after_sequence must not be negative")
        cursor = after_sequence

        # Subscribe before the first replay query. An append racing with that query either appears
        # in the query or leaves a wake signal, and the periodic poll is the final safety net.
        async with self.hub.subscribe(run_id) as notifications:
            while True:
                events = await asyncio.to_thread(
                    self.ledger.events,
                    run_id,
                    cursor,
                    self.batch_size,
                )
                if events:
                    for event in events:
                        if event.sequence <= cursor:
                            continue
                        cursor = event.sequence
                        self._delivered += 1
                        yield event
                    continue
                await self._wait_for_notification(notifications)

    async def subscribe_all(
        self,
        *,
        after_sequences: Mapping[str, int] | None = None,
    ) -> AsyncIterator[LedgerEvent]:
        cursors = dict(after_sequences or {})
        if any(sequence < 0 for sequence in cursors.values()):
            raise ValueError("after_sequences must not contain negative values")

        async with self.hub.subscribe(None) as notifications:
            while True:
                delivered = False
                run_ids = await asyncio.to_thread(self.ledger.run_ids)
                for run_id in run_ids:
                    while True:
                        events = await asyncio.to_thread(
                            self.ledger.events,
                            run_id,
                            cursors.get(run_id, 0),
                            self.batch_size,
                        )
                        if not events:
                            break
                        for event in events:
                            cursor = cursors.get(run_id, 0)
                            if event.sequence <= cursor:
                                continue
                            cursors[run_id] = event.sequence
                            delivered = True
                            self._delivered += 1
                            yield event
                        if len(events) < self.batch_size:
                            break
                if delivered:
                    continue
                await self._wait_for_notification(notifications)

    async def stats(self) -> dict[str, int | float]:
        hub_stats = await self.hub.stats()
        return {
            **hub_stats,
            "delivered": self._delivered,
            "notifications": self._notifications,
            "poll_timeouts": self._poll_timeouts,
            "batch_size": self.batch_size,
            "poll_interval_seconds": self.poll_interval_seconds,
        }

    async def _wait_for_notification(self, notifications: asyncio.Queue[object]) -> None:
        try:
            await asyncio.wait_for(
                notifications.get(),
                timeout=self.poll_interval_seconds,
            )
            self._notifications += 1
        except TimeoutError:
            self._poll_timeouts += 1
