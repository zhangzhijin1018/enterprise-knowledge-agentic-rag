"""经营分析 LangGraph 样板节点。

重要变更（v2 链路收敛）：
本轮重构后，统一主链路改造为：
用户问句 -> LLMAnalyticsIntentParser 生成 AnalyticsIntent -> AnalyticsIntentValidator 校验
-> Clarification or SQL Builder -> SQL Guard -> SQL Gateway -> Summary / Chart / Insight / Report

ReAct 不再作为默认主链路，只作为可选 repair/replan 能力预留。

设计原则：
- 节点职责单一；
- 优先复用现有 AnalyticsService 的稳定逻辑，不推翻已有实现；
- 当前已经通过 Workflow Adapter 接入真实经营分析主链，
  但仍然保留对既有 Service 内部稳定逻辑的复用，避免一次性重写。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from core.analytics.analytics_result_model import AnalyticsResult
from core.analytics.intent.parser import LLMAnalyticsIntentParser
from core.analytics.intent.schema import AnalyticsIntent, IntentValidationResult
from core.analytics.intent.validator import AnalyticsIntentValidator
from core.common import error_codes
from core.common.exceptions import AppException
from core.common.response import build_response_meta
from core.config.settings import get_settings
from core.agent.control_plane.analytics_planner import AnalyticsPlan
from core.agent.workflows.analytics.degradation import AnalyticsWorkflowDegradationController
from core.agent.workflows.analytics.react.planner import AnalyticsReactPlanner
from core.agent.workflows.analytics.react.policy import AnalyticsReactPlanningPolicy
from core.agent.workflows.analytics.react.tools import AnalyticsReactToolRegistry
from core.agent.workflows.analytics.retry_policy import AnalyticsWorkflowRetryController
from core.agent.workflows.analytics.state import AnalyticsWorkflowOutcome, AnalyticsWorkflowStage
from core.services.analytics_service import AnalyticsService
from core.tools.mcp import SQLGatewayExecutionError
from core.tools.mcp.sql_mcp_contracts import SQLReadQueryRequest


class AnalyticsWorkflowNodes:
    """经营分析微观工作流节点集合。"""

    def __init__(self, analytics_service: AnalyticsService) -> None:
        self.analytics_service = analytics_service
        self.retry_controller = AnalyticsWorkflowRetryController()
        self.degradation_controller = AnalyticsWorkflowDegradationController()
        self.settings = get_settings()

        # 新版统一意图解析器和校验器
        self.intent_parser = LLMAnalyticsIntentParser(
            settings=self.settings,
            metric_catalog=analytics_service.metric_catalog,
            schema_registry=analytics_service.schema_registry,
        )
        self.intent_validator = AnalyticsIntentValidator(
            metric_catalog=analytics_service.metric_catalog,
            schema_registry=analytics_service.schema_registry,
        )

        # 旧版 ReAct Planner（保留作为可选 repair/replan 能力）
        self.react_policy = analytics_service.analytics_react_policy or AnalyticsReactPlanningPolicy(
            settings=self.settings,
        )
        self.react_planner = analytics_service.analytics_react_planner
        if self.react_planner is None and self.settings.analytics_react_planner_enabled:
            self.react_planner = AnalyticsReactPlanner(
                base_planner=analytics_service.analytics_planner,
                tool_registry=AnalyticsReactToolRegistry(
                    metric_catalog=analytics_service.metric_catalog,
                    schema_registry=analytics_service.schema_registry,
                ),
                settings=self.settings,
            )

    def analytics_entry(self, state: dict) -> dict:
        """工作流入口节点。

        职责：
        - 校验 query；
        - 标准化 output_mode；
        - 创建/读取 conversation；
        - 记录用户消息（clarification 恢复场景不重复写原始问题）；
        - 为后续 plan 节点准备 conversation memory。
        """

        query = (state.get("query") or "").strip()
        if not query:
            raise AppException(
                error_code=error_codes.ANALYTICS_QUERY_FAILED,
                message="经营分析问题不能为空",
                status_code=400,
                detail={},
            )

        user_context = state["user_context"]
        output_mode = self.analytics_service._normalize_output_mode(state.get("output_mode") or "lite")
        if state.get("resume_from_clarification"):
            conversation_id = state.get("conversation_id")
            conversation = self.analytics_service.conversation_repository.get_conversation(conversation_id)
            if conversation is None:
                raise AppException(
                    error_code=error_codes.CONVERSATION_NOT_FOUND,
                    message="恢复经营分析时找不到原始会话",
                    status_code=404,
                    detail={"conversation_id": conversation_id},
                )
        else:
            conversation = self.analytics_service._get_or_create_conversation(
                conversation_id=state.get("conversation_id"),
                query=query,
                user_context=user_context,
            )
        memory = self.analytics_service.conversation_repository.get_memory(conversation["conversation_id"])
        if not state.get("resume_from_clarification"):
            self.analytics_service.conversation_repository.add_message(
                conversation_id=conversation["conversation_id"],
                role="user",
                message_type="analytics_query",
                content=query,
                related_run_id=None,
                structured_content={"output_mode": output_mode},
            )
        state["query"] = query
        state["output_mode"] = output_mode
        state["conversation"] = conversation
        state["conversation_id"] = conversation["conversation_id"]
        state["conversation_memory"] = memory
        state["timing"] = {}
        state.setdefault("retry_count", 0)
        state.setdefault("retry_history", [])
        state.setdefault("degraded", False)
        state.setdefault("degraded_features", [])
        state.setdefault("react_used", False)
        state.setdefault("react_steps", [])
        state.setdefault("react_stopped_reason", "")
        state.setdefault("react_fallback_used", False)
        state["workflow_stage"] = AnalyticsWorkflowStage.ANALYTICS_ENTRY
        state["workflow_outcome"] = AnalyticsWorkflowOutcome.CONTINUE
        state["clarification_needed"] = False
        state["review_required"] = False
        return state

    def analytics_plan(self, state: dict) -> dict:
        """规划节点。

        职责：
        - 调用现有 AnalyticsPlanner；
        - 得到结构化槽位、clarification 信息和 data_source。

        本轮开始，这个节点内部允许一个“局部 ReAct Planning 子循环”：
        - 只在复杂经营分析问题上触发；
        - 只做问题拆解和槽位候选生成；
        - 最终仍然收敛为 `AnalyticsPlan`；
        - 后续 SQL 仍必须走 SQL Builder / SQL Guard / SQL Gateway。
        """

        if state.get("recovered_plan") is not None:
            plan = state["recovered_plan"]
        else:
            use_react = self.react_policy.should_use_react(
                query=state["query"],
                conversation_memory=state.get("conversation_memory"),
            )
            if use_react and self.react_planner is not None:
                try:
                    plan, react_state = self.react_planner.plan(
                        query=state["query"],
                        conversation_memory=state.get("conversation_memory"),
                        trace_id=state.get("trace_id"),
                    )
                    state["react_used"] = True
                    state["react_steps"] = self._build_react_steps_summary(react_state)
                    state["react_stopped_reason"] = react_state.stopped_reason
                    state["react_fallback_used"] = False
                except Exception as exc:
                    # ReAct 是 planning 节点内部的增强子循环，不是受控主链的唯一入口。
                    # 当 LLM、prompt 或结构化输出失败时，必须回退到确定性 Planner，
                    # 避免复杂问题因为辅助规划失败而完全不可用。
                    state["react_used"] = True
                    state["react_fallback_used"] = True
                    state["react_stopped_reason"] = f"fallback_to_rule_planner:{type(exc).__name__}"
                    plan = self.analytics_service.analytics_planner.plan(
                        query=state["query"],
                        conversation_memory=state.get("conversation_memory"),
                    )
            else:
                plan = self.analytics_service.analytics_planner.plan(
                    query=state["query"],
                    conversation_memory=state.get("conversation_memory"),
                )
        state["workflow_stage"] = AnalyticsWorkflowStage.ANALYTICS_PLAN
        state["workflow_outcome"] = AnalyticsWorkflowOutcome.CONTINUE
        state["plan"] = plan
        return state

    def _build_react_steps_summary(self, react_state) -> list[dict]:
        """构造 ReAct 轻量调试摘要。

        ReAct trace 属于微观执行态，不是 task_run 权威运行态。
        这里仅保留 action/observation/stopped_reason 的轻量摘要，
        避免把 prompt、完整推理链或大对象写入持久化快照。
        """

        observations = {item.step: item.observation for item in react_state.observations}
        return [
            {
                "step": item.step,
                "action": item.action,
                "action_input": item.action_input,
                "observation": observations.get(item.step, {}),
            }
            for item in react_state.actions
        ]

    def analytics_validate_slots(self, state: dict) -> dict:
        """槽位验证节点。

        职责：
        - 创建 task_run；
        - 保存 slot snapshot；
        - 判断进入 clarify 还是继续 SQL 执行。
        """

        plan = state["plan"]
        conversation = state["conversation"]
        user_context = state["user_context"]
        if state.get("existing_task_run") is not None:
            task_run = state["existing_task_run"]
            state["run_id"] = task_run["run_id"]
            state["trace_id"] = task_run["trace_id"]
        else:
            task_run = self.analytics_service.task_run_repository.create_task_run(
                conversation_id=conversation["conversation_id"],
                user_id=user_context.user_id,
                task_type="analytics",
                route="business_analysis",
                status="executing",
                sub_status="planning_query",
                # 这里只写“权威运行态”的轻量输入摘要。
                # workflow state 自己会继续保存 plan / workflow_stage 等微观临时态，
                # 但这些对象不应直接进入 task_run.input_snapshot。
                input_snapshot=self.analytics_service.snapshot_builder.build_input_snapshot(
                    query=state["query"],
                    conversation_id=conversation["conversation_id"],
                    output_mode=state["output_mode"],
                    need_sql_explain=state.get("need_sql_explain", False),
                    user_context=user_context,
                    planner_slots=plan.slots,
                    planning_source=plan.planning_source,
                    confidence=plan.confidence,
                ),
                risk_level="medium",
                review_status="not_required",
                run_id=state.get("run_id"),
                trace_id=state.get("trace_id"),
                parent_task_id=state.get("parent_task_id"),
            )
            state["run_id"] = task_run["run_id"]
            state["trace_id"] = task_run["trace_id"]
            self.analytics_service.conversation_repository.update_conversation(
                conversation["conversation_id"],
                current_route="analytics",
                current_status="active",
                last_run_id=task_run["run_id"],
            )
            # slot_snapshot 属于“恢复执行态”，只保存补槽恢复的必要字段。
            self.analytics_service.task_run_repository.create_slot_snapshot(
                run_id=task_run["run_id"],
                task_type="analytics",
                **self.analytics_service.snapshot_builder.build_slot_snapshot_payload(plan=plan),
            )
        state["task_run"] = task_run
        state["workflow_stage"] = AnalyticsWorkflowStage.ANALYTICS_VALIDATE_SLOTS
        state["clarification_needed"] = not plan.is_executable
        if not plan.is_executable:
            state["workflow_outcome"] = AnalyticsWorkflowOutcome.CLARIFY
            state["next_step"] = "analytics_clarify"
        else:
            state["workflow_outcome"] = AnalyticsWorkflowOutcome.CONTINUE
            state["next_step"] = "analytics_build_sql"
        return state

    def analytics_clarify(self, state: dict) -> dict:
        """澄清节点。

        职责：
        - 当最小可执行条件不满足时，生成结构化 clarification 响应；
        - 当前阶段仍复用现有 AnalyticsService 的澄清落库和返回格式。
        """

        # clarification 的持久化写入仍复用 service，
        # 但 service 内部现在也只会写轻量 context_snapshot 和 clarification_event。
        state["final_response"] = self.analytics_service._build_clarification_response(
            conversation_id=state["conversation_id"],
            task_run=state["task_run"],
            plan=state["plan"],
        )
        state["workflow_stage"] = AnalyticsWorkflowStage.ANALYTICS_CLARIFY
        state["workflow_outcome"] = AnalyticsWorkflowOutcome.CLARIFY
        state["clarification_needed"] = True
        return state

    def analytics_build_sql(self, state: dict) -> dict:
        """SQL 构造节点。

        职责：
        - 解析 metric / data_source / table definition；
        - 做指标权限和数据源权限检查；
        - 调用现有 SQLBuilder 生成 schema-aware SQL。
        """

        t0 = time.monotonic()
        state["workflow_stage"] = AnalyticsWorkflowStage.ANALYTICS_BUILD_SQL
        state["workflow_outcome"] = AnalyticsWorkflowOutcome.CONTINUE
        plan = state["plan"]
        task_run = state["task_run"]
        user_context = state["user_context"]

        def _build_sql_bundle():
            metric_definition = self.analytics_service._get_cached_metric(plan.slots.get("metric"))
            if metric_definition is None:
                raise AppException(
                    error_code=error_codes.ANALYTICS_QUERY_FAILED,
                    message="未识别到可执行指标",
                    status_code=400,
                    detail={"metric": plan.slots.get("metric")},
                )
            data_source_definition = (
                self.analytics_service.data_source_registry.get_data_source(plan.data_source)
                if self.analytics_service.data_source_registry is not None
                else self.analytics_service.schema_registry.get_data_source(plan.data_source)
            )
            table_definition = self.analytics_service.schema_registry.get_table_definition(
                table_name=metric_definition.table_name,
                data_source=data_source_definition.key,
            )
            permission_check_result = self.analytics_service._assert_metric_permission(
                metric_definition=metric_definition,
                user_context=user_context,
            )
            permission_check_result["data_source"] = self.analytics_service._assert_data_source_permission(
                data_source_definition=data_source_definition,
                user_context=user_context,
            )
            data_scope_result = self.analytics_service._build_data_scope_result(
                table_definition=table_definition,
                user_context=user_context,
            )
            self.analytics_service.task_run_repository.update_task_run(
                task_run["run_id"],
                sub_status="building_sql",
                # 这里只写权威运行态需要理解的轻量上下文摘要。
                # plan / sql_bundle / workflow_stage 仍然只保留在微观 workflow state。
                context_snapshot=self.analytics_service.snapshot_builder.build_context_snapshot(
                    slots=plan.slots,
                    planning_source=plan.planning_source,
                    confidence=plan.confidence,
                    resume_step="run_sql_pipeline",
                ),
            )
            sql_bundle = self.analytics_service.sql_builder.build(
                plan.slots,
                department_code=user_context.department_code,
            )
            return (
                metric_definition,
                data_source_definition,
                table_definition,
                permission_check_result,
                data_scope_result,
                sql_bundle,
            )

        (
            metric_definition,
            data_source_definition,
            table_definition,
            permission_check_result,
            data_scope_result,
            sql_bundle,
        ) = self.retry_controller.run(
            node_name="analytics_build_sql",
            state=state,
            action=_build_sql_bundle,
        )
        state["metric_definition"] = metric_definition
        state["data_source_definition"] = data_source_definition
        state["table_definition"] = table_definition
        state["permission_check_result"] = permission_check_result
        state["data_scope_result"] = data_scope_result
        state["sql_bundle"] = sql_bundle
        state["timing"]["sql_build_ms"] = round((time.monotonic() - t0) * 1000, 1)
        return state

    def analytics_guard_sql(self, state: dict) -> dict:
        """SQL Guard 节点。

        职责：
        - 对 schema-aware SQL 做只读校验；
        - 强制表白名单与部门过滤约束；
        - 如果不安全则直接阻断。
        """

        t1 = time.monotonic()
        state["workflow_stage"] = AnalyticsWorkflowStage.ANALYTICS_GUARD_SQL
        task_run = state["task_run"]
        table_definition = state["table_definition"]
        user_context = state["user_context"]
        sql_bundle = state["sql_bundle"]
        self.analytics_service.task_run_repository.update_task_run(
            task_run["run_id"],
            sub_status="checking_sql",
        )
        guard_result = self.analytics_service.sql_guard.validate(
            sql_bundle["generated_sql"],
            allowed_tables=self.analytics_service._get_cached_allowed_tables(sql_bundle["data_source"]),
            required_filter_column=table_definition.department_filter_column,
            required_filter_value=user_context.department_code if table_definition.department_filter_column else None,
        )
        state["timing"]["sql_guard_ms"] = round((time.monotonic() - t1) * 1000, 1)
        if not guard_result.is_safe or not guard_result.checked_sql:
            state["workflow_outcome"] = AnalyticsWorkflowOutcome.FAIL
            raise AppException(
                error_code=error_codes.SQL_GUARD_BLOCKED,
                message="SQL 安全检查未通过",
                status_code=400,
                detail={"blocked_reason": guard_result.blocked_reason},
            )
        state["guard_result"] = guard_result
        return state

    def analytics_execute_sql(self, state: dict) -> dict:
        """SQL 执行节点。

        职责：
        - 调用 SQL Gateway 执行只读查询；
        - 记录 SQL Audit；
        - 完成结果脱敏。
        """

        t2 = time.monotonic()
        state["workflow_stage"] = AnalyticsWorkflowStage.ANALYTICS_EXECUTE_SQL
        plan = state["plan"]
        task_run = state["task_run"]
        user_context = state["user_context"]
        sql_bundle = state["sql_bundle"]
        guard_result = state["guard_result"]
        table_definition = state["table_definition"]
        permission_check_result = state["permission_check_result"]
        data_scope_result = state["data_scope_result"]

        self.analytics_service.task_run_repository.update_task_run(
            task_run["run_id"],
            status="executing",
            sub_status="running_sql",
        )
        def _execute_sql():
            return self.analytics_service.sql_gateway.execute_readonly_query(
                SQLReadQueryRequest(
                    data_source=sql_bundle["data_source"],
                    sql=guard_result.checked_sql,
                    timeout_ms=3000,
                    row_limit=500,
                    trace_id=task_run["trace_id"],
                    run_id=task_run["run_id"],
                    metadata={
                        "planning_source": plan.planning_source,
                        "confidence": plan.confidence,
                    },
                )
            )

        try:
            execution_result = self.retry_controller.run(
                node_name="analytics_execute_sql",
                state=state,
                action=_execute_sql,
            )
        except Exception as exc:
            state["workflow_outcome"] = AnalyticsWorkflowOutcome.FAIL
            self.analytics_service.task_run_repository.update_task_run(
                task_run["run_id"],
                status="failed",
                sub_status="running_sql",
                error_code=error_codes.SQL_EXECUTION_FAILED,
                error_message=str(exc),
                finished_at=datetime.now(timezone.utc),
            )
            raise AppException(
                error_code=error_codes.SQL_EXECUTION_FAILED,
                message="经营分析 SQL 执行失败",
                status_code=500,
                detail={"reason": str(exc)},
            ) from exc
        state["timing"]["sql_execute_ms"] = round((time.monotonic() - t2) * 1000, 1)

        audit_record = self.analytics_service.sql_audit_repository.create_audit(
            run_id=task_run["run_id"],
            user_id=user_context.user_id,
            db_type=execution_result.db_type,
            metric_scope=sql_bundle["metric_scope"],
            generated_sql=sql_bundle["generated_sql"],
            checked_sql=guard_result.checked_sql,
            is_safe=True,
            blocked_reason=None,
            execution_status="succeeded",
            row_count=execution_result.row_count,
            latency_ms=execution_result.latency_ms,
            metadata={
                **sql_bundle["builder_metadata"],
                "data_source": execution_result.data_source,
                "department_filter_column": table_definition.department_filter_column,
                "sensitive_fields": table_definition.sensitive_fields,
                "permission_check_result": permission_check_result,
                "data_scope_result": data_scope_result,
            },
        )

        t3 = time.monotonic()
        self.analytics_service.task_run_repository.update_task_run(
            task_run["run_id"],
            sub_status="explaining_result",
        )
        masking_result = self.analytics_service.data_masking_service.apply(
            rows=execution_result.rows,
            columns=execution_result.columns,
            visible_fields=self.analytics_service._get_cached_visible_fields(
                table_name=table_definition.name,
                data_source=execution_result.data_source,
            ),
            sensitive_fields=self.analytics_service._get_cached_sensitive_fields(
                table_name=table_definition.name,
                data_source=execution_result.data_source,
            ),
            masked_fields=self.analytics_service._get_cached_masked_fields(
                table_name=table_definition.name,
                data_source=execution_result.data_source,
            ),
            user_permissions=user_context.permissions,
        )
        state["timing"]["masking_ms"] = round((time.monotonic() - t3) * 1000, 1)
        state["execution_result"] = execution_result
        state["audit_record"] = audit_record
        state["masking_result"] = masking_result
        return state

    def analytics_summarize(self, state: dict) -> dict:
        """结果总结节点。

        职责：
        - 生成 summary；
        - 按 output_mode 延迟生成 chart_spec / insight_cards / report_blocks；
        - 构造统一 AnalyticsResult 对象。
        """

        plan = state["plan"]
        state["workflow_stage"] = AnalyticsWorkflowStage.ANALYTICS_SUMMARIZE
        state["workflow_outcome"] = AnalyticsWorkflowOutcome.CONTINUE
        output_mode = state["output_mode"]
        execution_result = state["execution_result"]
        masking_result = state["masking_result"]
        audit_record = state["audit_record"]
        sql_bundle = state["sql_bundle"]
        guard_result = state["guard_result"]
        permission_check_result = state["permission_check_result"]
        data_scope_result = state["data_scope_result"]
        need_sql_explain = bool(state.get("need_sql_explain"))

        summary = self.analytics_service._build_summary(plan.slots, execution_result)
        state["summary"] = summary
        sql_explain = None
        if need_sql_explain:
            sql_explain = (
                "当前阶段采用 schema-aware 受控模板 SQL。"
                f"主指标={plan.slots['metric']}，时间范围={plan.slots['time_range'].get('label')}，"
                f"group_by={plan.slots.get('group_by') or 'none'}，"
                f"compare_target={plan.slots.get('compare_target') or 'none'}，"
                f"data_source={execution_result.data_source}。"
            )

        effective_filters = sql_bundle["builder_metadata"].get("effective_filters", {})
        governance_decision = {
            "permission_check_result": permission_check_result,
            "data_scope_result": data_scope_result,
            "masked_fields": masking_result.masked_fields,
            "visible_fields": masking_result.visible_fields,
            "sensitive_fields": masking_result.sensitive_fields,
            "governance_action": masking_result.governance_decision,
            "effective_filters": effective_filters,
        }
        audit_info = self.analytics_service._build_audit_info(
            audit_record,
            permission_check_result=permission_check_result,
            data_scope_result=data_scope_result,
            masking_result=masking_result,
            effective_filters=effective_filters,
            guard_result=guard_result,
        )

        chart_spec = None
        insight_cards: list[dict] = []
        report_blocks: list[dict] = []

        if output_mode in {"standard", "full"}:
            t4 = time.monotonic()
            try:
                chart_spec = self.analytics_service._build_chart_spec(
                    slots=plan.slots,
                    execution_result=execution_result,
                    metric_name=plan.slots["metric"],
                )
            except Exception as exc:  # pragma: no cover - 降级保护
                self.degradation_controller.mark_degraded(
                    state=state,
                    feature="chart_spec",
                    reason=f"图表描述生成失败：{exc}",
                )
                chart_spec = None
            try:
                insight_cards = self.retry_controller.run(
                    node_name="analytics_summarize",
                    state=state,
                    action=lambda: self.analytics_service.insight_builder.build(
                        slots=plan.slots,
                        rows=masking_result.rows,
                        row_count=execution_result.row_count,
                    ),
                )
            except Exception as exc:  # pragma: no cover - 降级保护
                self.degradation_controller.mark_degraded(
                    state=state,
                    feature="insight_cards",
                    reason=f"洞察卡片生成失败：{exc}",
                )
                insight_cards = []
            state["timing"]["insight_ms"] = round((time.monotonic() - t4) * 1000, 1)

        if output_mode == "full":
            t5 = time.monotonic()
            try:
                report_blocks = self.retry_controller.run(
                    node_name="analytics_summarize",
                    state=state,
                    action=lambda: self.analytics_service.report_formatter.build(
                        summary=summary,
                        insight_cards=insight_cards,
                        tables=[
                            {
                                "name": "main_result",
                                "columns": masking_result.columns,
                                "rows": [list(row.values()) for row in masking_result.rows],
                            }
                        ],
                        chart_spec=chart_spec,
                        governance_note={
                            "audit_info": audit_info,
                            "permission_check_result": permission_check_result,
                            "data_scope_result": data_scope_result,
                            "masked_fields": masking_result.masked_fields,
                            "effective_filters": effective_filters,
                            "governance_action": masking_result.governance_decision,
                        },
                    ),
                )
            except Exception as exc:  # pragma: no cover - 降级保护
                self.degradation_controller.mark_degraded(
                    state=state,
                    feature="report_blocks",
                    reason=f"报告块生成失败：{exc}",
                )
                report_blocks = []
            state["timing"]["report_ms"] = round((time.monotonic() - t5) * 1000, 1)
        else:
            state["timing"].setdefault("insight_ms", 0.0)
            state["timing"].setdefault("report_ms", 0.0)

        state["analytics_result"] = AnalyticsResult(
            run_id=state["task_run"]["run_id"],
            trace_id=state["task_run"]["trace_id"],
            summary=summary,
            sql_preview=guard_result.checked_sql,
            row_count=execution_result.row_count,
            latency_ms=execution_result.latency_ms,
            data_source=execution_result.data_source,
            metric_scope=sql_bundle["metric_scope"],
            compare_target=plan.slots.get("compare_target"),
            group_by=plan.slots.get("group_by"),
            slots=plan.slots,
            planning_source=plan.planning_source,
            columns=execution_result.columns,
            rows=execution_result.rows,
            masked_columns=masking_result.columns,
            masked_rows=masking_result.rows,
            visible_fields=masking_result.visible_fields,
            sensitive_fields=masking_result.sensitive_fields,
            masked_fields=masking_result.masked_fields,
            hidden_fields=masking_result.hidden_fields,
            governance_decision=masking_result.governance_decision,
            chart_spec=chart_spec,
            insight_cards=insight_cards,
            report_blocks=report_blocks,
            safety_check_result={
                "is_safe": guard_result.is_safe,
                "blocked_reason": guard_result.blocked_reason,
                "table_whitelist": self.analytics_service._get_cached_allowed_tables(sql_bundle["data_source"]),
                "field_whitelist_reserved": self.analytics_service._get_cached_field_whitelist(
                    table_name=state["metric_definition"].table_name,
                    data_source=sql_bundle["data_source"],
                ),
                "governance_detail": guard_result.governance_detail,
            },
            permission_check_result=permission_check_result,
            data_scope_result=data_scope_result,
            effective_filters=effective_filters,
            audit_info=audit_info,
            sql_explain=sql_explain,
            timing_breakdown=state["timing"],
            degraded=bool(state.get("degraded")),
            degraded_features=list(state.get("degraded_features") or []),
            retry_summary={
                "retry_count": int(state.get("retry_count", 0)),
                "retry_history": list(state.get("retry_history") or []),
            },
        )
        return state

    def analytics_finish(self, state: dict) -> dict:
        """结束节点。

        职责：
        - 写入轻快照；
        - 单独保存 heavy result；
        - 记录 assistant 消息；
        - 返回与现有 analytics/query 兼容的最终响应。
        """

        if state.get("final_response") is not None:
            state["workflow_stage"] = AnalyticsWorkflowStage.ANALYTICS_FINISH
            return state

        analytics_result = state["analytics_result"]
        task_run = state["task_run"]
        conversation_id = state["conversation_id"]
        plan = state["plan"]

        # finish 节点只把轻量输出摘要写回 task_run。
        # 重结果继续交给 analytics_result_repository，避免 output_snapshot 再次膨胀。
        lightweight_snapshot = self.analytics_service.snapshot_builder.build_output_snapshot(
            analytics_result=analytics_result,
        )
        self.analytics_service.task_run_repository.update_task_run(
            task_run["run_id"],
            status="succeeded",
            sub_status="explaining_result",
            output_snapshot=lightweight_snapshot,
            finished_at=datetime.now(timezone.utc),
        )
        self.analytics_service.analytics_result_repository.save_heavy_result(
            run_id=task_run["run_id"],
            heavy_result=analytics_result.to_heavy_result(),
        )
        self.analytics_service.conversation_repository.add_message(
            conversation_id=conversation_id,
            role="assistant",
            message_type="analytics_answer",
            content=analytics_result.summary,
            related_run_id=task_run["run_id"],
            structured_content={
                "sql_preview": analytics_result.sql_preview,
                "chart_spec": analytics_result.chart_spec,
            },
        )
        self.analytics_service.conversation_repository.upsert_memory(
            conversation_id,
            last_route="analytics",
            last_metric=plan.slots.get("metric"),
            last_time_range=plan.slots.get("time_range") or {},
            last_org_scope=plan.slots.get("org_scope") or {},
            short_term_memory={
                "last_analytics_run_id": task_run["run_id"],
                "last_group_by": plan.slots.get("group_by"),
                "last_compare_target": plan.slots.get("compare_target"),
                "last_top_n": plan.slots.get("top_n"),
                "last_sort_direction": plan.slots.get("sort_direction"),
            },
        )
        if state["output_mode"] == "lite":
            response_data = analytics_result.to_lite_view()
        elif state["output_mode"] == "standard":
            response_data = analytics_result.to_standard_view()
        else:
            response_data = analytics_result.to_full_view()

        if state.get("review_required"):
            state["final_response"] = {
                "data": {
                    "review_required": True,
                    "summary": analytics_result.summary,
                },
                "meta": build_response_meta(
                    conversation_id=conversation_id,
                    run_id=task_run["run_id"],
                    status="waiting_review",
                    sub_status="awaiting_review",
                    review_status="pending",
                    degraded=bool(state.get("degraded")),
                    degraded_features=list(state.get("degraded_features") or []),
                    react_used=bool(state.get("react_used")),
                    react_fallback_used=bool(state.get("react_fallback_used")),
                    react_stopped_reason=state.get("react_stopped_reason") or None,
                    is_async=False,
                    need_clarification=False,
                ),
            }
            state["workflow_stage"] = AnalyticsWorkflowStage.ANALYTICS_FINISH
            state["workflow_outcome"] = AnalyticsWorkflowOutcome.REVIEW
            return state

        state["final_response"] = {
            "data": response_data,
            "meta": build_response_meta(
                conversation_id=conversation_id,
                run_id=task_run["run_id"],
                status="succeeded",
                sub_status="explaining_result",
                degraded=bool(state.get("degraded")),
                degraded_features=list(state.get("degraded_features") or []),
                react_used=bool(state.get("react_used")),
                react_fallback_used=bool(state.get("react_fallback_used")),
                react_stopped_reason=state.get("react_stopped_reason") or None,
                is_async=False,
                need_clarification=False,
            ),
        }
        state["workflow_stage"] = AnalyticsWorkflowStage.ANALYTICS_FINISH
        state["workflow_outcome"] = AnalyticsWorkflowOutcome.REVIEW if state.get("review_required") else AnalyticsWorkflowOutcome.FINISH
        return state
