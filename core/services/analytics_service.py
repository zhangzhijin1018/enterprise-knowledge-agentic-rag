"""经营分析主链路 Service。

本 Service 的职责不是做最终版 BI / 自由 NL2SQL，
而是把当前阶段企业经营分析的稳定主链路编排清楚：

用户问题
-> Planner 做意图识别与槽位提取
-> 缺槽位则澄清
-> 满足最小条件后构造 schema-aware SQL
-> SQL Guard 做安全检查与治理
-> 通过 SQL Gateway / SQL MCP-compatible server 执行只读查询
-> 按 output_mode 分级生成结果（lite / standard / full）
-> 记录 SQL Audit

V1 性能优化要点：
1. output_snapshot 轻量化：重内容拆到 analytics_result_repository，轻快照只保留摘要；
2. query 响应分级：lite / standard / full 三种输出模式，默认 lite；
3. insight / report 延迟生成：按 output_mode 决定是否生成 chart_spec / insight_cards / report_blocks；
4. 统一结果对象：AnalyticsResult 作为唯一结果载体，减少重复拷贝；
5. 可观测性增强：记录关键阶段耗时到 timing_breakdown；
6. registry/schema 缓存：高频只读对象通过 RegistryCache 常驻缓存。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from core.agent.control_plane.analytics_planner import AnalyticsPlan, AnalyticsPlanner
from core.agent.control_plane.sql_builder import SQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
from core.analytics.analytics_result_model import AnalyticsResult
from core.analytics.data_masking import DataMaskingResult, DataMaskingService
from core.analytics.data_source_registry import DataSourceRegistry
from core.analytics.insight_builder import InsightBuilder
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.report_formatter import ReportFormatter
from core.analytics.schema_registry import SchemaRegistry
from core.common import error_codes
from core.common.cache import RegistryCache, get_global_cache
from core.common.exceptions import AppException
from core.common.response import build_response_meta
from core.repositories.analytics_result_repository import AnalyticsResultRepository
from core.repositories.conversation_repository import ConversationRepository
from core.repositories.sql_audit_repository import SQLAuditRepository
from core.repositories.task_run_repository import TaskRunRepository
from core.security.auth import UserContext
from core.tools.mcp.sql_mcp_contracts import SQLReadQueryRequest
from core.tools.sql.sql_gateway import SQLGateway

VALID_OUTPUT_MODES = {"lite", "standard", "full"}
DEFAULT_OUTPUT_MODE = "lite"


class AnalyticsService:
    """经营分析应用编排层。"""

    def __init__(
        self,
        conversation_repository: ConversationRepository,
        task_run_repository: TaskRunRepository,
        sql_audit_repository: SQLAuditRepository,
        analytics_planner: AnalyticsPlanner,
        sql_builder: SQLBuilder,
        sql_guard: SQLGuard,
        sql_gateway: SQLGateway,
        schema_registry: SchemaRegistry,
        metric_catalog: MetricCatalog,
        data_source_registry: DataSourceRegistry | None = None,
        data_masking_service: DataMaskingService | None = None,
        insight_builder: InsightBuilder | None = None,
        report_formatter: ReportFormatter | None = None,
        analytics_result_repository: AnalyticsResultRepository | None = None,
        registry_cache: RegistryCache | None = None,
    ) -> None:
        self.conversation_repository = conversation_repository
        self.task_run_repository = task_run_repository
        self.sql_audit_repository = sql_audit_repository
        self.analytics_planner = analytics_planner
        self.sql_builder = sql_builder
        self.sql_guard = sql_guard
        self.sql_gateway = sql_gateway
        self.schema_registry = schema_registry
        self.metric_catalog = metric_catalog
        self.data_source_registry = data_source_registry
        self.data_masking_service = data_masking_service or DataMaskingService()
        self.insight_builder = insight_builder or InsightBuilder()
        self.report_formatter = report_formatter or ReportFormatter()
        self.analytics_result_repository = analytics_result_repository or AnalyticsResultRepository()
        self.registry_cache = registry_cache or get_global_cache()

    def submit_query(
        self,
        *,
        query: str,
        conversation_id: str | None,
        output_mode: str,
        need_sql_explain: bool,
        user_context: UserContext,
    ) -> dict:
        """提交经营分析请求。"""

        normalized_query = query.strip()
        if not normalized_query:
            raise AppException(
                error_code=error_codes.ANALYTICS_QUERY_FAILED,
                message="经营分析问题不能为空",
                status_code=400,
                detail={},
            )

        normalized_output_mode = self._normalize_output_mode(output_mode)

        conversation = self._get_or_create_conversation(
            conversation_id=conversation_id,
            query=normalized_query,
            user_context=user_context,
        )
        memory = self.conversation_repository.get_memory(conversation["conversation_id"])

        self.conversation_repository.add_message(
            conversation_id=conversation["conversation_id"],
            role="user",
            message_type="analytics_query",
            content=normalized_query,
            related_run_id=None,
            structured_content={"output_mode": normalized_output_mode},
        )

        plan = self.analytics_planner.plan(
            query=normalized_query,
            conversation_memory=memory,
        )

        task_run = self.task_run_repository.create_task_run(
            conversation_id=conversation["conversation_id"],
            user_id=user_context.user_id,
            task_type="analytics",
            route="business_analysis",
            status="executing",
            sub_status="planning_query",
            input_snapshot={
                "query": normalized_query,
                "output_mode": normalized_output_mode,
                "need_sql_explain": need_sql_explain,
                "planner_slots": plan.slots,
                "planning_source": plan.planning_source,
                "confidence": plan.confidence,
            },
            risk_level="medium",
            review_status="not_required",
        )
        self.conversation_repository.update_conversation(
            conversation["conversation_id"],
            current_route="analytics",
            current_status="active",
            last_run_id=task_run["run_id"],
        )

        self.task_run_repository.create_slot_snapshot(
            run_id=task_run["run_id"],
            task_type="analytics",
            required_slots=plan.required_slots,
            collected_slots=plan.slots,
            missing_slots=plan.missing_slots,
            min_executable_satisfied=plan.is_executable,
            awaiting_user_input=not plan.is_executable,
            resume_step="resume_after_analytics_slot_fill" if not plan.is_executable else "run_sql_pipeline",
        )

        if not plan.is_executable:
            return self._build_clarification_response(
                conversation_id=conversation["conversation_id"],
                task_run=task_run,
                plan=plan,
            )

        return self._execute_analytics_plan(
            conversation_id=conversation["conversation_id"],
            task_run=task_run,
            plan=plan,
            output_mode=normalized_output_mode,
            need_sql_explain=need_sql_explain,
            user_context=user_context,
        )

    def get_run_detail(self, *, run_id: str, output_mode: str = "full", user_context: UserContext) -> dict:
        """读取经营分析运行详情。

        支持 output_mode 分级返回：
        - lite：summary、row_count、latency_ms、run_id、trace_id
        - standard：在 lite 基础上增加 chart_spec、insight_cards
        - full：在 standard 基础上增加 tables、report_blocks、完整治理信息
        """

        task_run = self.task_run_repository.get_task_run(run_id)
        if task_run is None or task_run["task_type"] != "analytics":
            raise AppException(
                error_code=error_codes.ANALYTICS_RUN_NOT_FOUND,
                message="指定经营分析任务不存在",
                status_code=404,
                detail={"run_id": run_id},
            )

        conversation = self.conversation_repository.get_conversation(task_run["conversation_id"])
        if conversation is None:
            raise AppException(
                error_code=error_codes.CONVERSATION_NOT_FOUND,
                message="经营分析任务关联的会话不存在",
                status_code=404,
                detail={"run_id": run_id},
            )
        if conversation["user_id"] != user_context.user_id:
            raise AppException(
                error_code=error_codes.PERMISSION_DENIED,
                message="当前用户无权查看该经营分析任务",
                status_code=403,
                detail={
                    "run_id": run_id,
                    "conversation_id": task_run["conversation_id"],
                    "owner_user_id": conversation["user_id"],
                    "current_user_id": user_context.user_id,
                },
            )

        normalized_output_mode = self._normalize_output_mode(output_mode)
        output_snapshot = task_run.get("output_snapshot") or {}
        heavy_result = self.analytics_result_repository.get_heavy_result(run_id)

        base_data = {
            "run_id": task_run["run_id"],
            "conversation_id": task_run["conversation_id"],
            "task_type": task_run["task_type"],
            "route": task_run["route"],
            "status": task_run["status"],
            "sub_status": task_run["sub_status"],
            "trace_id": task_run["trace_id"],
            "summary": output_snapshot.get("summary"),
            "row_count": output_snapshot.get("row_count"),
            "latency_ms": output_snapshot.get("latency_ms"),
            "metric_scope": output_snapshot.get("metric_scope"),
            "data_source": output_snapshot.get("data_source"),
            "compare_target": output_snapshot.get("compare_target"),
            "group_by": output_snapshot.get("group_by"),
        }

        if normalized_output_mode == "lite":
            data = base_data
        elif normalized_output_mode == "standard":
            base_data.update({
                "sql_preview": output_snapshot.get("sql_preview"),
                "chart_spec": heavy_result.get("chart_spec") if heavy_result else None,
                "insight_cards": heavy_result.get("insight_cards", []) if heavy_result else [],
                "masked_fields": heavy_result.get("masked_fields", []) if heavy_result else [],
                "effective_filters": heavy_result.get("effective_filters", {}) if heavy_result else {},
                "governance_decision": output_snapshot.get("governance_decision"),
            })
            data = base_data
        else:
            slot_snapshot = self.task_run_repository.get_slot_snapshot(run_id) or {}
            latest_sql_audit = self.sql_audit_repository.get_latest_by_run_id(run_id)
            base_data.update({
                "slots": slot_snapshot.get("collected_slots", {}),
                "latest_sql_audit": latest_sql_audit,
                "output_snapshot": output_snapshot,
                "sql_preview": output_snapshot.get("sql_preview"),
                "sql_explain": heavy_result.get("sql_explain") if heavy_result else None,
                "safety_check_result": heavy_result.get("safety_check_result") if heavy_result else None,
                "chart_spec": heavy_result.get("chart_spec") if heavy_result else None,
                "insight_cards": heavy_result.get("insight_cards", []) if heavy_result else [],
                "report_blocks": heavy_result.get("report_blocks", []) if heavy_result else [],
                "tables": heavy_result.get("tables", []) if heavy_result else [],
                "audit_info": heavy_result.get("audit_info") if heavy_result else None,
                "permission_check_result": heavy_result.get("permission_check_result") if heavy_result else None,
                "data_scope_result": heavy_result.get("data_scope_result") if heavy_result else None,
                "masked_fields": heavy_result.get("masked_fields", []) if heavy_result else [],
                "effective_filters": heavy_result.get("effective_filters", {}) if heavy_result else {},
                "governance_decision": output_snapshot.get("governance_decision"),
                "timing_breakdown": heavy_result.get("timing_breakdown", {}) if heavy_result else {},
            })
            data = base_data

        return {
            "data": data,
            "meta": build_response_meta(
                conversation_id=task_run["conversation_id"],
                run_id=task_run["run_id"],
                status=task_run["status"],
                sub_status=task_run["sub_status"],
                is_async=False,
            ),
        }

    def _normalize_output_mode(self, output_mode: str) -> str:
        """标准化 output_mode，向后兼容。"""

        normalized = (output_mode or "").strip().lower()
        if normalized in VALID_OUTPUT_MODES:
            return normalized
        if normalized in {"summary", "default"}:
            return "standard"
        return DEFAULT_OUTPUT_MODE

    def _build_clarification_response(
        self,
        *,
        conversation_id: str,
        task_run: dict,
        plan: AnalyticsPlan,
    ) -> dict:
        """构造经营分析澄清响应。"""

        clarification = self.task_run_repository.create_clarification_event(
            run_id=task_run["run_id"],
            conversation_id=conversation_id,
            question_text=plan.clarification_question or "请补充经营分析关键条件",
            target_slots=plan.clarification_target_slots,
        )
        self.task_run_repository.update_task_run(
            task_run["run_id"],
            status="awaiting_user_clarification",
            sub_status="awaiting_slot_fill",
            context_snapshot={
                "slots": plan.slots,
                "missing_slots": plan.missing_slots,
                "conflict_slots": plan.conflict_slots,
                "clarification_type": plan.clarification_type,
            },
        )
        self.conversation_repository.add_message(
            conversation_id=conversation_id,
            role="assistant",
            message_type="clarification",
            content=clarification["question_text"],
            related_run_id=task_run["run_id"],
            structured_content={
                "clarification_id": clarification["clarification_id"],
                "target_slots": clarification["target_slots"],
                "clarification_type": plan.clarification_type,
                "reason": plan.clarification_reason,
                "suggested_options": plan.clarification_suggested_options,
            },
        )
        return {
            "data": {
                "clarification": {
                    "clarification_id": clarification["clarification_id"],
                    "question": clarification["question_text"],
                    "target_slots": clarification["target_slots"],
                    "clarification_type": plan.clarification_type,
                    "reason": plan.clarification_reason,
                    "suggested_options": plan.clarification_suggested_options,
                }
            },
            "meta": build_response_meta(
                conversation_id=conversation_id,
                run_id=task_run["run_id"],
                status="awaiting_user_clarification",
                sub_status="awaiting_slot_fill",
                need_clarification=True,
                is_async=False,
            ),
        }

    def _get_or_create_conversation(
        self,
        *,
        conversation_id: str | None,
        query: str,
        user_context: UserContext,
    ) -> dict:
        """读取已有会话或创建新会话。"""

        if conversation_id:
            conversation = self.conversation_repository.get_conversation(conversation_id)
            if conversation is None:
                raise AppException(
                    error_code=error_codes.CONVERSATION_NOT_FOUND,
                    message="指定会话不存在",
                    status_code=404,
                    detail={"conversation_id": conversation_id},
                )
            if conversation["user_id"] != user_context.user_id:
                raise AppException(
                    error_code=error_codes.PERMISSION_DENIED,
                    message="当前用户无权访问该会话",
                    status_code=403,
                    detail={
                        "conversation_id": conversation_id,
                        "owner_user_id": conversation["user_id"],
                        "current_user_id": user_context.user_id,
                    },
                )
            return conversation

        return self.conversation_repository.create_conversation(
            user_id=user_context.user_id,
            title=query[:20],
            current_route="analytics",
            current_status="active",
        )

    def _execute_analytics_plan(
        self,
        *,
        conversation_id: str,
        task_run: dict,
        plan: AnalyticsPlan,
        output_mode: str,
        need_sql_explain: bool,
        user_context: UserContext,
    ) -> dict:
        """执行经营分析主链路。

        V1 性能优化：
        1. 按 output_mode 决定是否生成 chart_spec / insight_cards / report_blocks；
        2. 轻快照写入 output_snapshot，重内容写入 analytics_result_repository；
        3. 记录关键阶段耗时到 timing_breakdown。
        """

        timing: dict[str, float] = {}

        metric_definition = self._get_cached_metric(plan.slots.get("metric"))
        if metric_definition is None:
            raise AppException(
                error_code=error_codes.ANALYTICS_QUERY_FAILED,
                message="未识别到可执行指标",
                status_code=400,
                detail={"metric": plan.slots.get("metric")},
            )

        data_source_definition = (
            self.data_source_registry.get_data_source(plan.data_source)
            if self.data_source_registry is not None
            else self.schema_registry.get_data_source(plan.data_source)
        )
        table_definition = self.schema_registry.get_table_definition(
            table_name=metric_definition.table_name,
            data_source=data_source_definition.key,
        )

        permission_check_result = self._assert_metric_permission(
            metric_definition=metric_definition,
            user_context=user_context,
        )
        data_source_permission_result = self._assert_data_source_permission(
            data_source_definition=data_source_definition,
            user_context=user_context,
        )
        permission_check_result["data_source"] = data_source_permission_result
        data_scope_result = self._build_data_scope_result(
            table_definition=table_definition,
            user_context=user_context,
        )

        try:
            t0 = time.monotonic()

            self.task_run_repository.update_task_run(
                task_run["run_id"],
                sub_status="building_sql",
                context_snapshot={
                    "slots": plan.slots,
                    "planning_source": plan.planning_source,
                    "confidence": plan.confidence,
                },
            )
            sql_bundle = self.sql_builder.build(
                plan.slots,
                department_code=user_context.department_code,
            )
            timing["sql_build_ms"] = round((time.monotonic() - t0) * 1000, 1)

            t1 = time.monotonic()
            self.task_run_repository.update_task_run(
                task_run["run_id"],
                sub_status="checking_sql",
            )
            guard_result = self.sql_guard.validate(
                sql_bundle["generated_sql"],
                allowed_tables=self._get_cached_allowed_tables(sql_bundle["data_source"]),
                required_filter_column=table_definition.department_filter_column,
                required_filter_value=user_context.department_code if table_definition.department_filter_column else None,
            )
            timing["sql_guard_ms"] = round((time.monotonic() - t1) * 1000, 1)

            if not guard_result.is_safe or not guard_result.checked_sql:
                blocked_audit = self.sql_audit_repository.create_audit(
                    run_id=task_run["run_id"],
                    user_id=user_context.user_id,
                    db_type=data_source_definition.db_type,
                    metric_scope=sql_bundle["metric_scope"],
                    generated_sql=sql_bundle["generated_sql"],
                    checked_sql=guard_result.checked_sql,
                    is_safe=False,
                    blocked_reason=guard_result.blocked_reason,
                    execution_status="blocked",
                    row_count=None,
                    latency_ms=None,
                    metadata={
                        **sql_bundle["builder_metadata"],
                        "data_source": sql_bundle["data_source"],
                    },
                )
                self.task_run_repository.update_task_run(
                    task_run["run_id"],
                    status="failed",
                    sub_status="checking_sql",
                    error_code=error_codes.SQL_GUARD_BLOCKED,
                    error_message=guard_result.blocked_reason,
                    finished_at=datetime.now(timezone.utc),
                )
                raise AppException(
                    error_code=error_codes.SQL_GUARD_BLOCKED,
                    message="SQL 安全检查未通过",
                    status_code=400,
                    detail={
                        "blocked_reason": guard_result.blocked_reason,
                        "audit_info": self._build_audit_info(blocked_audit),
                        "governance_detail": guard_result.governance_detail,
                    },
                )

            t2 = time.monotonic()
            self.task_run_repository.update_task_run(
                task_run["run_id"],
                status="executing",
                sub_status="running_sql",
            )
            execution_result = self.sql_gateway.execute_readonly_query(
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
            timing["sql_execute_ms"] = round((time.monotonic() - t2) * 1000, 1)

            audit_record = self.sql_audit_repository.create_audit(
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
            self.task_run_repository.update_task_run(
                task_run["run_id"],
                sub_status="explaining_result",
            )
            masking_result = self.data_masking_service.apply(
                rows=execution_result.rows,
                columns=execution_result.columns,
                visible_fields=self._get_cached_visible_fields(
                    table_name=table_definition.name,
                    data_source=execution_result.data_source,
                ),
                sensitive_fields=self._get_cached_sensitive_fields(
                    table_name=table_definition.name,
                    data_source=execution_result.data_source,
                ),
                masked_fields=self._get_cached_masked_fields(
                    table_name=table_definition.name,
                    data_source=execution_result.data_source,
                ),
                user_permissions=user_context.permissions,
            )
            timing["masking_ms"] = round((time.monotonic() - t3) * 1000, 1)

            summary = self._build_summary(plan.slots, execution_result)

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
            audit_info = self._build_audit_info(
                audit_record,
                permission_check_result=permission_check_result,
                data_scope_result=data_scope_result,
                masking_result=masking_result,
                effective_filters=effective_filters,
                guard_result=guard_result,
            )

            # 按 output_mode 延迟生成 chart_spec / insight_cards / report_blocks
            chart_spec = None
            insight_cards: list[dict] = []
            report_blocks: list[dict] = []

            if output_mode in {"standard", "full"}:
                t4 = time.monotonic()
                chart_spec = self._build_chart_spec(
                    slots=plan.slots,
                    execution_result=execution_result,
                    metric_name=plan.slots["metric"],
                )
                insight_cards = self.insight_builder.build(
                    slots=plan.slots,
                    rows=masking_result.rows,
                    row_count=execution_result.row_count,
                )
                timing["insight_ms"] = round((time.monotonic() - t4) * 1000, 1)

            if output_mode == "full":
                t5 = time.monotonic()
                report_blocks = self.report_formatter.build(
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
                )
                timing["report_ms"] = round((time.monotonic() - t5) * 1000, 1)

            # 构造统一结果对象
            analytics_result = AnalyticsResult(
                run_id=task_run["run_id"],
                trace_id=task_run["trace_id"],
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
                    "table_whitelist": self._get_cached_allowed_tables(sql_bundle["data_source"]),
                    "field_whitelist_reserved": self._get_cached_field_whitelist(
                        table_name=metric_definition.table_name,
                        data_source=sql_bundle["data_source"],
                    ),
                    "governance_detail": guard_result.governance_detail,
                },
                permission_check_result=permission_check_result,
                data_scope_result=data_scope_result,
                effective_filters=effective_filters,
                audit_info=audit_info,
                sql_explain=sql_explain,
                timing_breakdown=timing,
            )

            # 轻快照写入 output_snapshot
            lightweight_snapshot = analytics_result.to_lightweight_snapshot()
            self.task_run_repository.update_task_run(
                task_run["run_id"],
                status="succeeded",
                sub_status="explaining_result",
                output_snapshot=lightweight_snapshot,
                finished_at=datetime.now(timezone.utc),
            )

            # 重内容写入 analytics_result_repository
            self.analytics_result_repository.save_heavy_result(
                run_id=task_run["run_id"],
                heavy_result=analytics_result.to_heavy_result(),
            )

            self.conversation_repository.add_message(
                conversation_id=conversation_id,
                role="assistant",
                message_type="analytics_answer",
                content=summary,
                related_run_id=task_run["run_id"],
                structured_content={
                    "sql_preview": guard_result.checked_sql,
                    "chart_spec": chart_spec,
                },
            )
            self.conversation_repository.upsert_memory(
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

            # 按 output_mode 返回分级视图
            if output_mode == "lite":
                response_data = analytics_result.to_lite_view()
            elif output_mode == "standard":
                response_data = analytics_result.to_standard_view()
            else:
                response_data = analytics_result.to_full_view()

            return {
                "data": response_data,
                "meta": build_response_meta(
                    conversation_id=conversation_id,
                    run_id=task_run["run_id"],
                    status="succeeded",
                    sub_status="explaining_result",
                    is_async=False,
                    need_clarification=False,
                ),
            }
        except AppException:
            raise
        except Exception as exc:  # pragma: no cover - 作为兜底保护
            self.sql_audit_repository.create_audit(
                run_id=task_run["run_id"],
                user_id=user_context.user_id,
                db_type=data_source_definition.db_type,
                metric_scope=plan.slots.get("metric"),
                generated_sql="",
                checked_sql=None,
                is_safe=False,
                blocked_reason=str(exc),
                execution_status="failed",
                row_count=None,
                latency_ms=None,
                metadata={
                    "stage": "analytics_service_runtime",
                    "data_source": plan.data_source,
                },
            )
            self.task_run_repository.update_task_run(
                task_run["run_id"],
                status="failed",
                sub_status="running_sql",
                error_code=error_codes.SQL_EXECUTION_FAILED,
                error_message=str(exc),
                finished_at=datetime.now(timezone.utc),
            )
            raise AppException(
                error_code=error_codes.SQL_EXECUTION_FAILED,
                message="经营分析执行失败",
                status_code=500,
                detail={"reason": str(exc)},
            ) from exc

    def _get_cached_metric(self, metric_name: str | None):
        """通过缓存获取指标定义。"""

        cache_key = f"metric:{metric_name}"
        return self.registry_cache.get_or_compute(
            cache_key,
            lambda: self.metric_catalog.resolve_metric(metric_name),
        )

    def _get_cached_allowed_tables(self, data_source: str) -> list[str]:
        """通过缓存获取表白名单。"""

        cache_key = f"allowed_tables:{data_source}"
        return self.registry_cache.get_or_compute(
            cache_key,
            lambda: self.schema_registry.get_allowed_tables(data_source=data_source),
        )

    def _get_cached_visible_fields(self, table_name: str, data_source: str) -> list[str]:
        """通过缓存获取可见字段。"""

        cache_key = f"visible_fields:{data_source}:{table_name}"
        return self.registry_cache.get_or_compute(
            cache_key,
            lambda: self.schema_registry.get_table_visible_fields(table_name=table_name, data_source=data_source),
        )

    def _get_cached_sensitive_fields(self, table_name: str, data_source: str) -> list[str]:
        """通过缓存获取敏感字段。"""

        cache_key = f"sensitive_fields:{data_source}:{table_name}"
        return self.registry_cache.get_or_compute(
            cache_key,
            lambda: self.schema_registry.get_table_sensitive_fields(table_name=table_name, data_source=data_source),
        )

    def _get_cached_masked_fields(self, table_name: str, data_source: str) -> list[str]:
        """通过缓存获取脱敏字段。"""

        cache_key = f"masked_fields:{data_source}:{table_name}"
        return self.registry_cache.get_or_compute(
            cache_key,
            lambda: self.schema_registry.get_table_masked_fields(table_name=table_name, data_source=data_source),
        )

    def _get_cached_field_whitelist(self, table_name: str, data_source: str) -> list[str]:
        """通过缓存获取字段白名单。"""

        cache_key = f"field_whitelist:{data_source}:{table_name}"
        return self.registry_cache.get_or_compute(
            cache_key,
            lambda: self.schema_registry.get_table_field_whitelist(table_name=table_name, data_source=data_source),
        )

    def _assert_metric_permission(self, *, metric_definition, user_context: UserContext) -> dict:
        """执行最小指标级权限校验。"""

        required_permissions = metric_definition.required_permissions or ["analytics:query"]
        if not self._has_all_permissions(user_context.permissions, required_permissions):
            raise AppException(
                error_code=error_codes.ANALYTICS_METRIC_PERMISSION_DENIED,
                message="当前用户无权查询该经营指标",
                status_code=403,
                detail={
                    "metric": metric_definition.name,
                    "required_permissions": required_permissions,
                    "missing_permissions": [
                        permission
                        for permission in required_permissions
                        if permission not in set(user_context.permissions or [])
                    ],
                },
            )

        if metric_definition.allowed_roles and not set(user_context.roles or []).intersection(metric_definition.allowed_roles):
            raise AppException(
                error_code=error_codes.ANALYTICS_METRIC_PERMISSION_DENIED,
                message="当前用户无权查询该经营指标",
                status_code=403,
                detail={
                    "metric": metric_definition.name,
                    "allowed_roles": metric_definition.allowed_roles,
                    "current_roles": user_context.roles,
                },
            )

        if metric_definition.allowed_departments and user_context.department_code not in set(metric_definition.allowed_departments):
            raise AppException(
                error_code=error_codes.ANALYTICS_DATA_SCOPE_DENIED,
                message="当前用户部门范围不允许访问该经营指标",
                status_code=403,
                detail={
                    "metric": metric_definition.name,
                    "allowed_departments": metric_definition.allowed_departments,
                    "current_department": user_context.department_code,
                },
            )

        return {
            "metric": metric_definition.name,
            "allowed": True,
            "required_permissions": required_permissions,
            "allowed_roles": metric_definition.allowed_roles,
            "allowed_departments": metric_definition.allowed_departments,
            "sensitivity_level": metric_definition.sensitivity_level,
        }

    def _assert_data_source_permission(self, *, data_source_definition, user_context: UserContext) -> dict:
        """执行最小数据源级权限校验。"""

        required_permissions = data_source_definition.required_permissions
        if required_permissions and not self._has_all_permissions(
            user_context.permissions,
            required_permissions,
        ):
            raise AppException(
                error_code=error_codes.ANALYTICS_DATA_SOURCE_PERMISSION_DENIED,
                message="当前用户无权访问该经营分析数据源",
                status_code=403,
                detail={
                    "data_source": data_source_definition.key,
                    "required_permissions": required_permissions,
                },
            )

        if data_source_definition.allowed_roles and not set(user_context.roles or []).intersection(data_source_definition.allowed_roles):
            raise AppException(
                error_code=error_codes.ANALYTICS_DATA_SOURCE_PERMISSION_DENIED,
                message="当前用户角色无权访问该经营分析数据源",
                status_code=403,
                detail={
                    "data_source": data_source_definition.key,
                    "allowed_roles": data_source_definition.allowed_roles,
                    "current_roles": user_context.roles,
                },
            )

        return {
            "data_source": data_source_definition.key,
            "allowed": True,
            "required_permissions": required_permissions,
            "allowed_roles": data_source_definition.allowed_roles,
        }

    def _build_data_scope_result(self, *, table_definition, user_context: UserContext) -> dict:
        """构造当前经营分析的数据范围治理结果。"""

        if table_definition.department_filter_column and not user_context.department_code:
            raise AppException(
                error_code=error_codes.ANALYTICS_DATA_SCOPE_DENIED,
                message="当前分析表要求部门范围过滤，但用户上下文缺少部门信息",
                status_code=403,
                detail={
                    "required_filter_column": table_definition.department_filter_column,
                },
            )

        return {
            "scope_type": "single_department" if table_definition.department_filter_column else "global",
            "department_filter_column": table_definition.department_filter_column,
            "effective_department": user_context.department_code if table_definition.department_filter_column else None,
            "enforced": bool(table_definition.department_filter_column),
        }

    def _has_any_permission(self, user_permissions: list[str], required_permissions: list[str]) -> bool:
        """判断用户是否至少满足一项权限。"""

        if not required_permissions:
            return True
        permission_set = set(user_permissions or [])
        return any(permission in permission_set for permission in required_permissions)

    def _has_all_permissions(self, user_permissions: list[str], required_permissions: list[str]) -> bool:
        """判断用户是否满足全部权限。"""

        if not required_permissions:
            return True
        permission_set = set(user_permissions or [])
        return all(permission in permission_set for permission in required_permissions)

    def _build_summary(self, slots: dict, execution_result) -> str:
        """把结构化查询结果转换成最小业务解释文本。"""

        metric = slots["metric"]
        time_label = slots["time_range"].get("label", "目标时间范围")
        org_scope = slots.get("org_scope")
        group_by = slots.get("group_by")
        rows = execution_result.rows

        scope_text = org_scope["value"] if org_scope else "全部范围"
        if not rows:
            return f'在{time_label}的{scope_text}范围内，未查询到与"{metric}"相关的数据。'

        if slots.get("compare_target") in {"mom", "yoy"} and group_by not in {"region", "station", "month"}:
            current_value = rows[0].get("current_value")
            compare_value = rows[0].get("compare_value")
            compare_label = "环比" if slots.get("compare_target") == "mom" else "同比"
            return (
                f"{time_label}{scope_text}的{metric}当前值为 {current_value}，"
                f"{compare_label}对比值为 {compare_value}。"
            )

        if group_by in {"region", "station", "month"}:
            analysis_name = "趋势" if group_by == "month" else "排名"
            return (
                f'已完成"{metric}"在{time_label}范围内的{analysis_name}查询，'
                f"当前返回 {execution_result.row_count} 行结果，可继续做对比或下钻分析。"
            )

        total_value = rows[0].get("total_value")
        return f"{time_label}{scope_text}的{metric}汇总值为 {total_value}。"

    def _build_chart_spec(self, *, slots: dict, execution_result, metric_name: str) -> dict | None:
        """生成前端可直接消费的最小图表描述。"""

        rows = execution_result.rows
        if not rows:
            return None

        group_by = slots.get("group_by")
        compare_target = slots.get("compare_target")
        if group_by == "month":
            return {
                "chart_type": "line",
                "title": f"{metric_name}按月趋势",
                "x_field": "month",
                "y_field": "current_value" if compare_target in {"mom", "yoy"} else "total_value",
                "series_field": None,
                "dataset_ref": "main_result",
                "data_mapping": {
                    "primary_series": "current_value" if compare_target in {"mom", "yoy"} else "total_value",
                    "secondary_series": "compare_value" if compare_target in {"mom", "yoy"} else None,
                },
            }
        if group_by in {"region", "station"}:
            return {
                "chart_type": "ranking_bar" if slots.get("top_n") else "bar",
                "title": f"{metric_name}{'对比' if compare_target else ''}{group_by}分布",
                "x_field": group_by,
                "y_field": "current_value" if compare_target in {"mom", "yoy"} else "total_value",
                "series_field": None,
                "dataset_ref": "main_result",
                "data_mapping": {
                    "primary_series": "current_value" if compare_target in {"mom", "yoy"} else "total_value",
                    "secondary_series": "compare_value" if compare_target in {"mom", "yoy"} else None,
                },
            }
        return {
            "chart_type": "pie" if execution_result.row_count > 1 else "stacked_bar",
            "title": f"{metric_name}汇总",
            "x_field": None,
            "y_field": "current_value" if compare_target in {"mom", "yoy"} else "total_value",
            "series_field": None,
            "dataset_ref": "main_result",
            "data_mapping": {
                "primary_series": "current_value" if compare_target in {"mom", "yoy"} else "total_value",
                "secondary_series": "compare_value" if compare_target in {"mom", "yoy"} else None,
            },
        }

    def _build_audit_info(
        self,
        audit_record: dict | None,
        *,
        permission_check_result: dict | None = None,
        data_scope_result: dict | None = None,
        masking_result: DataMaskingResult | None = None,
        effective_filters: dict | None = None,
        guard_result=None,
    ) -> dict | None:
        """构造前端可展示的最小审计摘要。"""

        if audit_record is None:
            return None
        return {
            "execution_status": audit_record.get("execution_status"),
            "is_safe": audit_record.get("is_safe"),
            "row_count": audit_record.get("row_count"),
            "latency_ms": audit_record.get("latency_ms"),
            "db_type": audit_record.get("db_type"),
            "blocked_reason": audit_record.get("blocked_reason"),
            "permission_check_result": permission_check_result,
            "data_scope_result": data_scope_result,
            "masked_fields": masking_result.masked_fields if masking_result is not None else [],
            "effective_filters": effective_filters or {},
            "governance_decision": {
                "action": masking_result.governance_decision if masking_result is not None else "no_masking_needed",
                "guard_stage": getattr(guard_result, "governance_detail", None),
            },
        }
