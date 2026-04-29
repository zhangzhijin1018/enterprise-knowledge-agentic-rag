"""Redis Streams-ready 事件总线占位实现。

这里先保留“Redis Streams-ready”边界，而不在第一轮强行做完整生产版，
原因是：
1. 本轮目标是先把混合架构的宏观调度边界定下来；
2. 当前无需为了抽象而引入完整外部依赖和部署复杂度；
3. 只要 publish / consume 契约稳定，后续切真实 Redis Streams transport
   就只需要替换此实现。
"""

from __future__ import annotations

from core.runtime.events.event_bus import EventBus, EventMessage


class RedisStreamEventBus(EventBus):
    """Redis Streams-ready 事件总线占位实现。"""

    def __init__(self, *, redis_url: str | None = None) -> None:
        self.redis_url = redis_url

    def publish(
        self,
        *,
        stream: str,
        event_type: str,
        payload: dict,
        trace_id: str | None = None,
        run_id: str | None = None,
    ) -> EventMessage:
        """发布事件占位。

        第一轮不接真实 Redis Streams，因此这里显式抛出未实现，
        避免调用方误以为已经具备生产级分布式能力。
        """

        raise NotImplementedError(
            "当前阶段仅保留 Redis Streams-ready 抽象，尚未接入真实 Redis Streams transport"
        )

    def consume(self, *, stream: str, max_count: int = 10) -> list[EventMessage]:
        """消费事件占位。"""

        raise NotImplementedError(
            "当前阶段仅保留 Redis Streams-ready 抽象，尚未接入真实 Redis Streams transport"
        )
