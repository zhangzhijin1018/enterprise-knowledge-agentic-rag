"""经营分析 LangGraph 微观执行状态。

为什么要单独定义结构化 state：
1. LangGraph 的核心就是显式状态流转；
2. 当前项目已有 `task_run / slot_snapshot / clarification / sql_audit` 等权威状态对象，
   这里要做的是“把微观执行上下文结构化”，而不是再发明一套散乱 dict；
3. 第一轮先把经营分析专家做成样板，后续其他业务专家可以沿用同样模式。
"""

from __future__ import annotations

from typing import Any, TypedDict

from core.agent.control_plane.analytics_planner import AnalyticsPlan
from core.analytics.analytics_result_model import AnalyticsResult
from core.security.auth import UserContext


class AnalyticsWorkflowState(TypedDict, total=False):
    """经营分析微观工作流状态。"""

    query: str
    conversation_id: str | None
    parent_task_id: str | None
    run_id: str | None
    trace_id: str | None
    output_mode: str
    need_sql_explain: bool
    user_context: UserContext

    conversation: dict
    conversation_memory: dict
    plan: AnalyticsPlan
    task_run: dict

    metric_definition: Any
    data_source_definition: Any
    table_definition: Any
    permission_check_result: dict
    data_scope_result: dict

    sql_bundle: dict
    guard_result: Any
    execution_result: Any
    audit_record: dict
    masking_result: Any

    summary: str
    analytics_result: AnalyticsResult
    timing: dict[str, float]
    final_response: dict
    next_step: str
