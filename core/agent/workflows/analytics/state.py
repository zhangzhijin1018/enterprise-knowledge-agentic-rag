"""经营分析 LangGraph 微观执行状态。

为什么要单独定义结构化 state：
1. LangGraph 的核心价值就是显式状态流转；
2. 当前项目已经有 `task_run / slot_snapshot / clarification / sql_audit` 等权威状态对象，
   这里不再重复造一套数据库，而是把“微观执行上下文”结构化；
3. 后续无论是 workflow 恢复执行、状态映射还是可观测性埋点，都需要稳定字段名。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, TypedDict

from core.agent.control_plane.analytics_planner import AnalyticsPlan
from core.analytics.analytics_result_model import AnalyticsResult
from core.security.auth import UserContext


class AnalyticsWorkflowStage(str, Enum):
    """经营分析子 Agent 的微观执行阶段。

    这些值只描述“经营分析内部当前走到哪个节点”，
    不应该直接暴露给 Supervisor 当作宏观生命周期状态。
    """

    # 入口节点：做输入标准化、会话准备。
    ANALYTICS_ENTRY = "analytics_entry"

    # 规划节点：做意图识别、槽位抽取、语义补强。
    ANALYTICS_PLAN = "analytics_plan"

    # 槽位校验节点：判断是否满足最小可执行条件。
    ANALYTICS_VALIDATE_SLOTS = "analytics_validate_slots"

    # 澄清节点：当关键信息缺失时，生成结构化 clarification。
    ANALYTICS_CLARIFY = "analytics_clarify"

    # SQL 构造节点：生成 schema-aware 受控 SQL。
    ANALYTICS_BUILD_SQL = "analytics_build_sql"

    # SQL Guard 节点：做只读限制、白名单、范围过滤。
    ANALYTICS_GUARD_SQL = "analytics_guard_sql"

    # SQL 执行节点：调 SQL Gateway 执行只读查询。
    ANALYTICS_EXECUTE_SQL = "analytics_execute_sql"

    # 结果总结节点：生成 summary / chart / insight / report。
    ANALYTICS_SUMMARIZE = "analytics_summarize"

    # 结束节点：落轻快照、落重结果、组装最终响应。
    ANALYTICS_FINISH = "analytics_finish"


class AnalyticsWorkflowOutcome(str, Enum):
    """经营分析子 Agent 的微观结果方向。

    它表达的是“当前节点之后，workflow 应该往哪个方向继续走”。
    """

    # 当前节点处理完成，workflow 应继续向下执行。
    CONTINUE = "continue"

    # 当前请求缺少必要槽位，需要进入 clarification。
    CLARIFY = "clarify"

    # 当前请求命中了审核要求，需要进入 review 等待态。
    REVIEW = "review"

    # 当前 workflow 已经顺利完成，可以收口输出。
    FINISH = "finish"

    # 当前 workflow 已经失败，不再继续往下执行。
    FAIL = "fail"


class AnalyticsWorkflowState(TypedDict, total=False):
    """经营分析微观工作流状态。

    字段分三类：
    1. 输入态字段：来自 API / Supervisor / Adapter；
    2. 中间态字段：只在 workflow 节点之间流转；
    3. 输出态字段：用于最终响应、状态映射和性能观测。
    """

    # -------------------------
    # 输入态字段
    # -------------------------

    # 用户原始经营分析问题。
    # 这是 workflow 的核心输入，同时会进入 task_run.input_snapshot。
    query: str

    # 当前会话 ID。
    # clarification 恢复、多轮分析继承都依赖这个标识。
    conversation_id: str | None

    # 父任务 ID。
    # 用于把微观执行链路挂到宏观 Supervisor / A2A 委托关系上。
    parent_task_id: str | None

    # 权威运行 ID。
    # 该字段需要贯穿 task_run、sql_audit、clarification、review 等链路。
    run_id: str | None

    # Trace ID。
    # 用于串联 Supervisor、Workflow、SQL Gateway、审计和后续可观测性。
    trace_id: str | None

    # 输出模式：lite / standard / full。
    # 该字段决定是否延迟生成 chart_spec / insight_cards / report_blocks。
    output_mode: str

    # 是否需要额外返回 SQL explain。
    need_sql_explain: bool

    # 用户上下文。
    # 包含角色、权限、部门，是经营分析治理链路的关键输入。
    user_context: UserContext

    # -------------------------
    # 微观状态机字段
    # -------------------------

    # 当前 workflow 所处节点阶段。
    workflow_stage: AnalyticsWorkflowStage

    # 当前阶段执行完之后的方向性结果。
    workflow_outcome: AnalyticsWorkflowOutcome

    # 下一个应进入的节点名称。
    # 这是 workflow 内部路由字段，不直接暴露给外层 API。
    next_step: str

    # 是否需要用户澄清。
    # clarification 是标准可恢复中间态，不能混成 failed。
    clarification_needed: bool

    # 是否需要人工审核。
    # 当前经营分析主查询链大多不走 review，但状态字段必须预留并明确表达。
    review_required: bool

    # -------------------------
    # 中间态业务上下文
    # -------------------------

    # 会话实体快照。
    conversation: dict

    # 会话记忆。
    # 用于多轮继承，但只是执行期上下文，不是额外权威存储。
    conversation_memory: dict

    # 结构化分析计划。
    # 包含 slots、clarification、data_source 等结果。
    plan: AnalyticsPlan

    # 当前 task_run 快照。
    # 这是权威运行态对象在 workflow 中的引用。
    task_run: dict

    # 指标定义。
    metric_definition: Any

    # 数据源定义。
    data_source_definition: Any

    # 表定义。
    table_definition: Any

    # 指标级 / 数据源级权限检查结果。
    permission_check_result: dict

    # 部门范围等数据范围过滤结果。
    data_scope_result: dict

    # SQLBuilder 生成的结构化结果。
    sql_bundle: dict

    # SQL Guard 校验结果。
    guard_result: Any

    # SQL 执行结果。
    execution_result: Any

    # SQL 审计记录。
    audit_record: dict

    # 脱敏结果。
    masking_result: Any

    # -------------------------
    # 输出态字段
    # -------------------------

    # 文本摘要。
    # 在 summarize 节点生成，供最终响应和 report/export 复用。
    summary: str

    # 统一分析结果对象。
    # 这是 workflow 对外部 service/export/result_repository 提供的标准载体。
    analytics_result: AnalyticsResult

    # 各关键阶段耗时。
    # 用于性能验收和慢点分析，不作为权威业务状态。
    timing: dict[str, float]

    # 最终响应。
    # 这是 workflow 对 API / Adapter 返回的最终业务结果。
    final_response: dict
