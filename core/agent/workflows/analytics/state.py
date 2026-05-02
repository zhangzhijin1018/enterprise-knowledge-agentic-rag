"""经营分析 LangGraph 微观执行状态（v2 纯 Workflow 链路）。

v2 变更：
- 移除旧版 AnalyticsPlan 依赖
- 使用 AnalyticsIntent 作为主链路意图对象

设计原则：
- LangGraph StateDict 用于结构化微观执行上下文
- 不重复造数据库，依赖 task_run / slot_snapshot / clarification 等权威状态对象
"""

from __future__ import annotations

from enum import Enum
from typing import Any, TypedDict

from core.analytics.analytics_result_model import AnalyticsResult
from core.analytics.intent.schema import AnalyticsIntent
from core.security.auth import UserContext


class AnalyticsWorkflowStage(str, Enum):
    """经营分析子 Agent 的微观执行阶段。

    这些值只描述"经营分析内部当前走到哪个节点"，
    不应该直接暴露给 Supervisor 当作宏观生命周期状态。
    """

    # 入口节点：做输入标准化、会话准备。
    ANALYTICS_ENTRY = "analytics_entry"

    # 规划节点：做意图识别、槽位抽取、语义补强。
    # 本轮重构后，统一使用 LLMAnalyticsIntentParser 生成 AnalyticsIntent。
    ANALYTICS_PLAN = "analytics_plan"

    # 槽位校验节点：判断是否满足最小可执行条件。
    ANALYTICS_VALIDATE_SLOTS = "analytics_validate_slots"

    # 澄清节点：当关键信息缺失时，生成结构化 clarification。
    ANALYTICS_CLARIFY = "analytics_clarify"

    # SQL 构造节点：生成 schema-aware 受控 SQL。
    ANALYTICS_BUILD_SQL = "analytics_build_sql"

    # SQL Guard 节点：做只读限制，白名单、范围过滤。
    ANALYTICS_GUARD_SQL = "analytics_guard_sql"

    # SQL 执行节点：调 SQL Gateway 执行只读查询。
    ANALYTICS_EXECUTE_SQL = "analytics_execute_sql"

    # 结果总结节点：生成 summary / chart / insight / report。
    ANALYTICS_SUMMARIZE = "analytics_summarize"

    # 结束节点：落轻快照、落重结果、组装最终响应。
    ANALYTICS_FINISH = "analytics_finish"


