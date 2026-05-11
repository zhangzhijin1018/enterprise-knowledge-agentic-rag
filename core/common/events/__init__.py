"""
分布式 Agent 事件总线 - 统一事件 Schema

基于 Redis Streams 的分布式消息总线，用于：
1. 各 Agent 推送进度事件到 Redis
2. Supervisor 统一消费事件并通过 SSE 推送给前端
3. 支持多 Agent 并行推送进度

核心设计：
- 统一事件格式：所有 Agent 使用相同的事件 Schema
- Redis Streams：跨进程、持久化、支持断线重连
- SSE 推送：前端订阅 run_id 对应的进度流

数据流：
  ┌─────────────┐     XADD      ┌─────────────┐     XREAD     ┌─────────────┐
  │ Analytics   │──────────────►│   Redis     │──────────────►│ Supervisor  │
  │   Agent     │               │   Streams   │               │   SSE       │
  └─────────────┘               └─────────────┘               └─────────────┘
           │                                                                   │
           │                                                                   ▼
  ┌─────────────┐                                                     ┌─────────────┐
  │ RAG Agent   │                                                     │   前端      │
  └─────────────┘                                                     └─────────────┘

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

from core.common.events.schema import (
    AgentEvent,
    EventType,
    EventStatus,
    EventStage,
    create_progress_event,
    create_complete_event,
    create_error_event,
    create_analytics_summary_event,
    create_analytics_insight_event,
    create_analytics_chart_event,
    create_analytics_report_event,
)

from core.common.events.producer import AgentEventProducer, get_event_producer
from core.common.events.consumer import AgentEventConsumer, sse_event_stream

__all__ = [
    # Schema
    "AgentEvent",
    "EventType",
    "EventStatus",
    "EventStage",
    "create_progress_event",
    "create_complete_event",
    "create_error_event",
    "create_analytics_summary_event",
    "create_analytics_insight_event",
    "create_analytics_chart_event",
    "create_analytics_report_event",
    # Producer
    "AgentEventProducer",
    "get_event_producer",
    # Consumer
    "AgentEventConsumer",
    "sse_event_stream",
]
