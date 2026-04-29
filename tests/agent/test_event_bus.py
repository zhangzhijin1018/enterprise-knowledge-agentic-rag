"""事件总线测试。"""

from __future__ import annotations

from core.runtime.events import InMemoryEventBus


def test_in_memory_event_bus_publish_and_consume() -> None:
    """内存事件总线应支持最小 publish / consume。"""

    bus = InMemoryEventBus()
    published = bus.publish(
        stream="supervisor.tasks",
        event_type="task_submitted",
        payload={"task_type": "business_analysis"},
        trace_id="tr_001",
        run_id="sup_001",
    )

    consumed = bus.consume(stream="supervisor.tasks", max_count=10)

    assert published.stream == "supervisor.tasks"
    assert len(consumed) == 1
    assert consumed[0].event_type == "task_submitted"
    assert consumed[0].trace_id == "tr_001"
    assert bus.consume(stream="supervisor.tasks", max_count=10) == []
