from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable

from agent_runtime.domain.models import RuntimeEvent


class EventStreamHub:
    def __init__(
        self,
        load_persisted_events: Callable[[str], Awaitable[list[RuntimeEvent]]],
    ) -> None:
        self._load_persisted_events = load_persisted_events
        self._queues: dict[str, list[asyncio.Queue[RuntimeEvent]]] = defaultdict(list)

    async def publish(self, event: RuntimeEvent) -> None:
        for queue in list(self._queues.get(event.run_id, [])):
            await queue.put(event)

    async def stream(self, run_id: str) -> AsyncIterator[RuntimeEvent]:
        queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue()
        self._queues[run_id].append(queue)
        try:
            persisted_events = await self._load_persisted_events(run_id)
            replayed_event_ids = {event.event_id for event in persisted_events}
            for event in persisted_events:
                yield event

            while True:
                event = await queue.get()
                if event.event_id in replayed_event_ids:
                    continue
                yield event
        finally:
            self._queues[run_id].remove(queue)
