"""经营分析最小主链路 Service。

本 Service 的定位不是最终版 BI / NL2SQL 引擎，
而是把“经营分析最小闭环”先打通并且纳入现有运行态体系：

用户问题
-> Planner 做意图识别与槽位提取
-> 缺槽位则澄清
-> 满足最小条件后构造 SQL
-> SQL Guard 做安全检查
-> 只读执行
-> 结果解释
-> SQL 审计

关键设计原则：
1. router 只收参与返回，业务编排都在这里；
2. 不能跳过槽位化直接自由生成 SQL；
3. 不能跳过 SQL Guard；
4. 不能只执行不审计。
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.agent.control_plane.sql_builder import SQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
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
    """经营分析最小业务编排层。"""

    def __init__(
        self,
        conversation_repository: ConversationRepository,
        task_run_repository: TaskRunRepository,
        sql_audit_repository: SQLAuditRepository,
        analytics_planner: AnalyticsPlanner,
        sql_builder: SQLBuilder,
        sql_guard: SQLGuard,
        sql_gateway: SQLGateway,
    ) -> None:
        self.conversation_repository = conversation_repository
        self.task_run_repository = task_run_repository
        self.sql_audit_repository = sql_audit_repository
        self.analytics_planner = analytics_planner
        self.sql_builder = sql_builder
        self.sql_guard = sql_guard
        self.sql_gateway = sql_gateway

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
            clarification = self.task_run_repository.create_clarification_event(
                run_id=task_run["run_id"],
                conversation_id=conversation["conversation_id"],
                question_text=plan.clarification_question or "请补充经营分析关键条件",
                target_slots=plan.clarification_target_slots,
            )
            self.task_run_repository.update_task_run(
                task_run["run_id"],
                status="awaiting_user_clarification",
                sub_status="awaiting_slot_fill",
                context_snapshot={"slots": plan.slots, "missing_slots": plan.missing_slots},
            )
            self.conversation_repository.add_message(
                conversation_id=conversation["conversation_id"],
                role="assistant",
                message_type="clarification",
                content=clarification["question_text"],
                related_run_id=task_run["run_id"],
                structured_content={
                    "clarification_id": clarification["clarification_id"],
                    "target_slots": clarification["target_slots"],
                },
            )
            return {
                "data": {
                    "clarification": {
                        "clarification_id": clarification["clarification_id"],
                        "question": clarification["question_text"],
                        "target_slots": clarification["target_slots"],
                    }
                },
                "meta": build_response_meta(
                    conversation_id=conversation["conversation_id"],
                    run_id=task_run["run_id"],
                    status="awaiting_user_clarification",
                    sub_status="awaiting_slot_fill",
                    need_clarification=True,
                    is_async=False,
                ),
            }

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
                "output_snapshot": task_run.get("output_snapshot") or {},
                "summary": (task_run.get("output_snapshot") or {}).get("summary"),
                "tables": (task_run.get("output_snapshot") or {}).get("tables", []),
                "sql_explain": (task_run.get("output_snapshot") or {}).get("sql_explain"),
                "sql_preview": (task_run.get("output_snapshot") or {}).get("sql_preview"),
                "safety_check_result": (task_run.get("output_snapshot") or {}).get("safety_check_result"),
                "metric_scope": (task_run.get("output_snapshot") or {}).get("metric_scope"),
                "data_source": (task_run.get("output_snapshot") or {}).get("data_source"),
                "row_count": (task_run.get("output_snapshot") or {}).get("row_count"),
                "latency_ms": (task_run.get("output_snapshot") or {}).get("latency_ms"),
                "compare_target": (task_run.get("output_snapshot") or {}).get("compare_target"),
                "group_by": (task_run.get("output_snapshot") or {}).get("group_by"),
            },
            "meta": build_response_meta(
                conversation_id=task_run["conversation_id"],
                run_id=task_run["run_id"],
                status=task_run["status"],
                sub_status=task_run["sub_status"],
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
        plan,
        need_sql_explain: bool,
        user_context: UserContext,
    ) -> dict:
        """执行最小经营分析链路。"""

        try:
            self.task_run_repository.update_task_run(
                task_run["run_id"],
                sub_status="building_sql",
                context_snapshot={"slots": plan.slots},
            )
            sql_bundle = self.sql_builder.build(plan.slots)

            self.task_run_repository.update_task_run(
                task_run["run_id"],
                sub_status="checking_sql",
            )
            guard_result = self.sql_guard.validate(sql_bundle["generated_sql"])
            if not guard_result.is_safe or not guard_result.checked_sql:
                self.sql_audit_repository.create_audit(
                    run_id=task_run["run_id"],
                    user_id=user_context.user_id,
                    db_type="sqlite",
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
                    detail={"blocked_reason": guard_result.blocked_reason},
                )

            self.task_run_repository.update_task_run(
                task_run["run_id"],
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
                )
            )

            self.sql_audit_repository.create_audit(
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
                },
            )

            self.task_run_repository.update_task_run(
                task_run["run_id"],
                sub_status="explaining_result",
            )
            summary = self._build_summary(plan.slots, execution_result)
            tables = [
                {
                    "name": "main_result",
                    "columns": execution_result.columns,
                    "rows": [list(row.values()) for row in execution_result.rows],
                }
            ]
            sql_explain = None
            if need_sql_explain:
                sql_explain = (
                    "当前阶段采用 schema-aware 规则模板 SQL。"
                    f"主指标={plan.slots['metric']}，时间范围={plan.slots['time_range'].get('label')}，"
                    f"group_by={plan.slots.get('group_by') or 'none'}，"
                    f"compare_target={plan.slots.get('compare_target') or 'none'}，"
                    f"data_source={execution_result.data_source}。"
                )

            output_snapshot = {
                "summary": summary,
                "tables": tables,
                "sql_explain": sql_explain,
                "sql_preview": guard_result.checked_sql,
                "safety_check_result": {
                    "is_safe": guard_result.is_safe,
                    "blocked_reason": guard_result.blocked_reason,
                },
                "metric_scope": sql_bundle["metric_scope"],
                "data_source": execution_result.data_source,
                "row_count": execution_result.row_count,
                "latency_ms": execution_result.latency_ms,
                "compare_target": plan.slots.get("compare_target"),
                "group_by": plan.slots.get("group_by"),
                "slots": plan.slots,
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
                },
            )

            return {
                "data": {
                    "summary": summary,
                    "tables": tables,
                    "sql_explain": sql_explain,
                    "sql_preview": guard_result.checked_sql,
                    "safety_check_result": {
                        "is_safe": guard_result.is_safe,
                        "blocked_reason": guard_result.blocked_reason,
                    },
                    "metric_scope": sql_bundle["metric_scope"],
                    "data_source": execution_result.data_source,
                    "row_count": execution_result.row_count,
                    "latency_ms": execution_result.latency_ms,
                    "compare_target": plan.slots.get("compare_target"),
                    "group_by": plan.slots.get("group_by"),
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
                db_type="sqlite",
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

    def _build_summary(self, slots: dict, execution_result: dict) -> str:
        """把结构化查询结果转换成最小业务解释文本。"""

        metric = slots["metric"]
        time_label = slots["time_range"].get("label", "目标时间范围")
        org_scope = slots.get("org_scope")
        group_by = slots.get("group_by")
        rows = execution_result.rows

        scope_text = org_scope["value"] if org_scope else "全部范围"
        if not rows:
            return f"在{time_label}的{scope_text}范围内，未查询到与“{metric}”相关的数据。"

        if group_by in {"region", "station", "month"}:
            return (
                f"已完成“{metric}”在{time_label}范围内的分组查询，"
                f"当前返回 {execution_result.row_count} 行结果，可继续做趋势或对比分析。"
            )

        if slots.get("compare_target") in {"mom", "yoy"}:
            current_value = rows[0].get("current_value")
            compare_value = rows[0].get("compare_value")
            compare_label = "环比" if slots.get("compare_target") == "mom" else "同比"
            return (
                f"{time_label}{scope_text}的{metric}当前值为 {current_value}，"
                f"{compare_label}对比值为 {compare_value}。"
            )

        total_value = rows[0].get("total_value")
        return f"{time_label}{scope_text}的{metric}汇总值为 {total_value}。"
