"""经营分析 LangGraph 微观执行样板。

这一层回答的是“怎么做”：
- 宏观层 Supervisor / A2A Gateway 决定把任务交给谁；
- 微观层 Analytics Workflow 决定经营分析专家内部如何一步步执行。

为什么这一轮先做经营分析样板：
1. 经营分析主链路已经相对稳定，节点边界清楚；
2. 适合验证 LangGraph 风格的显式状态流转；
3. 不会像一次性改所有专家那样引发大面积回归风险。

当前实现策略：
1. 如果环境里已经安装 `langgraph`，优先使用真实 `StateGraph`；
2. 如果当前环境还没安装 `langgraph`，使用本地 fallback runner 跑通相同节点顺序；
3. 这样可以保证“目录骨架、契约模型、最小样板”先一致，后续再平滑切到真实依赖。
"""

from __future__ import annotations

from typing import Callable

from core.agent.workflows.analytics.nodes import AnalyticsWorkflowNodes
from core.agent.workflows.analytics.state import AnalyticsWorkflowState
from core.services.analytics_service import AnalyticsService
from core.tools.a2a import ResultContract, StatusContract

try:  # pragma: no cover - 当前仓库未强依赖 langgraph 时走 fallback
    from langgraph.graph import END, StateGraph

    LANGGRAPH_AVAILABLE = True
except Exception:  # pragma: no cover - 保持第一轮样板可跑
    END = "__end__"
    StateGraph = None
    LANGGRAPH_AVAILABLE = False


def _route_after_validation(state: AnalyticsWorkflowState) -> str:
    """根据槽位校验结果决定后续走向。"""

    return state.get("next_step", "analytics_build_sql")


class _LocalCompiledAnalyticsWorkflow:
    """LangGraph 缺失时的本地 fallback executor。

    目的不是替代 LangGraph，而是让第一轮样板在当前仓库内先可运行、可测试。
    """

    def __init__(self, nodes: AnalyticsWorkflowNodes) -> None:
        self.nodes = nodes

    def invoke(self, state: AnalyticsWorkflowState) -> AnalyticsWorkflowState:
        """按固定节点顺序执行最小 workflow。"""

        state = self.nodes.analytics_entry(dict(state))
        state = self.nodes.analytics_plan(state)
        state = self.nodes.analytics_validate_slots(state)
        if state.get("next_step") == "analytics_clarify":
            state = self.nodes.analytics_clarify(state)
            state = self.nodes.analytics_finish(state)
            return state
        state = self.nodes.analytics_build_sql(state)
        state = self.nodes.analytics_guard_sql(state)
        state = self.nodes.analytics_execute_sql(state)
        state = self.nodes.analytics_summarize(state)
        state = self.nodes.analytics_finish(state)
        return state


class AnalyticsLangGraphWorkflow:
    """经营分析微观执行工作流入口。"""

    def __init__(self, analytics_service: AnalyticsService) -> None:
        self.analytics_service = analytics_service
        self.nodes = AnalyticsWorkflowNodes(analytics_service=analytics_service)
        self._compiled = self._build_graph()

    def _build_graph(self):
        """构造真实 LangGraph 或本地 fallback。"""

        if not LANGGRAPH_AVAILABLE:
            return _LocalCompiledAnalyticsWorkflow(self.nodes)

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

    def invoke(
        self,
        *,
        query: str,
        user_context,
        conversation_id: str | None = None,
        output_mode: str = "lite",
        need_sql_explain: bool = False,
    ) -> dict:
        """执行经营分析微观工作流。"""

        state: AnalyticsWorkflowState = {
            "query": query,
            "user_context": user_context,
            "conversation_id": conversation_id,
            "output_mode": output_mode,
            "need_sql_explain": need_sql_explain,
        }
        result_state = self._compiled.invoke(state)
        return result_state["final_response"]

    def as_local_handler(self) -> Callable:
        """返回可供 Supervisor 本地委托调用的 handler。"""

        def _handler(envelope) -> dict:
            payload = envelope.input_payload
            response = self.invoke(
                query=payload["query"],
                user_context=payload["user_context"],
                conversation_id=payload.get("conversation_id"),
                output_mode=payload.get("output_mode", "lite"),
                need_sql_explain=payload.get("need_sql_explain", False),
            )
            meta = response.get("meta", {})
            return ResultContract(
                run_id=meta.get("run_id") or envelope.run_id,
                trace_id=response.get("data", {}).get("trace_id") or envelope.trace_id,
                parent_task_id=envelope.parent_task_id,
                task_type=envelope.task_type,
                source_agent=envelope.source_agent,
                target_agent=envelope.target_agent,
                status=StatusContract(
                    status=meta.get("status", "failed"),
                    sub_status=meta.get("sub_status"),
                    review_status=meta.get("review_status"),
                ),
                output_payload=response,
                error=None,
            )

        return _handler
