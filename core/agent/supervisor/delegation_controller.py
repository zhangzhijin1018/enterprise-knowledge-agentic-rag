"""Supervisor 委托控制器。

这层是宏观调度层的一部分，职责非常克制：
1. 维护“任务类型 -> 业务专家”的最小映射；
2. 构造跨专家统一的 TaskEnvelope；
3. 决定本地执行还是 A2A-ready 委托；
4. 不承担经营分析、合同审查等微观业务执行细节。

为什么要把这层单独拆出来：
1. Supervisor 需要保持“接收请求、路由、委托、汇总结果”的职责边界；
2. 如果把具体委托策略写死在 SupervisorService 里，后续扩到多个业务专家会很难维护；
3. DelegationController 更像“宏观派单控制器”，便于后续接 Agent Card、远程注册中心和降级策略。
"""

from __future__ import annotations

from typing import Callable
from uuid import uuid4

from core.security.auth import UserContext
from core.tools.a2a import (
    A2AGateway,
    AgentCardRef,
    DelegationTarget,
    ResultContract,
    StatusContract,
    TaskEnvelope,
)


def _generate_supervisor_run_id() -> str:
    """生成 Supervisor 宏观调度 run_id。"""

    return f"sup_{uuid4().hex[:12]}"


def _generate_trace_id() -> str:
    """生成宏观调度 trace_id。"""

    return f"tr_{uuid4().hex[:12]}"


class DelegationController:
    """宏观委托控制器。"""

    def __init__(
        self,
        *,
        a2a_gateway: A2AGateway | None = None,
        local_handlers: dict[str, Callable[[TaskEnvelope], ResultContract]] | None = None,
        delegation_targets: dict[str, DelegationTarget] | None = None,
    ) -> None:
        self.a2a_gateway = a2a_gateway or A2AGateway()
        self.local_handlers = local_handlers or {}
        self.delegation_targets = delegation_targets or self._build_default_targets()

    def _build_default_targets(self) -> dict[str, DelegationTarget]:
        """构造默认业务专家目标表。

        第一轮只把经营分析专家接成 LangGraph 微观执行样板，
        其他业务专家后续再按同样模式逐步迁移。
        """

        analytics_card = AgentCardRef(
            agent_name="analytics_expert",
            description="经营分析业务专家，内部采用 LangGraph-ready workflow 样板执行",
            capabilities=["business_analysis", "sql_guarded_query", "analytics_summary"],
            execution_mode="local",
        )
        return {
            "business_analysis": DelegationTarget(
                task_type="business_analysis",
                route_key="analytics",
                agent_card=analytics_card,
                preferred_transport="local",
            )
        }

    def resolve_target(self, task_type: str) -> DelegationTarget:
        """根据任务类型解析目标业务专家。"""

        return self.delegation_targets.get(task_type) or DelegationTarget(
            task_type=task_type,
            route_key="unsupported",
            agent_card=AgentCardRef(
                agent_name="unsupported_expert",
                description="当前阶段未注册的业务专家",
                capabilities=[],
                execution_mode="a2a_ready",
            ),
            preferred_transport="http_json",
        )

    def build_envelope(
        self,
        *,
        task_type: str,
        source_agent: str,
        target_agent: str,
        input_payload: dict,
        parent_task_id: str | None = None,
        run_id: str | None = None,
        trace_id: str | None = None,
    ) -> TaskEnvelope:
        """构造统一 TaskEnvelope。"""

        return TaskEnvelope(
            run_id=run_id or _generate_supervisor_run_id(),
            trace_id=trace_id or _generate_trace_id(),
            parent_task_id=parent_task_id,
            task_type=task_type,
            source_agent=source_agent,
            target_agent=target_agent,
            input_payload=input_payload,
            status="pending",
        )

    def dispatch(self, envelope: TaskEnvelope) -> ResultContract:
        """按照目标专家定义做本地执行或 A2A-ready 委托。"""

        target = self.resolve_target(envelope.task_type)
        if target.agent_card.execution_mode == "local":
            local_handler = self.local_handlers.get(target.agent_card.agent_name)
            if local_handler is None:
                return ResultContract(
                    run_id=envelope.run_id,
                    trace_id=envelope.trace_id,
                    parent_task_id=envelope.parent_task_id,
                    task_type=envelope.task_type,
                    source_agent=envelope.source_agent,
                    target_agent=envelope.target_agent,
                    status=StatusContract(
                        status="failed",
                        sub_status="missing_local_handler",
                        message=f"未找到本地业务专家处理器: {target.agent_card.agent_name}",
                    ),
                    output_payload={},
                    error={"message": "missing local handler"},
                )
            return self.a2a_gateway.delegate_local(
                envelope=envelope,
                local_handler=local_handler,
            )

        return self.a2a_gateway.delegate_remote_ready(envelope=envelope)

    def build_input_payload(
        self,
        *,
        query: str,
        user_context: UserContext,
        conversation_id: str | None = None,
        output_mode: str = "lite",
        need_sql_explain: bool = False,
    ) -> dict:
        """构造 Supervisor 统一输入载荷。"""

        return {
            "query": query,
            "conversation_id": conversation_id,
            "output_mode": output_mode,
            "need_sql_explain": need_sql_explain,
            "user_context": user_context,
        }
