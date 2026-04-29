"""A2A 宏观调度契约模型。

为什么第一阶段先统一契约，而不是先做重型分布式实现：
1. 当前项目已经进入企业级 Agent 平台阶段，跨业务专家委托的边界必须先稳定；
2. 如果没有统一的 Task Envelope / Result Contract，后续无论走 HTTP/JSON、
   Redis Streams 还是远端 A2A Server，都会在每条链路里重复发明协议；
3. 第一阶段先把“字段、状态、链路标识”统一，后续只替换 transport，
   不需要推翻 Supervisor、业务专家和审计代码。

为什么 run_id / trace_id 必须透传：
1. run_id 是权威任务运行标识，必须贯穿宏观调度与微观执行；
2. trace_id 用于串联 Supervisor、A2A Gateway、业务专家工作流、SQL Audit、Human Review；
3. 如果跨专家委托时丢失这些标识，后续就无法做完整审计与故障排查。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """返回当前 UTC 时间。"""

    return datetime.now(timezone.utc)


class AgentCardRef(BaseModel):
    """业务专家卡片的最小引用模型。

    当前阶段不直接实现完整 Agent Registry，而是先用最小卡片描述：
    - 这个专家是谁；
    - 这个专家擅长什么；
    - 当前是本地执行，还是已经具备 A2A-ready 边界。
    """

    agent_name: str = Field(description="业务专家名称，例如 analytics_expert")
    description: str = Field(description="业务专家说明")
    capabilities: list[str] = Field(default_factory=list, description="当前专家声明的能力列表")
    execution_mode: Literal["local", "a2a_ready"] = Field(
        default="local",
        description="执行模式：local 表示当前进程内可本地执行，a2a_ready 表示已具备远程委托边界",
    )
    version: str = Field(default="v1", description="专家卡片版本")


class DelegationTarget(BaseModel):
    """Supervisor 选择出来的委托目标。"""

    task_type: str = Field(description="任务类型，例如 business_analysis")
    route_key: str = Field(description="宏观路由键，例如 analytics")
    agent_card: AgentCardRef = Field(description="目标专家卡片")
    preferred_transport: Literal["local", "http_json", "redis_stream_ready"] = Field(
        default="local",
        description="当前推荐的委托传输方式",
    )


class StatusContract(BaseModel):
    """A2A 宏观调度状态契约。"""

    status: str = Field(description="主状态，例如 pending / running / succeeded / failed")
    sub_status: str | None = Field(default=None, description="子状态，用于表达更细粒度执行阶段")
    review_status: str | None = Field(default=None, description="审核状态")
    message: str | None = Field(default=None, description="当前状态补充说明")


class TaskEnvelope(BaseModel):
    """A2A 任务投递信封。

    这是宏观调度层向本地/远程业务专家投递任务时的统一对象。
    """

    run_id: str = Field(description="任务运行 ID，必须透传到业务专家内部工作流")
    trace_id: str = Field(description="链路 Trace ID，必须透传到所有审计链路")
    parent_task_id: str | None = Field(default=None, description="父任务 ID，用于宏观委托关系追踪")
    task_type: str = Field(description="任务类型，例如 business_analysis")
    source_agent: str = Field(description="发起委托的上游 Agent / Supervisor 名称")
    target_agent: str = Field(description="接收任务的目标业务专家名称")
    input_payload: dict[str, Any] = Field(default_factory=dict, description="标准化输入载荷")
    status: str = Field(default="pending", description="当前任务状态")
    created_at: datetime = Field(default_factory=_utcnow, description="任务创建时间")


class ResultContract(BaseModel):
    """A2A 统一结果契约。

    无论目标专家是本地 workflow 还是后续远程 A2A 服务，
    Supervisor 最终都只接收这一种标准结果。
    """

    run_id: str = Field(description="任务运行 ID")
    trace_id: str = Field(description="链路 Trace ID")
    parent_task_id: str | None = Field(default=None, description="父任务 ID")
    task_type: str = Field(description="任务类型")
    source_agent: str = Field(description="发起方名称")
    target_agent: str = Field(description="执行方名称")
    status: StatusContract = Field(description="标准化状态对象")
    output_payload: dict[str, Any] = Field(default_factory=dict, description="业务结果载荷")
    error: dict[str, Any] | None = Field(default=None, description="标准化错误对象")
    finished_at: datetime = Field(default_factory=_utcnow, description="结果生成时间")
