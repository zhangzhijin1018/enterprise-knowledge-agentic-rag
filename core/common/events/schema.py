"""
Agent 事件数据模型

统一规范所有 Agent 事件的数据格式，便于：
1. 跨 Agent 事件追踪
2. Redis Streams 序列化/反序列化
3. SSE 前端解析

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


# =============================================================================
# 事件类型枚举
# =============================================================================

class EventType(str, Enum):
    """事件类型枚举。

    定义所有 Agent 可能产生的事件类型。
    """

    # 连接状态
    CONNECTED = "connected"              # 连接成功
    HEARTBEAT = "heartbeat"              # 心跳保活

    # 任务状态
    STARTED = "started"                  # 任务开始
    PROGRESS = "progress"                # 进度更新
    STAGE_STARTED = "stage_started"      # 阶段开始
    STAGE_COMPLETED = "stage_completed"   # 阶段完成
    COMPLETED = "completed"              # 任务完成
    ERROR = "error"                      # 任务失败

    # 业务事件
    SUMMARY_DONE = "summary_done"        # 摘要生成完成（Analytics）
    INSIGHT_DONE = "insight_done"        # 洞察生成完成（Analytics）
    CHART_DONE = "chart_done"            # 图表生成完成（Analytics）
    REPORT_DONE = "report_done"          # 报告生成完成（Analytics）
    QUERY_DONE = "query_done"            # SQL 查询完成（RAG）
    RETRIEVAL_DONE = "retrieval_done"    # 检索完成（RAG）


class EventStatus(str, Enum):
    """任务状态枚举。"""

    PENDING = "pending"      # 等待中
    RUNNING = "running"      # 执行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"        # 失败
    CANCELLED = "cancelled"  # 已取消


class EventStage(str, Enum):
    """标准阶段枚举。

    定义所有 Agent 可能执行的阶段。
    """

    # 通用阶段
    INTENT_PARSE = "intent_parse"        # 意图解析
    ROUTING = "routing"                  # 路由决策
    AGENT_SELECT = "agent_select"         # Agent 选择

    # Analytics Agent 阶段
    SQL_BUILD = "sql_build"               # 构建 SQL
    SQL_EXECUTE = "sql_execute"           # 执行查询
    DATA_ANALYZE = "data_analyze"         # 数据分析
    SUMMARY_GENERATE = "summary_generate"  # 生成摘要
    INSIGHT_GENERATE = "insight_generate" # 生成洞察
    CHART_GENERATE = "chart_generate"     # 生成图表
    REPORT_GENERATE = "report_generate"   # 生成报告

    # RAG Agent 阶段
    QUERY_REWRITE = "query_rewrite"      # 查询改写
    RETRIEVAL = "retrieval"               # 检索
    RERANK = "rerank"                     # 重排序
    CONTEXT_BUILD = "context_build"       # 构建上下文
    ANSWER_GENERATE = "answer_generate"   # 生成答案

    # Contract Agent 阶段
    CONTRACT_PARSE = "contract_parse"    # 合同解析
    CLAUSE_EXTRACT = "clause_extract"     # 条款抽取
    RISK_ANALYZE = "risk_analyze"        # 风险分析

    # Policy Agent 阶段
    POLICY_RETRIEVAL = "policy_retrieval" # 制度检索
    POLICY_MATCH = "policy_match"         # 制度匹配


# =============================================================================
# 事件数据模型
# =============================================================================

@dataclass
class AgentEvent:
    """
    Agent 事件统一数据模型。

    字段说明：
    - run_id: 任务唯一标识，用于 SSE 订阅
    - agent_name: 产生事件的 Agent 名称
    - event_type: 事件类型
    - status: 当前任务状态
    - stage: 当前执行阶段
    - progress: 进度百分比 0-100
    - message: 人类可读的消息
    - data: 业务数据（SQL、结果、图表等）
    - error: 错误信息（仅 error 时有值）
    - timestamp: 事件时间戳（毫秒）

    使用示例：
    ```python
    event = AgentEvent(
        run_id="run_abc123",
        agent_name="analytics-agent",
        event_type=EventType.PROGRESS,
        status=EventStatus.RUNNING,
        stage=EventStage.SQL_BUILD,
        progress=25,
        message="正在构建 SQL...",
    )
    ```
    """

    # 核心标识
    run_id: str                           # 任务运行 ID
    agent_name: str                       # Agent 名称
    event_type: str                       # 事件类型

    # 状态信息
    status: str = EventStatus.RUNNING.value  # 任务状态
    stage: Optional[str] = None           # 当前阶段
    progress: int = 0                    # 进度 0-100

    # 消息内容
    message: Optional[str] = None         # 人类可读消息

    # 业务数据（Agent 根据类型填充不同数据）
    data: dict[str, Any] = field(default_factory=dict)

    # 错误信息（仅 error 事件时填充）
    error: Optional[dict[str, Any]] = None

    # 元数据
    trace_id: Optional[str] = None        # 追踪 ID
    conversation_id: Optional[str] = None # 会话 ID
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))  # 毫秒时间戳

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。

        Returns:
            字典格式的事件数据
        """
        result = {
            "run_id": self.run_id,
            "agent_name": self.agent_name,
            "event_type": self.event_type,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "message": self.message,
            "data": self.data,
            "trace_id": self.trace_id,
            "conversation_id": self.conversation_id,
            "timestamp": self.timestamp,
        }

        if self.error:
            result["error"] = self.error

        return result

    def to_json(self) -> str:
        """序列化为 JSON 字符串。

        Returns:
            JSON 格式的事件数据
        """
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentEvent":
        """从字典创建实例。

        Args:
            data: 事件数据字典

        Returns:
            AgentEvent 实例
        """
        return cls(
            run_id=data.get("run_id", ""),
            agent_name=data.get("agent_name", ""),
            event_type=data.get("event_type", EventType.PROGRESS.value),
            status=data.get("status", EventStatus.RUNNING.value),
            stage=data.get("stage"),
            progress=data.get("progress", 0),
            message=data.get("message"),
            data=data.get("data", {}),
            error=data.get("error"),
            trace_id=data.get("trace_id"),
            conversation_id=data.get("conversation_id"),
            timestamp=data.get("timestamp", int(time.time() * 1000)),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "AgentEvent":
        """从 JSON 字符串创建实例。

        Args:
            json_str: JSON 格式的事件数据

        Returns:
            AgentEvent 实例
        """
        data = json.loads(json_str)
        return cls.from_dict(data)


# =============================================================================
# 事件工厂函数
# =============================================================================

def create_progress_event(
    run_id: str,
    agent_name: str,
    stage: str,
    progress: int,
    message: str,
    *,
    status: str = EventStatus.RUNNING.value,
    trace_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    **extra_data: Any,
) -> AgentEvent:
    """创建进度事件。

    Args:
        run_id: 任务运行 ID
        agent_name: Agent 名称
        stage: 当前阶段
        progress: 进度百分比
        message: 消息
        status: 任务状态
        trace_id: 追踪 ID
        conversation_id: 会话 ID
        **extra_data: 额外数据

    Returns:
        进度事件
    """
    return AgentEvent(
        run_id=run_id,
        agent_name=agent_name,
        event_type=EventType.PROGRESS.value,
        status=status,
        stage=stage,
        progress=progress,
        message=message,
        trace_id=trace_id,
        conversation_id=conversation_id,
        data=extra_data,
    )


def create_stage_event(
    run_id: str,
    agent_name: str,
    stage: str,
    event_type: str,
    message: str,
    *,
    progress: int = 0,
    trace_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    **extra_data: Any,
) -> AgentEvent:
    """创建阶段事件。

    Args:
        run_id: 任务运行 ID
        agent_name: Agent 名称
        stage: 阶段名称
        event_type: 事件类型 (stage_started / stage_completed)
        message: 消息
        progress: 进度百分比
        trace_id: 追踪 ID
        conversation_id: 会话 ID
        **extra_data: 额外数据

    Returns:
        阶段事件
    """
    return AgentEvent(
        run_id=run_id,
        agent_name=agent_name,
        event_type=event_type,
        status=EventStatus.RUNNING.value,
        stage=stage,
        progress=progress,
        message=message,
        trace_id=trace_id,
        conversation_id=conversation_id,
        data=extra_data,
    )


def create_complete_event(
    run_id: str,
    agent_name: str,
    message: str = "任务完成",
    *,
    trace_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    **result_data: Any,
) -> AgentEvent:
    """创建完成事件。

    Args:
        run_id: 任务运行 ID
        agent_name: Agent 名称
        message: 消息
        trace_id: 追踪 ID
        conversation_id: 会话 ID
        **result_data: 结果数据

    Returns:
        完成事件
    """
    return AgentEvent(
        run_id=run_id,
        agent_name=agent_name,
        event_type=EventType.COMPLETED.value,
        status=EventStatus.COMPLETED.value,
        progress=100,
        message=message,
        trace_id=trace_id,
        conversation_id=conversation_id,
        data=result_data,
    )


def create_error_event(
    run_id: str,
    agent_name: str,
    error_code: str,
    error_message: str,
    *,
    trace_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> AgentEvent:
    """创建错误事件。

    Args:
        run_id: 任务运行 ID
        agent_name: Agent 名称
        error_code: 错误码
        error_message: 错误信息
        trace_id: 追踪 ID
        conversation_id: 会话 ID

    Returns:
        错误事件
    """
    return AgentEvent(
        run_id=run_id,
        agent_name=agent_name,
        event_type=EventType.ERROR.value,
        status=EventStatus.FAILED.value,
        progress=0,
        message=error_message,
        error={
            "error_code": error_code,
            "message": error_message,
        },
        trace_id=trace_id,
        conversation_id=conversation_id,
    )


def create_heartbeat_event(run_id: str, agent_name: str) -> AgentEvent:
    """创建心跳事件。

    Args:
        run_id: 任务运行 ID
        agent_name: Agent 名称

    Returns:
        心跳事件
    """
    return AgentEvent(
        run_id=run_id,
        agent_name=agent_name,
        event_type=EventType.HEARTBEAT.value,
        status=EventStatus.RUNNING.value,
        progress=0,
        message="心跳",
        timestamp=int(time.time() * 1000),
    )


# =============================================================================
# Analytics 专用事件工厂
# =============================================================================

def create_analytics_summary_event(
    run_id: str,
    summary: dict[str, Any],
    *,
    trace_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> AgentEvent:
    """创建 Analytics 摘要完成事件。

    Args:
        run_id: 任务运行 ID
        summary: 摘要数据
        trace_id: 追踪 ID
        conversation_id: 会话 ID

    Returns:
        摘要完成事件
    """
    return AgentEvent(
        run_id=run_id,
        agent_name="analytics-agent",
        event_type=EventType.SUMMARY_DONE.value,
        status=EventStatus.RUNNING.value,
        stage=EventStage.SUMMARY_GENERATE.value,
        progress=25,
        message="经营分析摘要生成完成",
        trace_id=trace_id,
        conversation_id=conversation_id,
        data={"summary": summary},
    )


def create_analytics_insight_event(
    run_id: str,
    insights: dict[str, Any],
    *,
    trace_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> AgentEvent:
    """创建 Analytics 洞察完成事件。

    Args:
        run_id: 任务运行 ID
        insights: 洞察数据
        trace_id: 追踪 ID
        conversation_id: 会话 ID

    Returns:
        洞察完成事件
    """
    return AgentEvent(
        run_id=run_id,
        agent_name="analytics-agent",
        event_type=EventType.INSIGHT_DONE.value,
        status=EventStatus.RUNNING.value,
        stage=EventStage.INSIGHT_GENERATE.value,
        progress=50,
        message="经营洞察生成完成",
        trace_id=trace_id,
        conversation_id=conversation_id,
        data={"insights": insights},
    )


def create_analytics_chart_event(
    run_id: str,
    chart: dict[str, Any],
    *,
    trace_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> AgentEvent:
    """创建 Analytics 图表完成事件。

    Args:
        run_id: 任务运行 ID
        chart: 图表数据
        trace_id: 追踪 ID
        conversation_id: 会话 ID

    Returns:
        图表完成事件
    """
    return AgentEvent(
        run_id=run_id,
        agent_name="analytics-agent",
        event_type=EventType.CHART_DONE.value,
        status=EventStatus.RUNNING.value,
        stage=EventStage.CHART_GENERATE.value,
        progress=75,
        message="图表生成完成",
        trace_id=trace_id,
        conversation_id=conversation_id,
        data={"chart": chart},
    )


def create_analytics_report_event(
    run_id: str,
    report: dict[str, Any],
    *,
    trace_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> AgentEvent:
    """创建 Analytics 报告完成事件。

    Args:
        run_id: 任务运行 ID
        report: 报告数据
        trace_id: 追踪 ID
        conversation_id: 会话 ID

    Returns:
        报告完成事件
    """
    return AgentEvent(
        run_id=run_id,
        agent_name="analytics-agent",
        event_type=EventType.REPORT_DONE.value,
        status=EventStatus.COMPLETED.value,
        stage=EventStage.REPORT_GENERATE.value,
        progress=100,
        message="经营分析报告生成完成",
        trace_id=trace_id,
        conversation_id=conversation_id,
        data={"report": report},
    )
