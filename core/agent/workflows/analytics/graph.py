"""经营分析 LangGraph StateGraph 工作流。

这一层回答的是“经营分析子 Agent 内部怎么做”：
- 宏观层 Supervisor / A2A Gateway 负责决定任务交给谁；
- 微观层 Analytics Workflow 负责决定经营分析专家内部的节点流转。

为什么从本轮开始要切到 StateGraph-first：
1. 经营分析主链已经不再只是 LangGraph-ready 样板，而是正式执行路径；
2. 如果生产路径继续长期保留本地 fallback runner，测试和生产就可能跑出两套行为；
3. StateGraph 的显式节点、条件分支和状态流转，正好匹配当前经营分析的微观状态机设计。

为什么当前不接 checkpoint：
1. 当前经营分析的中断恢复点仍相对固定，主要依赖业务状态机：
   - task_run
   - slot_snapshot
   - clarification_event
   - review / export task
2. 直接引入 LangGraph checkpoint 会把大量微观状态序列化，容易重新放大状态对象；
3. 当前先让 StateGraph 负责“单次 workflow 的显式执行流转”，
   把中断恢复继续交给业务持久化层，边界更清晰。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.agent.workflows.analytics.nodes import AnalyticsWorkflowNodes
from core.agent.workflows.analytics.state import (
    AnalyticsWorkflowOutcome,
    AnalyticsWorkflowStage,
    AnalyticsWorkflowState,
)
from core.agent.workflows.analytics.status_mapper import AnalyticsWorkflowStatusMapper
from core.common.exceptions import AppException
from core.services.analytics_service import AnalyticsService
from core.tools.a2a import ResultContract


def _load_stategraph_components() -> tuple[Any, Any]:
    """延迟加载 LangGraph 组件。

    为什么不在模块导入时直接强依赖：
    1. 这样测试可以更容易模拟“依赖缺失”场景；
    2. 错误信息也可以收口成更友好的运行时提示，而不是裸 ImportError；
    3. 但正式执行路径仍然只有 StateGraph，一旦缺失就直接清晰失败。
    """

    try:
        from langgraph.graph import END, StateGraph
    except Exception as exc:  # pragma: no cover - 依赖缺失时走清晰错误
        raise RuntimeError(
            "当前 Analytics Workflow 已正式依赖 LangGraph StateGraph，"
            "但运行环境中未正确安装 `langgraph`。"
            "请检查 pyproject.toml 是否已声明 `langgraph>=0.2,<1.0`，"
            "并确认当前 Python 环境已安装该依赖。"
        ) from exc
    return END, StateGraph


def _route_after_validation(state: AnalyticsWorkflowState) -> str:
    """根据槽位校验结果决定后续走向。

    为什么 clarification 是正常业务分支：
    1. 经营分析缺少 `metric / time_range` 等关键槽位时，本质上是“等待补充输入”；
    2. 这是一种标准可恢复中间态，不是失败态；
    3. 因此这里走的是条件分支，而不是异常失败分支。
    """

    return state.get("next_step", "analytics_build_sql")


class AnalyticsLangGraphWorkflow:
    """经营分析微观执行工作流入口。

    当前类的运行原则：
    - 正式执行路径：LangGraph `StateGraph`
    - 当前不启用 checkpoint
    - 中断恢复继续交给业务状态机
    """

    def __init__(self, analytics_service: AnalyticsService) -> None:
        self.analytics_service = analytics_service
        self.nodes = AnalyticsWorkflowNodes(analytics_service=analytics_service)
        # 明确暴露当前执行后端，方便测试、文档和运行时排查对齐。
        self.backend_name = "langgraph_stategraph"
        # 当前阶段明确不接 checkpoint。
        # 这不是遗漏，而是有意保持“业务状态恢复”和“微观执行流转”分层。
        self.checkpoint_enabled = False
        self._compiled = self._build_graph()

    def _build_graph(self):
        """构造正式 StateGraph。

        这里不再默认保留本地 fallback runner。
        原因是：
        1. 经营分析已经进入 workflow-first 正式阶段；
        2. 如果 fallback 长期存在为生产默认路径，测试和生产可能出现分叉；
        3. 当前应明确把“依赖缺失”视为环境问题，而不是静默切换执行引擎。
        """

        END, StateGraph = _load_stategraph_components()

        graph = StateGraph(AnalyticsWorkflowState)
        graph.add_node("analytics_entry", self.nodes.analytics_entry)
        graph.add_node("analytics_plan", self.nodes.analytics_plan)
        graph.add_node("analytics_validate_slots", self.nodes.analytics_validate_slots)
        graph.add_node("analytics_clarify", self.nodes.analytics_clarify)
        graph.add_node("analytics_build_sql", self.nodes.analytics_build_sql)
        graph.add_node("analytics_guard_sql", self.nodes.analytics_guard_sql)
        graph.add_node("analytics_execute_sql", self.nodes.analytics_execute_sql)
        graph.add_node("analytics_summarize", self.nodes.analytics_summarize)
        graph.add_node("analytics_finish", self.nodes.analytics_finish)

        graph.set_entry_point("analytics_entry")
        graph.add_edge("analytics_entry", "analytics_plan")
        graph.add_edge("analytics_plan", "analytics_validate_slots")
        graph.add_conditional_edges(
            "analytics_validate_slots",
            _route_after_validation,
            {
                "analytics_clarify": "analytics_clarify",
                "analytics_build_sql": "analytics_build_sql",
            },
        )
        graph.add_edge("analytics_clarify", "analytics_finish")
        graph.add_edge("analytics_build_sql", "analytics_guard_sql")
        graph.add_edge("analytics_guard_sql", "analytics_execute_sql")
        graph.add_edge("analytics_execute_sql", "analytics_summarize")
        graph.add_edge("analytics_summarize", "analytics_finish")
        graph.add_edge("analytics_finish", END)
        return graph.compile()

    def run_state(
        self,
        *,
        query: str,
        user_context,
        conversation_id: str | None = None,
        output_mode: str = "lite",
        need_sql_explain: bool = False,
        run_id: str | None = None,
        trace_id: str | None = None,
        parent_task_id: str | None = None,
        recovered_plan=None,
        resume_from_clarification: bool = False,
        existing_task_run: dict | None = None,
    ) -> AnalyticsWorkflowState:
        """执行经营分析微观工作流并返回完整微观状态。

        返回的是 workflow state，不是持久化快照。
        其中可能包含：
        - plan
        - sql_bundle
        - execution_result
        - timing

        这些对象继续属于微观临时态，不能直接全量落库。
        """

        state: AnalyticsWorkflowState = {
            "query": query,
            "user_context": user_context,
            "conversation_id": conversation_id,
            "parent_task_id": parent_task_id,
            "run_id": run_id,
            "trace_id": trace_id,
            "output_mode": output_mode,
            "need_sql_explain": need_sql_explain,
            "recovered_plan": recovered_plan,
            "resume_from_clarification": resume_from_clarification,
            "existing_task_run": existing_task_run,
        }
        return self._compiled.invoke(state)

    def resume_from_slots(
        self,
        *,
        query: str,
        user_context,
        conversation_id: str,
        run_id: str,
        trace_id: str,
        output_mode: str,
        need_sql_explain: bool,
        recovered_plan,
        existing_task_run: dict,
        parent_task_id: str | None = None,
    ) -> AnalyticsWorkflowState:
        """基于 clarification 补槽结果恢复 workflow。

        这里恢复的是“业务状态机”，不是原 Python 线程。
        具体做法是：
        1. 复用原 `run_id / trace_id / conversation_id`；
        2. 基于 `slot_snapshot + clarification_event` 重新构造可执行 state；
        3. 让 StateGraph 从入口重新走一遍，但跳过“新建 run / 新增原始用户 query”这类动作。
        """

        return self.run_state(
            query=query,
            user_context=user_context,
            conversation_id=conversation_id,
            output_mode=output_mode,
            need_sql_explain=need_sql_explain,
            run_id=run_id,
            trace_id=trace_id,
            parent_task_id=parent_task_id,
            recovered_plan=recovered_plan,
            resume_from_clarification=True,
            existing_task_run=existing_task_run,
        )

    def invoke(
        self,
        *,
        query: str,
        user_context,
        conversation_id: str | None = None,
        output_mode: str = "lite",
        need_sql_explain: bool = False,
        run_id: str | None = None,
        trace_id: str | None = None,
        parent_task_id: str | None = None,
    ) -> dict:
        """执行经营分析微观工作流并返回最终业务响应。"""

        result_state = self.run_state(
            query=query,
            user_context=user_context,
            conversation_id=conversation_id,
            output_mode=output_mode,
            need_sql_explain=need_sql_explain,
            run_id=run_id,
            trace_id=trace_id,
            parent_task_id=parent_task_id,
        )
        return result_state["final_response"]

    def as_local_handler(self) -> Callable:
        """返回可供 Supervisor 本地委托调用的 handler。

        当前仍保持：
        `Supervisor -> DelegationController -> local handler -> Workflow`
        这层不直接暴露 graph 细节，只对外返回统一 `ResultContract`。
        """

        def _handler(envelope) -> dict:
            payload = envelope.input_payload
            try:
                result_state = self.run_state(
                    query=payload["query"],
                    user_context=payload["user_context"],
                    conversation_id=payload.get("conversation_id"),
                    output_mode=payload.get("output_mode", "lite"),
                    need_sql_explain=payload.get("need_sql_explain", False),
                    run_id=envelope.run_id,
                    trace_id=envelope.trace_id,
                    parent_task_id=envelope.parent_task_id,
                )
                response = result_state["final_response"]
                status = AnalyticsWorkflowStatusMapper.map_to_supervisor_status(result_state)
                return ResultContract(
                    run_id=result_state.get("run_id") or envelope.run_id,
                    trace_id=result_state.get("trace_id") or envelope.trace_id,
                    parent_task_id=envelope.parent_task_id,
                    task_type=envelope.task_type,
                    source_agent=envelope.source_agent,
                    target_agent=envelope.target_agent,
                    status=status,
                    output_payload=response,
                    error=None,
                )
            except AppException as exc:
                return ResultContract(
                    run_id=envelope.run_id,
                    trace_id=envelope.trace_id,
                    parent_task_id=envelope.parent_task_id,
                    task_type=envelope.task_type,
                    source_agent=envelope.source_agent,
                    target_agent=envelope.target_agent,
                    status=AnalyticsWorkflowStatusMapper.map_to_supervisor_status(
                        {
                            "workflow_outcome": AnalyticsWorkflowOutcome.FAIL,
                            "workflow_stage": AnalyticsWorkflowStage.ANALYTICS_FINISH,
                        }
                    ),
                    output_payload={},
                    error={
                        "error_code": exc.error_code,
                        "message": exc.message,
                        "detail": exc.detail,
                    },
                )

        return _handler
