"""经营分析 Workflow Adapter。

这一层是现有 `AnalyticsService` 和 `AnalyticsLangGraphWorkflow` 之间的稳定适配层。

为什么不能让 API / Service 直接操作 workflow graph：
1. API 层不应该感知 LangGraph 节点、状态结构和 graph compile 细节；
2. Service 层当前仍承担很多既有兼容职责，直接把 graph 细节塞进去会导致职责混乱；
3. Adapter 可以把“传统 service 编排入口”平滑过渡到“workflow-first 执行入口”，
   同时保留后续继续接 Supervisor 本地 handler、远端 A2A handler 的统一边界。

为什么 adapter 是关键过渡层：
1. 当前项目不是推翻重写，而是增量演进；
2. Adapter 允许我们先把经营分析真实主链切到 workflow，
   但不破坏既有 API、export、review、run detail 的稳定契约；
3. 后续如果别的业务专家也切到 LangGraph，可以沿用相同模式逐步演进。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from core.agent.workflows.analytics.status_mapper import AnalyticsWorkflowStatusMapper
from core.common.exceptions import AppException
from core.tools.a2a import ResultContract, StatusContract, TaskEnvelope
from core.agent.workflows.analytics.graph import AnalyticsLangGraphWorkflow

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型提示
    from core.services.analytics_service import AnalyticsService
    from core.security.auth import UserContext


class AnalyticsWorkflowAdapter:
    """经营分析工作流适配层。"""

    def __init__(self, analytics_service: AnalyticsService) -> None:
        self.analytics_service = analytics_service
        self.workflow = AnalyticsLangGraphWorkflow(analytics_service=analytics_service)

    def execute_query(
        self,
        *,
        query: str,
        user_context: UserContext,
        conversation_id: str | None = None,
        output_mode: str = "lite",
        need_sql_explain: bool = False,
        run_id: str | None = None,
        trace_id: str | None = None,
        parent_task_id: str | None = None,
    ) -> dict:
        """以稳定方法签名执行经营分析 workflow。

        这里对上层暴露的仍然是“提交经营分析请求”的语义，
        而不是“调用哪个 graph、走哪些 node”的内部细节。
        """

        return self.workflow.invoke(
            query=query,
            user_context=user_context,
            conversation_id=conversation_id,
            output_mode=output_mode,
            need_sql_explain=need_sql_explain,
            run_id=run_id,
            trace_id=trace_id,
            parent_task_id=parent_task_id,
        )

    def execute_state(
        self,
        *,
        query: str,
        user_context: UserContext,
        conversation_id: str | None = None,
        output_mode: str = "lite",
        need_sql_explain: bool = False,
        run_id: str | None = None,
        trace_id: str | None = None,
        parent_task_id: str | None = None,
    ) -> dict:
        """执行 workflow 并返回完整微观状态。

        这个方法主要供：
        1. Supervisor / A2A 本地 handler 做状态映射；
        2. 状态机测试验证微观字段；
        3. 后续恢复执行和更细粒度可观测性接入。
        """

        return self.workflow.run_state(
            query=query,
            user_context=user_context,
            conversation_id=conversation_id,
            output_mode=output_mode,
            need_sql_explain=need_sql_explain,
            run_id=run_id,
            trace_id=trace_id,
            parent_task_id=parent_task_id,
        )

    def to_result_contract(
        self,
        *,
        envelope: TaskEnvelope,
        response: dict,
        workflow_state: dict | None = None,
    ) -> ResultContract:
        """把 workflow 业务返回统一收敛为 A2A ResultContract。

        为什么必须做这一步：
        1. 业务 workflow 的原生返回偏向 HTTP/API 语义；
        2. Supervisor / A2A Gateway 需要稳定的跨专家协议；
        3. 先统一 ResultContract，后续切远端 A2A transport 时，上层无需再改。
        """

        meta = response.get("meta", {})
        data = response.get("data", {})
        status = (
            AnalyticsWorkflowStatusMapper.map_to_supervisor_status(workflow_state)
            if workflow_state is not None
            else StatusContract(
                status=meta.get("status", "failed"),
                sub_status=meta.get("sub_status"),
                review_status=meta.get("review_status"),
                message=meta.get("message"),
            )
        )
        return ResultContract(
            run_id=meta.get("run_id") or envelope.run_id,
            trace_id=data.get("trace_id") or envelope.trace_id,
            parent_task_id=envelope.parent_task_id,
            task_type=envelope.task_type,
            source_agent=envelope.source_agent,
            target_agent=envelope.target_agent,
            status=status,
            output_payload=response,
            error=response.get("error"),
        )

    def as_local_handler(self) -> Callable[[TaskEnvelope], ResultContract]:
        """返回可供 Supervisor / DelegationController 使用的本地 handler。"""

        def _handler(envelope: TaskEnvelope) -> ResultContract:
            payload = envelope.input_payload
            try:
                workflow_state = self.execute_state(
                    query=payload["query"],
                    user_context=payload["user_context"],
                    conversation_id=payload.get("conversation_id"),
                    output_mode=payload.get("output_mode", "lite"),
                    need_sql_explain=payload.get("need_sql_explain", False),
                    run_id=envelope.run_id,
                    trace_id=envelope.trace_id,
                    parent_task_id=envelope.parent_task_id,
                )
                response = workflow_state["final_response"]
                return self.to_result_contract(
                    envelope=envelope,
                    response=response,
                    workflow_state=workflow_state,
                )
            except AppException as exc:
                return ResultContract(
                    run_id=envelope.run_id,
                    trace_id=envelope.trace_id,
                    parent_task_id=envelope.parent_task_id,
                    task_type=envelope.task_type,
                    source_agent=envelope.source_agent,
                    target_agent=envelope.target_agent,
                    status=StatusContract(
                        status="failed",
                        sub_status="terminal_failure",
                        review_status=None,
                        message=exc.message,
                    ),
                    output_payload={},
                    error={
                        "error_code": exc.error_code,
                        "message": exc.message,
                        "detail": exc.detail,
                    },
                )

        return _handler
