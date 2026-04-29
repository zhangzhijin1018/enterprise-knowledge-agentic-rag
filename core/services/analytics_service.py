"""经营分析主链路 Service。

本 Service 的职责不是做最终版 BI / 自由 NL2SQL，
而是把当前阶段企业经营分析的稳定主链路编排清楚：

用户问题
-> Planner 做意图识别与槽位提取
-> 缺槽位则澄清
-> 满足最小条件后构造 schema-aware SQL
-> SQL Guard 做安全检查与治理
-> 通过 SQL Gateway / SQL MCP-compatible server 执行只读查询
-> 生成最小业务解释、图表描述、洞察卡片
-> 记录 SQL Audit

关键设计原则：
1. router 只收参与返回，业务编排都在这里；
2. 不能跳过槽位化直接自由生成 SQL；
3. 不能跳过 SQL Guard；
4. 不能只执行不审计；
5. 权限、数据源治理、表白名单等基础治理必须在这里显式落点。
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.agent.control_plane.analytics_planner import AnalyticsPlan, AnalyticsPlanner
from core.agent.control_plane.sql_builder import SQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
from core.analytics.data_masking import DataMaskingResult, DataMaskingService
from core.analytics.insight_builder import InsightBuilder
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.report_formatter import ReportFormatter
from core.analytics.schema_registry import SchemaRegistry
from core.common import error_codes
from core.common.exceptions import AppException
from core.common.response import build_response_meta
from core.repositories.conversation_repository import ConversationRepository
from core.repositories.sql_audit_repository import SQLAuditRepository
from core.repositories.task_run_repository import TaskRunRepository
from core.security.auth import UserContext
from core.tools.mcp.sql_mcp_contracts import SQLReadQueryRequest
from core.tools.sql.sql_gateway import SQLGateway


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
        data_masking_service: DataMaskingService | None = None,
        insight_builder: InsightBuilder | None = None,
        report_formatter: ReportFormatter | None = None,
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
        self.data_masking_service = data_masking_service or DataMaskingService()
        self.insight_builder = insight_builder or InsightBuilder()
        self.report_formatter = report_formatter or ReportFormatter()

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
            structured_content={"output_mode": output_mode},
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
                "output_mode": output_mode,
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
            need_sql_explain=need_sql_explain,
            user_context=user_context,
        )

    def get_run_detail(self, *, run_id: str, user_context: UserContext) -> dict:
        """读取经营分析运行详情。"""

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

        slot_snapshot = self.task_run_repository.get_slot_snapshot(run_id) or {}
        latest_sql_audit = self.sql_audit_repository.get_latest_by_run_id(run_id)
        output_snapshot = task_run.get("output_snapshot") or {}
        return {
            "data": {
                "run_id": task_run["run_id"],
                "conversation_id": task_run["conversation_id"],
                "task_type": task_run["task_type"],
                "route": task_run["route"],
                "status": task_run["status"],
                "sub_status": task_run["sub_status"],
                "trace_id": task_run["trace_id"],
                "slots": slot_snapshot.get("collected_slots", {}),
                "latest_sql_audit": latest_sql_audit,
                "output_snapshot": output_snapshot,
                "summary": output_snapshot.get("summary"),
                "tables": output_snapshot.get("tables", []),
                "sql_explain": output_snapshot.get("sql_explain"),
                "sql_preview": output_snapshot.get("sql_preview"),
                "safety_check_result": output_snapshot.get("safety_check_result"),
                "metric_scope": output_snapshot.get("metric_scope"),
                "data_source": output_snapshot.get("data_source"),
                "row_count": output_snapshot.get("row_count"),
                "latency_ms": output_snapshot.get("latency_ms"),
                "compare_target": output_snapshot.get("compare_target"),
                "group_by": output_snapshot.get("group_by"),
                "chart_spec": output_snapshot.get("chart_spec"),
                "insight_cards": output_snapshot.get("insight_cards", []),
                "report_blocks": output_snapshot.get("report_blocks", []),
                "audit_info": output_snapshot.get("audit_info"),
                "permission_check_result": output_snapshot.get("permission_check_result"),
                "data_scope_result": output_snapshot.get("data_scope_result"),
                "masked_fields": output_snapshot.get("masked_fields", []),
                "effective_filters": output_snapshot.get("effective_filters", {}),
                "governance_decision": output_snapshot.get("governance_decision"),
            },
            "meta": build_response_meta(
                conversation_id=task_run["conversation_id"],
                run_id=task_run["run_id"],
                status=task_run["status"],
                sub_status=task_run["sub_status"],
                is_async=False,
            ),
        }

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
        need_sql_explain: bool,
        user_context: UserContext,
    ) -> dict:
        """执行经营分析主链路。"""

        metric_definition = self.metric_catalog.resolve_metric(plan.slots.get("metric"))
        if metric_definition is None:
            raise AppException(
                error_code=error_codes.ANALYTICS_QUERY_FAILED,
                message="未识别到可执行指标",
                status_code=400,
                detail={"metric": plan.slots.get("metric")},
            )

        data_source_definition = self.schema_registry.get_data_source(plan.data_source)
        table_definition = self.schema_registry.get_table_definition(
            table_name=metric_definition.table_name,
            data_source=data_source_definition.key,
        )

        # 治理前置说明：
        # - 指标级权限决定“这个人能不能看这个业务指标”；
        # - 数据源级权限决定“这个人能不能访问这类数据库/数仓”；
        # - 表白名单 / 字段白名单决定“即使生成了 SQL，也只能落到受控物理范围”。
        # 这些校验必须在真正执行 SQL 之前完成，不能等查完再补救。
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

            self.task_run_repository.update_task_run(
                task_run["run_id"],
                sub_status="checking_sql",
            )
            guard_result = self.sql_guard.validate(
                sql_bundle["generated_sql"],
                allowed_tables=self.schema_registry.get_allowed_tables(data_source=sql_bundle["data_source"]),
                required_filter_column=table_definition.department_filter_column,
                required_filter_value=user_context.department_code if table_definition.department_filter_column else None,
            )

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

            self.task_run_repository.update_task_run(
                task_run["run_id"],
                sub_status="explaining_result",
            )
            masking_result = self.data_masking_service.apply(
                rows=execution_result.rows,
                columns=execution_result.columns,
                visible_fields=self.schema_registry.get_table_visible_fields(
                    table_name=table_definition.name,
                    data_source=execution_result.data_source,
                ),
                sensitive_fields=self.schema_registry.get_table_sensitive_fields(
                    table_name=table_definition.name,
                    data_source=execution_result.data_source,
                ),
                masked_fields=self.schema_registry.get_table_masked_fields(
                    table_name=table_definition.name,
                    data_source=execution_result.data_source,
                ),
                user_permissions=user_context.permissions,
            )
            summary = self._build_summary(plan.slots, execution_result)
            tables = [
                {
                    "name": "main_result",
                    "columns": masking_result.columns,
                    "rows": [list(row.values()) for row in masking_result.rows],
                }
            ]
            sql_explain = None
            if need_sql_explain:
                sql_explain = (
                    "当前阶段采用 schema-aware 受控模板 SQL。"
                    f"主指标={plan.slots['metric']}，时间范围={plan.slots['time_range'].get('label')}，"
                    f"group_by={plan.slots.get('group_by') or 'none'}，"
                    f"compare_target={plan.slots.get('compare_target') or 'none'}，"
                    f"data_source={execution_result.data_source}。"
                )

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
            report_blocks = self.report_formatter.build(
                summary=summary,
                insight_cards=insight_cards,
                tables=tables,
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

            output_snapshot = {
                "summary": summary,
                "tables": tables,
                "sql_explain": sql_explain,
                "sql_preview": guard_result.checked_sql,
                "safety_check_result": {
                    "is_safe": guard_result.is_safe,
                    "blocked_reason": guard_result.blocked_reason,
                    "table_whitelist": self.schema_registry.get_allowed_tables(
                        data_source=sql_bundle["data_source"]
                    ),
                    "field_whitelist_reserved": self.schema_registry.get_table_field_whitelist(
                        table_name=metric_definition.table_name,
                        data_source=sql_bundle["data_source"],
                    ),
                    "governance_detail": guard_result.governance_detail,
                },
                "metric_scope": sql_bundle["metric_scope"],
                "data_source": execution_result.data_source,
                "row_count": execution_result.row_count,
                "latency_ms": execution_result.latency_ms,
                "compare_target": plan.slots.get("compare_target"),
                "group_by": plan.slots.get("group_by"),
                "chart_spec": chart_spec,
                "insight_cards": insight_cards,
                "report_blocks": report_blocks,
                "audit_info": audit_info,
                "permission_check_result": permission_check_result,
                "data_scope_result": data_scope_result,
                "masked_fields": masking_result.masked_fields,
                "effective_filters": effective_filters,
                "governance_decision": governance_decision,
                "slots": plan.slots,
                "planning_source": plan.planning_source,
            }
            self.task_run_repository.update_task_run(
                task_run["run_id"],
                status="succeeded",
                sub_status="explaining_result",
                output_snapshot=output_snapshot,
                finished_at=datetime.now(timezone.utc),
            )

            self.conversation_repository.add_message(
                conversation_id=conversation_id,
                role="assistant",
                message_type="analytics_answer",
                content=summary,
                related_run_id=task_run["run_id"],
                structured_content={
                    "tables": tables,
                    "sql_explain": sql_explain,
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

            return {
                "data": {
                    "summary": summary,
                    "tables": tables,
                    "sql_explain": sql_explain,
                    "sql_preview": guard_result.checked_sql,
                    "safety_check_result": output_snapshot["safety_check_result"],
                    "metric_scope": sql_bundle["metric_scope"],
                    "data_source": execution_result.data_source,
                    "row_count": execution_result.row_count,
                    "latency_ms": execution_result.latency_ms,
                    "compare_target": plan.slots.get("compare_target"),
                    "group_by": plan.slots.get("group_by"),
                    "chart_spec": chart_spec,
                    "insight_cards": insight_cards,
                    "report_blocks": report_blocks,
                    "audit_info": audit_info,
                    "permission_check_result": permission_check_result,
                    "data_scope_result": data_scope_result,
                    "masked_fields": masking_result.masked_fields,
                    "effective_filters": effective_filters,
                    "governance_decision": governance_decision,
                },
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

    def _assert_metric_permission(self, *, metric_definition, user_context: UserContext) -> dict:
        """执行最小指标级权限校验。

        当前阶段先采用“指标定义声明权限 + 用户上下文显式权限集合”的简单模型：
        - required_permissions 决定“查这个指标至少需要哪些权限”；
        - allowed_roles 决定“哪些角色默认允许访问这个指标”；
        - allowed_departments 决定“哪些部门允许访问这个指标”。

        经营分析不能默认所有指标都可查：
        - 发电量、产量通常属于一般经营指标；
        - 收入、成本、利润往往更敏感；
        - 因此必须把 metric 级治理做成显式结构，而不是靠前端按钮控制。
        """

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
        """执行最小数据源级权限校验。

        为什么经营分析必须做数据源级治理：
        - 同一个系统未来会接多个库、多个数仓、多个权限域；
        - 即使指标相同，不同数据源的敏感级别和可见范围也可能完全不同；
        - 所以不能只判断“是不是经营分析用户”，还要判断“能不能访问这个 data_source”。
        """

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
            return f"在{time_label}的{scope_text}范围内，未查询到与“{metric}”相关的数据。"

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
                f"已完成“{metric}”在{time_label}范围内的{analysis_name}查询，"
                f"当前返回 {execution_result.row_count} 行结果，可继续做对比或下钻分析。"
            )

        total_value = rows[0].get("total_value")
        return f"{time_label}{scope_text}的{metric}汇总值为 {total_value}。"

    def _build_chart_spec(self, *, slots: dict, execution_result, metric_name: str) -> dict | None:
        """生成前端可直接消费的最小图表描述。

        当前阶段不生成真实图片，而是返回结构化 chart_spec：
        - 前端可以按 type / x_field / y_field / title 直接渲染；
        - 后续如果要接更复杂 BI 图层，也能继续沿用这层描述。
        """

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
