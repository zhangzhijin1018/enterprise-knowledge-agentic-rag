"""内存版事件总线。

当前阶段优先保证：
1. publish / consume 契约先跑通；
2. Supervisor / Workflow / Gateway 不依赖外部 Redis 环境也能联调；
3. 后续切 Redis Streams 时，上层不需要改接口。
"""

from __future__ import annotations

from collections import defaultdict
from uuid import uuid4

from core.runtime.events.event_bus import EventBus, EventMessage, _utcnow


class InMemoryEventBus(EventBus):
    """内存事件总线实现。"""

    def __init__(self) -> None:
        self._streams: dict[str, list[EventMessage]] = defaultdict(list)

    def publish(
        self,
        *,
        stream: str,
        event_type: str,
        payload: dict,
        trace_id: str | None = None,
        run_id: str | None = None,
    ) -> EventMessage:
        """发布事件到内存流。"""

        message = EventMessage(
            event_id=f"evt_{uuid4().hex[:12]}",
            stream=stream,
            event_type=event_type,
            payload=payload,
            trace_id=trace_id,
            run_id=run_id,
            created_at=_utcnow(),
        )
        self._streams[stream].append(message)
        return message

    def consume(self, *, stream: str, max_count: int = 10) -> list[EventMessage]:
        """按先进先出方式消费事件。"""

        items = self._streams.get(stream, [])
        consumed = items[:max_count]
        self._streams[stream] = items[max_count:]
        return consumed
