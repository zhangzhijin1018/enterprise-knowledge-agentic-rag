"""Supervisor 委托控制器。

这层是宏观调度层的一部分，职责非常克制：
1. 维护"任务类型 -> 业务专家"的最小映射；
2. 构造跨专家统一的 TaskEnvelope；
3. 决定本地执行还是 A2A-ready 委托；
4. 不承担经营分析、合同审查等微观业务执行细节。

为什么要把这层单独拆出来：
1. Supervisor 需要保持"接收请求、路由、委托、汇总结果"的职责边界；
2. 如果把具体委托策略写死在 SupervisorService 里，后续扩到多个业务专家会很难维护；
3. DelegationController 更像"宏观派单控制器"，便于后续接 Agent Card、远程注册中心和降级策略。
"""

from __future__ import annotations

from typing import Callable
from uuid import uuid4

from core.agent.supervisor.status import (
    SupervisorStatus,
    SupervisorSubStatus,
    build_supervisor_status_contract,
)
from core.security.auth import UserContext
from core.tools.a2a import (
    A2AGateway,
    AgentCardRef,
    DelegationTarget,
    ResultContract,
    TaskEnvelope,
)


def _generate_supervisor_run_id() -> str:
    """生成 Supervisor 宏观调度 run_id。"""

    return f"sup_{uuid4().hex[:12]}"


def _generate_trace_id() -> str:
    """生成宏观调度 trace_id。"""

    return f"tr_{uuid4().hex[:12]}"


class DelegationController:
    """宏观委托控制器。

    职责：
    - 维护任务类型到业务专家的映射
    - 构造统一的 TaskEnvelope
    - 决定本地执行或远程委托

    当前注册的 Agent：
    1. rag_agent: 通用知识库问答（制度/安全/设备/新能源/项目）
    2. contract_agent: 合同审查（走 Milvus 检索）
    3. analytics_agent: 经营数据分析（SQL 查询）
    """

    def __init__(
        self,
        a2a_gateway: A2AGateway | None = None,
        local_handlers: dict[str, Callable[[TaskEnvelope], ResultContract]] | None = None,
        delegation_targets: dict[str, DelegationTarget] | None = None,
    ) -> None:
        self.a2a_gateway = a2a_gateway or A2AGateway()
        self.local_handlers = local_handlers or {}
        self.delegation_targets = delegation_targets or self._build_default_targets()

    def _build_default_targets(self) -> dict[str, DelegationTarget]:
        """构造默认业务专家目标表。

        注册的 Agent：
        1. rag_agent: 通用 RAG 问答
           - 集团制度文件
           - 安全生产规程
           - 岗位操作手册
           - 设备检修手册
           - 新能源运维资料
           - 项目资料

        2. contract_agent: 合同审查
           - 合同解析
           - 条款抽取
           - 风险识别
           - 走 Milvus 检索相关制度模板

        3. analytics_agent: 经营分析
           - SQL 查询
           - 数据分析
           - 报告生成
        """

        # RAG Agent - 通用知识库问答
        rag_agent_card = AgentCardRef(
            agent_name="rag_agent",
            description=(
                "通用知识库问答 Agent，处理的业务域："
                "集团制度政策、安全生产规程、岗位操作手册、设备检修手册、"
                "新能源运维资料、项目资料问答"
            ),
            capabilities=[
                "rag_qa",
                "policy_qa",
                "safety_qa",
                "equipment_qa",
                "new_energy_ops_qa",
                "project_qa",
            ],
            execution_mode="local",
        )

        # 合同审查 Agent
        contract_agent_card = AgentCardRef(
            agent_name="contract_agent",
            description=(
                "合同审查 Agent，处理的业务域："
                "合同解析、条款抽取、风险识别、风险等级划分、"
                "法务复核、审查报告生成"
            ),
            capabilities=[
                "contract_review",
                "contract_parse",
                "clause_extraction",
                "risk_identification",
                "contract_report",
            ],
            execution_mode="local",
        )

        # 经营分析 Agent
        analytics_agent_card = AgentCardRef(
            agent_name="analytics_agent",
            description=(
                "经营分析 Agent，处理的业务域："
                "经营数据查询、SQL 生成、数据分析、图表生成、报告生成"
            ),
            capabilities=[
                "business_analysis",
                "sql_guarded_query",
                "analytics_summary",
                "chart_generation",
            ],
            execution_mode="local",
        )

        return {
            # RAG Agent
            "rag_qa": DelegationTarget(
                task_type="rag_qa",
                route_key="rag",
                agent_card=rag_agent_card,
                preferred_transport="local",
            ),
            "policy_qa": DelegationTarget(
                task_type="policy_qa",
                route_key="rag",
                agent_card=rag_agent_card,
                preferred_transport="local",
            ),
            "safety_qa": DelegationTarget(
                task_type="safety_qa",
                route_key="rag",
                agent_card=rag_agent_card,
                preferred_transport="local",
            ),
            "equipment_qa": DelegationTarget(
                task_type="equipment_qa",
                route_key="rag",
                agent_card=rag_agent_card,
                preferred_transport="local",
            ),
            "new_energy_ops_qa": DelegationTarget(
                task_type="new_energy_ops_qa",
                route_key="rag",
                agent_card=rag_agent_card,
                preferred_transport="local",
            ),
            "project_qa": DelegationTarget(
                task_type="project_qa",
                route_key="rag",
                agent_card=rag_agent_card,
                preferred_transport="local",
            ),
            # 合同审查 Agent
            "contract_review": DelegationTarget(
                task_type="contract_review",
                route_key="contract",
                agent_card=contract_agent_card,
                preferred_transport="local",
            ),
            # 经营分析 Agent
            "business_analysis": DelegationTarget(
                task_type="business_analysis",
                route_key="analytics",
                agent_card=analytics_agent_card,
                preferred_transport="local",
            ),
            "analytics_query": DelegationTarget(
                task_type="analytics_query",
                route_key="analytics",
                agent_card=analytics_agent_card,
                preferred_transport="local",
            ),
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
            status=SupervisorStatus.CREATED.value,
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
                    status=build_supervisor_status_contract(
                        status=SupervisorStatus.FAILED,
                        sub_status=SupervisorSubStatus.TERMINAL_FAILURE,
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