class AnalyticsWorkflowOutcome(str, Enum):
    """经营分析子 Agent 的微观结果方向。

    它表达的是"当前节点之后，workflow 应该往哪个方向继续走"。
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

    新增 AnalyticsIntent 相关字段（本轮重构）：
    - intent：LLM 统一解析生成的 AnalyticsIntent
    - intent_validation_result：意图校验结果
    - planning_source：规划来源（llm_parser / rule_fallback）
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

    # 当前是否由 clarification 恢复入口进入 workflow。
    # 这属于微观执行控制字段，用于告诉 entry/validate 节点：
    # - 这次不是一条全新的用户问题；
    # - 而是基于原 run_id、slot_snapshot、clarification_event 做状态机恢复。
    resume_from_clarification: bool

    # -------------------------
    # 中间态业务上下文
    # -------------------------

    # 会话实体快照。
    # 这是 workflow 执行期间引用的会话对象，不是新的权威持久化副本。
    conversation: dict

    # 会话记忆。
    # 用于多轮继承，但只是执行期上下文，不是额外权威存储。
    # 需要持久化的多轮记忆仍应回到 conversation memory / slot_snapshot 等专属位置。
    conversation_memory: dict

    # -------------------------
    # AnalyticsIntent 相关字段（本轮重构新增）
    # -------------------------

    # LLM 统一解析生成的 AnalyticsIntent。
    # 这是新版主链路的结构化意图对象。
    intent: AnalyticsIntent

    # 意图校验结果。
    # Validator 输出的校验结果，包含是否通过、是否需要澄清等信息。
    intent_validation_result: dict | None

    # 规划来源。
    # - llm_parser：LLM 统一解析
    planning_source: str

    # v2：已移除旧版 AnalyticsPlan，统一使用 intent

    # 当前 task_run 快照。
    # 这是权威运行态对象在 workflow 中的引用。
    # 注意：它本身不是新的持久化层，只是 workflow 对权威运行态的当前视图。
    task_run: dict

    # clarification 恢复时复用的原 task_run。
    # 这里引用的是权威运行态对象的当前视图，目的是避免恢复执行时重复创建新的 run。
    existing_task_run: dict

    # 指标定义。
    # 这是执行期读取到的配置对象，节点结束后即可丢弃，不应直接落 task_run。
    metric_definition: Any

    # 数据源定义。
    # 这是执行期读取到的配置对象，节点结束后即可丢弃，不应直接落 task_run。
    data_source_definition: Any

    # 表定义。
    # 这是执行期读取到的配置对象，节点结束后即可丢弃，不应直接落 task_run。
    table_definition: Any

    # 指标级 / 数据源级权限检查结果。
    # 该对象常包含较细粒度治理信息，通常只保留摘要进入 output_snapshot，
    # 全量治理结果应进入 analytics_result / audit_info，而不是 task_run 主表。
    permission_check_result: dict

    # 部门范围等数据范围过滤结果。
    # 这是治理执行中间态，通常只保留轻量摘要，不直接作为权威运行态持久化。
    data_scope_result: dict

    # SQLBuilder 生成的结构化结果。
    # 该对象可能包含 generated_sql、builder_metadata 等中间态信息，
    # 它属于微观执行上下文，通常不直接落 task_run。
    sql_bundle: dict

    # SQL Guard 校验结果。
    # Guard 结果的全量对象属于执行期临时态；
    # 如果需要跨请求审计，应进入 sql_audit 或治理摘要，而不是直接写入 task_run。
    guard_result: Any

    # SQL 执行结果。
    # 该对象可能带全量 rows / columns，是典型的大对象执行态，
    # 原则上只在当前 workflow 内部流转，不直接写回 task_run。
    execution_result: Any

    # SQL 审计记录。
    # 审计记录本身已经有 sql_audits 作为权威存储，
    # workflow state 这里只保存当前节点需要引用的结果快照。
    audit_record: dict

    # 脱敏结果。
    # 脱敏后的 rows 仍然可能很大，因此该对象只在当前执行链中流转，
    # 需要重结果持久化时由 analytics_result_repository 承接。
    masking_result: Any

    # 是否在 analytics_plan 节点使用了局部 ReAct planning。
    # 这是微观执行调试字段，不是权威运行态；不能把完整 ReAct trace 写入 task_run。
    # 注意：本轮重构后，ReAct 只作为可选 repair/replan 能力预留，不是默认主链路。
    react_used: bool

    # ReAct 子循环的轻量步骤摘要。
    # 每步只保留 action/observation 摘要，不能包含 SQL 执行或状态写入指令。
    react_steps: list[dict[str, Any]]

    # ReAct 子循环停止原因。
    # 用于解释是正常 finish、达到 max_steps，还是触发禁止工具后回退。
    react_stopped_reason: str

    # ReAct 失败后是否回退到确定性 Planner。
    # 降级回规则 Planner 是可接受的规划降级，不应影响后续 SQL 安全链。
    react_fallback_used: bool

    # -------------------------
    # 输出态字段
    # -------------------------

    # 文本摘要。
    # 在 summarize 节点生成，供最终响应和 report/export 复用。
    # 这是少数会进入 task_run.output_snapshot 的微观产物之一，因为它是轻量摘要。
    summary: str

    # 统一分析结果对象。
    # 这是 workflow 对外部 service/export/result_repository 提供的标准载体。
    # 它本身不直接等于持久化对象：轻部分会进入 task_run.output_snapshot，
    # 重部分会拆到 analytics_result_repository。
    analytics_result: AnalyticsResult

    # 各关键阶段耗时。
    # 用于性能验收和慢点分析，不作为权威业务状态。
    # 一般只会以 timing_breakdown 摘要形式进入 output_snapshot 或 audit metadata。
    timing: dict[str, float]

    # 节点级重试总次数。
    # 这是微观执行可观测性字段，只会以轻量摘要形式进入 output_snapshot / meta，
    # 不会把完整异常堆栈持久化到 task_run。
    retry_count: int

    # 节点级重试摘要。
    # 每条记录只保留 node_name / attempt / error_type / error_message 等轻量信息，
    # 用于排查慢点和瞬时失败，不直接替代权威审计日志。
    retry_history: list[dict[str, Any]]

    # 当前 workflow 是否发生了"可接受降级"。
    # 例如 insight/chart/report 失败后退回 summary/table 模式时会置为 True。
    degraded: bool

    # 本次执行中被降级的特性列表。
    # 这属于微观执行摘要，后续会进入 response meta / output_snapshot 的轻量字段。
    degraded_features: list[str]

    # 最终响应。
    # 这是 workflow 对 API / Adapter 返回的最终业务结果。
    # 它是输出载体，不是新的权威存储层；真正落库仍要分拆到 task_run / analytics_result / sql_audit。
    final_response: dict
