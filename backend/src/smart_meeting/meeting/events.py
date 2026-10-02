import asyncio
import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class EventHub:
    """Fan-out of meeting events to WebSocket subscribers."""

    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def subscribe(self, meeting_id: int) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._subscribers[meeting_id].add(queue)
        return queue

    def unsubscribe(self, meeting_id: int, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers[meeting_id].discard(queue)
        if not self._subscribers[meeting_id]:
            del self._subscribers[meeting_id]

    def publish(self, meeting_id: int, event: dict[str, Any]) -> None:
        for queue in self._subscribers.get(meeting_id, ()):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Dropping event for a slow subscriber of meeting %s", meeting_id)
