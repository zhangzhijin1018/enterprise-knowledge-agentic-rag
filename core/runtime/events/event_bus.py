"""事件总线抽象。

为什么这里要抽象 Event Bus：
1. Supervisor 与 A2A Gateway 后续会逐步演进到跨进程、跨实例、跨专家协作；
2. 事件流适合承载“任务投递、状态变化、异步通知”等高频轻事件；
3. 但事件总线不是权威状态存储，task_run / review / audit / clarification
   仍然以 PostgreSQL 为准。

这一层的职责非常克制：
- 定义 publish / consume 契约；
- 允许先用 in-memory 跑通；
- 为 Redis Streams-ready 的后续接入保留统一接口。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _utcnow() -> datetime:
    """返回当前 UTC 时间。"""

    return datetime.now(timezone.utc)


@dataclass(slots=True)
class EventMessage:
    """事件消息对象。"""

    event_id: str
    stream: str
    event_type: str
    payload: dict[str, Any]
    trace_id: str | None
    run_id: str | None
    created_at: datetime


class EventBus(ABC):
    """事件总线最小抽象。"""

    @abstractmethod
    def publish(
        self,
        *,
        stream: str,
        event_type: str,
        payload: dict[str, Any],
        trace_id: str | None = None,
        run_id: str | None = None,
    ) -> EventMessage:
        """发布事件。"""

    @abstractmethod
    def consume(self, *, stream: str, max_count: int = 10) -> list[EventMessage]:
        """消费事件。"""
