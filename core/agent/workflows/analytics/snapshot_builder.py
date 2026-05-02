"""经营分析轻量快照构造层（v2 纯 Workflow 链路）。

v2 变更：
- 移除对旧版 AnalyticsPlan 的依赖
- 新增基于 AnalyticsIntent 的快照构造方法
- build_slot_snapshot_payload 和 build_clarification_event_payload 改为接受 intent 参数

设计原则：
1. `task_run.input_snapshot` 只承载轻量输入摘要；
2. `task_run.output_snapshot` 只承载轻量输出摘要；
3. `task_run.context_snapshot` 只承载恢复执行和审计所需的轻量上下文；
4. `slot_snapshot` 只承载补槽恢复信息；
5. `clarification_event` 只承载澄清交互事件信息；
6. `workflow_state` 的微观大对象不通过这里落库。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.analytics.analytics_result_model import AnalyticsResult
from core.analytics.intent.schema import AnalyticsIntent
from core.security.auth import UserContext


@dataclass(slots=True)
class AnalyticsSnapshotBuilder:
    """经营分析快照构造器（v2 纯 Workflow 链路）。

    这层不负责真正落库，只负责在上游把 payload 先收紧成"边界正确的轻量快照"。
    """

    def build_input_snapshot(
        self,
        *,
        query: str,
        conversation_id: str | None,
        output_mode: str,
        need_sql_explain: bool,
        user_context: UserContext,
        intent: AnalyticsIntent | None = None,
    ) -> dict:
        """构造 task_run.input_snapshot。

        这是"权威运行态"的轻量输入快照，只保存：
        - 用户问了什么；
        - 请求希望返回什么粒度；
        - 谁在发起请求；
        - Intent 产出的轻量槽位摘要。

        v2 变更：planner_slots / planning_source / confidence 改为从 intent 提取。
        """

        # 从 intent 提取槽位摘要
        planner_slots = {}
        if intent:
            if intent.metric:
                planner_slots["metric"] = intent.metric.metric_name or intent.metric.raw_text
            if intent.time_range:
                planner_slots["time_range"] = {
                    "raw_text": intent.time_range.raw_text,
                    "type": intent.time_range.type.value if hasattr(intent.time_range.type, "value") else intent.time_range.type,
                    "value": intent.time_range.value,
                }
            if intent.org_scope:
                planner_slots["org_scope"] = {
                    "raw_text": intent.org_scope.raw_text,
                    "type": intent.org_scope.type.value if hasattr(intent.org_scope.type, "value") else intent.org_scope.type,
                    "name": intent.org_scope.name,
                    "code": intent.org_scope.code,
                    "value": intent.org_scope.name,  # 兼容旧格式
                }
            if intent.group_by:
                planner_slots["group_by"] = intent.group_by
            if intent.compare_target:
                planner_slots["compare_target"] = (
                    intent.compare_target.value if hasattr(intent.compare_target, "value") else intent.compare_target
                )

        planning_source = "llm_parser"
        confidence = intent.confidence.overall if intent and intent.confidence else None

        return {
            "query": query,
            "conversation_id": conversation_id,
            "output_mode": output_mode,
            "need_sql_explain": need_sql_explain,
            "user_context_summary": self._build_user_context_summary(user_context),
            "planner_slots": planner_slots,
            "planning_source": planning_source,
            "confidence": confidence,
        }

    def build_output_snapshot(self, *, analytics_result: AnalyticsResult) -> dict:
        """构造 task_run.output_snapshot。

        这是"权威运行态"的轻量输出快照。

        为什么只接受 `AnalyticsResult` 而不是随便传 dict：
        - 统一结果对象已经明确区分了轻结果和重结果；
        - 这里直接复用 `to_lightweight_snapshot()`，避免上游重复拼装；
        - 这样可以保证 `tables / chart_spec / insight_cards / report_blocks`
          不会再被误塞回 output_snapshot。
        """

        return analytics_result.to_lightweight_snapshot()

    def build_context_snapshot(
        self,
        *,
        slots: dict | None = None,
        planning_source: str | None = None,
        confidence: float | None = None,
        missing_slots: list[str] | None = None,
        conflict_slots: list[str] | None = None,
        clarification_type: str | None = None,
        resume_step: str | None = None,
    ) -> dict:
        """构造 task_run.context_snapshot。

        这是"权威运行态"的轻量上下文摘要，主要服务：
        - clarification 恢复；
        - run detail 排查；
        - 宏观层理解当前缺什么、下一步准备做什么。

        为什么不写 workflow 临时大对象：
        - `sql_bundle / execution_result / workflow_stage` 都属于微观临时态；
        - 它们对跨请求恢复并不是必需字段；
        - 如果把这些对象放进 context_snapshot，会再次把 task_run 变成微观状态垃圾桶。
        """

        snapshot = {
            "slots": slots or {},
            "planning_source": planning_source,
            "confidence": confidence,
            "missing_slots": missing_slots or [],
            "conflict_slots": conflict_slots or [],
            "clarification_type": clarification_type,
            "resume_step": resume_step,
        }
        return {key: value for key, value in snapshot.items() if value not in (None, [], {})}

    def build_slot_snapshot_payload(self, *, intent: AnalyticsIntent) -> dict:
        """构造 slot_snapshot 写入载荷（v2 基于 AnalyticsIntent）。

        这是"恢复执行态"，只保存补槽所需的最小字段。
        """

        # 从 intent 提取槽位
        collected_slots = {}
        if intent.metric:
            collected_slots["metric"] = intent.metric.metric_name or intent.metric.raw_text
        if intent.time_range:
            collected_slots["time_range"] = intent.time_range.raw_text
        if intent.org_scope:
            collected_slots["org_scope"] = intent.org_scope.raw_text
        if intent.group_by:
            collected_slots["group_by"] = intent.group_by
        if intent.compare_target:
            collected_slots["compare_target"] = (
                intent.compare_target.value if hasattr(intent.compare_target, "value") else intent.compare_target
            )

        is_executable = not intent.need_clarification

        return {
            "required_slots": ["metric", "time_range"],
            "collected_slots": collected_slots,
            "missing_slots": intent.missing_fields or [],
            "min_executable_satisfied": is_executable,
            "awaiting_user_input": intent.need_clarification,
            "resume_step": "resume_after_analytics_slot_fill" if intent.need_clarification else "run_sql_pipeline",
        }

    def build_clarification_event_payload(self, *, intent: AnalyticsIntent) -> dict:
        """构造 clarification_event 写入载荷（v2 基于 AnalyticsIntent）。

        这是"可审计的交互事件"，只保存：
        - 本轮追问文本；
        - 要补齐哪些槽位。
        """

        return {
            "question_text": intent.clarification_question or "请补充经营分析关键条件",
            "target_slots": intent.missing_fields or [],
        }

    def _build_user_context_summary(self, user_context: UserContext) -> dict[str, Any]:
        """构造 user_context 的轻量摘要。

        这里只保留跨审计、跨恢复有价值但体量较小的信息：
        - `user_id`
        - `roles`
        - `department_code`
        - `permissions_count`

        为什么不把完整权限列表写进 input_snapshot：
        - 完整权限集合可能较大；
        - 权限真值以当前 `user_context` 和鉴权层为准；
        - 这里更适合保留"当时请求是谁发起的"轻量摘要。
        """

        return {
            "user_id": user_context.user_id,
            "roles": list(user_context.roles or []),
            "department_code": user_context.department_code,
            "permissions_count": len(user_context.permissions or []),
        }
