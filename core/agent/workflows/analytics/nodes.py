"""经营分析 LangGraph 样板节点（v2 纯 Workflow 链路）。

重要变更（v2 链路收敛）：
- 统一主链路：LLMAnalyticsIntentParser -> AnalyticsIntentValidator -> SQL Builder -> SQL Guard -> SQL Gateway -> Summary / Chart / Insight / Report
- ReAct 已删除，不再作为可选能力
- 移除了 _intent_to_plan / _plan_to_intent 转换函数

设计原则：
- 节点职责单一；
- 复用 AnalyticsService 的辅助组件（缓存、Registry等）
- 不再依赖旧版 AnalyticsPlan
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from core.analytics.analytics_result_model import AnalyticsResult
from core.analytics.intent.parser import LLMAnalyticsIntentParser
from core.analytics.intent.schema import AnalyticsIntent, IntentValidationResult
from core.analytics.intent.validator import AnalyticsIntentValidator
from core.analytics.llm_content_generator import (
    MAX_SSE_INLINE_SIZE,
    LLMContentGenerator,
    ParallelLLMGenerator,
    should_inline_result,
)
from core.common import error_codes
from core.common.exceptions import AppException
from core.common.response import build_response_meta
from core.common.sse_progress import RedisSSEProgressTracker, SSEEventType, get_redis_pool
from core.config.settings import get_settings
from core.agent.workflows.analytics.degradation import AnalyticsWorkflowDegradationController
from core.agent.workflows.analytics.retry_policy import AnalyticsWorkflowRetryController
from core.agent.workflows.analytics.state import AnalyticsWorkflowOutcome, AnalyticsWorkflowStage
from core.llm.gateway import LLMGateway, MockLLMGateway
from core.services.analytics_service import AnalyticsService
from core.tools.mcp import SQLGatewayExecutionError
from core.tools.mcp.sql_mcp_contracts import SQLReadQueryRequest

logger = logging.getLogger(__name__)


class AnalyticsWorkflowNodes:
    """经营分析微观工作流节点集合（v2 纯 Workflow 链路）。

    主链路：
    1. analytics_entry：入口校验、创建会话
    2. analytics_plan：调用 LLMAnalyticsIntentParser 生成 AnalyticsIntent
    3. analytics_validate_slots：校验意图是否满足执行条件
    4. analytics_clarify：触发澄清
    5. analytics_build_sql：构建 SQL
    6. analytics_guard_sql：安全校验
    7. analytics_execute_sql：执行查询
    8. analytics_summarize：生成结果
    9. analytics_finish：结束
    """

    def __init__(self, analytics_service: AnalyticsService) -> None:
        self.analytics_service = analytics_service
        self.retry_controller = AnalyticsWorkflowRetryController()
        self.degradation_controller = AnalyticsWorkflowDegradationController()
        self.settings = get_settings()

        # v2：统一意图解析器（使用 MetricResolver）
        self.intent_parser = LLMAnalyticsIntentParser(
            settings=self.settings,
        )
        self.intent_validator = AnalyticsIntentValidator(
            metric_catalog=analytics_service.metric_catalog,
            schema_registry=analytics_service.schema_registry,
        )

        # LLM 内容生成器（并行调用版本）
        self._llm_gateway: LLMGateway | None = None
        self._parallel_llm_generator: ParallelLLMGenerator | None = None

    @property
    def llm_gateway(self) -> LLMGateway:
        """获取 LLM Gateway（懒加载）"""
        if self._llm_gateway is None:
            # 优先使用配置的模型，否则使用 Mock
            if self.settings.llm_api_key and self.settings.llm_api_key != "your-api-key":
                from core.llm.gateway import OpenAICompatibleLLMGateway
                self._llm_gateway = OpenAICompatibleLLMGateway(settings=self.settings)
            else:
                self._llm_gateway = MockLLMGateway()
        return self._llm_gateway

    @property
    def parallel_llm_generator(self) -> ParallelLLMGenerator:
        """获取并行 LLM 生成器（懒加载）"""
        if self._parallel_llm_generator is None:
            model = self.settings.llm_model_name or "qwen-32b"
            self._parallel_llm_generator = ParallelLLMGenerator(
                llm_gateway=self.llm_gateway,
                model=model,
                temperature=0.7,
            )
        return self._parallel_llm_generator

    async def analytics_entry(self, state: dict) -> dict:
        """工作流入口节点。

        职责：
        - 校验 query；
        - 标准化 output_mode；
        - 创建/读取 conversation；
        - 记录用户消息（clarification 恢复场景不重复写原始问题）；
        - 为后续 plan 节点准备 conversation memory。
        """

        # SSE 进度推送
        tracker = state.get("_sse_tracker")
        if tracker:
            await tracker.step("analytics_entry")

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
            conversation = await self.analytics_service._get_or_create_conversation(
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

    async def analytics_plan(self, state: dict) -> dict:
        """规划节点（v2 纯 Workflow 链路）。

        核心职责：
        - 调用 LLMAnalyticsIntentParser 生成结构化 AnalyticsIntent；
        - LLM 只生成结构化 AnalyticsIntent，不生成 SQL。
        """

        # SSE 进度推送
        tracker = state.get("_sse_tracker")
        if tracker:
            await tracker.step("analytics_plan")

        # 调用新版统一意图解析器
        parser_result = self.intent_parser.parse(
            query=state["query"],
            conversation_memory=state.get("conversation_memory"),
            trace_id=state.get("trace_id"),
            run_id=state.get("run_id"),
        )

        intent = parser_result.intent
        state["planning_source"] = parser_result.planning_source

        state["workflow_stage"] = AnalyticsWorkflowStage.ANALYTICS_PLAN
        state["workflow_outcome"] = AnalyticsWorkflowOutcome.CONTINUE
        state["intent"] = intent
        return state

    async def analytics_validate_slots(self, state: dict) -> dict:
        """槽位验证节点（v2 纯 Workflow 链路）。

        职责：
        - 创建 task_run；
        - 保存 slot snapshot；
        - 调用 AnalyticsIntentValidator 进行校验；
        - 判断进入 clarify 还是继续 SQL 执行。
        """

        # SSE 进度推送
        tracker = state.get("_sse_tracker")
        if tracker:
            await tracker.step("analytics_validate_slots")

        intent = state.get("intent")
        conversation = state["conversation"]
        user_context = state["user_context"]

        # 调用意图校验器
        validation_result = self.intent_validator.validate(
            intent=intent,
            user_context=user_context,
        )

        # 保存校验结果到 state
        state["intent_validation_result"] = validation_result.model_dump() if validation_result else None

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
                input_snapshot=self.analytics_service.snapshot_builder.build_input_snapshot(
                    query=state["query"],
                    conversation_id=conversation["conversation_id"],
                    output_mode=state["output_mode"],
                    need_sql_explain=state.get("need_sql_explain", False),
                    user_context=user_context,
                    intent=intent,
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
            # slot_snapshot 属于"恢复执行态"，只保存补槽恢复的必要字段。
            self.analytics_service.task_run_repository.create_slot_snapshot(
                run_id=task_run["run_id"],
                task_type="analytics",
                **self.analytics_service.snapshot_builder.build_slot_snapshot_payload(intent=intent),
            )
        state["task_run"] = task_run
        state["workflow_stage"] = AnalyticsWorkflowStage.ANALYTICS_VALIDATE_SLOTS

        # 根据 Validator 结果决定 workflow 走向
        # v2：直接使用 intent.need_clarification
        if validation_result and not validation_result.valid:
            if validation_result.need_clarification:
                state["clarification_needed"] = True
                state["workflow_outcome"] = AnalyticsWorkflowOutcome.CLARIFY
                state["next_step"] = "analytics_clarify"
            else:
                state["workflow_outcome"] = AnalyticsWorkflowOutcome.FAIL
        else:
            need_clarify = intent.need_clarification if intent else False
            state["clarification_needed"] = need_clarify
            if need_clarify:
                state["workflow_outcome"] = AnalyticsWorkflowOutcome.CLARIFY
                state["next_step"] = "analytics_clarify"
            else:
                state["workflow_outcome"] = AnalyticsWorkflowOutcome.CONTINUE
                state["next_step"] = "analytics_build_sql"

        return state

    async def analytics_clarify(self, state: dict) -> dict:
        """澄清节点（v2 纯 Workflow 链路）。

        职责：
        - 当最小可执行条件不满足时，生成结构化 clarification 响应；
        - 复用 snapshot_builder 构建澄清事件。
        """

        intent = state.get("intent")

        # 构建澄清事件
        clarification = self.analytics_service.task_run_repository.create_clarification_event(
            run_id=state["task_run"]["run_id"],
            conversation_id=state["conversation_id"],
            **self.analytics_service.snapshot_builder.build_clarification_event_payload(intent=intent),
        )

        # 更新 task_run 状态
        self.analytics_service.task_run_repository.update_task_run(
            state["task_run"]["run_id"],
            status="awaiting_user_clarification",
            sub_status="awaiting_slot_fill",
            context_snapshot=self.analytics_service.snapshot_builder.build_context_snapshot(
                slots=intent.missing_fields if intent else [],
                missing_slots=intent.missing_fields if intent else [],
                clarification_type="missing_slots" if intent and intent.missing_fields else None,
                resume_step="resume_after_analytics_slot_fill",
            ),
        )

        # 添加 assistant 消息
        self.analytics_service.conversation_repository.add_message(
            conversation_id=state["conversation_id"],
            role="assistant",
            message_type="clarification",
            content=clarification["question_text"],
            related_run_id=state["task_run"]["run_id"],
            structured_content={
                "clarification_id": clarification["clarification_id"],
                "target_slots": clarification["target_slots"],
            },
        )

        state["final_response"] = {
            "data": {
                "clarification": {
                    "clarification_id": clarification["clarification_id"],
                    "question": clarification["question_text"],
                    "target_slots": clarification["target_slots"],
                }
            },
            "meta": {
                "status": "awaiting_user_clarification",
                "sub_status": "awaiting_slot_fill",
                "run_id": state["task_run"]["run_id"],
                "trace_id": state["trace_id"],
                "conversation_id": state["conversation_id"],
            },
        }
        state["workflow_stage"] = AnalyticsWorkflowStage.ANALYTICS_CLARIFY
        state["workflow_outcome"] = AnalyticsWorkflowOutcome.CLARIFY
        state["clarification_needed"] = True
        return state

    async def analytics_build_sql(self, state: dict) -> dict:
        """SQL 构造节点（新版适配 AnalyticsIntent）。

        职责：
        - 解析 metric / data_source / table definition；
        - 做指标权限和数据源权限检查；
        - 调用 SQLBuilder 生成 schema-aware SQL。

        新版适配：
        - 优先使用 state["intent"] 生成 SQL；
        
        - 支持 simple 和 complex 两种模式。
        """

        # SSE 进度推送
        tracker = state.get("_sse_tracker")
        if tracker:
            await tracker.step("analytics_build_sql")

        t0 = time.monotonic()
        state["workflow_stage"] = AnalyticsWorkflowStage.ANALYTICS_BUILD_SQL
        state["workflow_outcome"] = AnalyticsWorkflowOutcome.CONTINUE
        intent = state.get("intent")
        task_run = state["task_run"]
        user_context = state["user_context"]

        def _build_sql_bundle():
            # 优先使用 intent 生成 SQL
            if intent is not None:
                return self._build_sql_from_intent(
                    intent=intent,
                    user_context=user_context,
                    task_run=task_run,
                )

        # 使用 asyncio.to_thread 将同步操作放到线程池执行
        (
            metric_definition,
            data_source_definition,
            table_definition,
            permission_check_result,
            data_scope_result,
            sql_bundle,
        ) = await asyncio.to_thread(
            self.retry_controller.run,
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



    def _intent_to_slots(self, intent: 'AnalyticsIntent') -> dict:
        """从 AnalyticsIntent 提取 slots 字典（供下游复用）。"""
        slots = {}
        if intent.metric:
            slots['metric'] = intent.metric.metric_name or intent.metric.raw_text
        if intent.time_range:
            time_range_data = {
                'raw_text': intent.time_range.raw_text,
                'type': intent.time_range.type.value if hasattr(intent.time_range.type, 'value') else intent.time_range.type,
            }
            if intent.time_range.value:
                time_range_data['label'] = intent.time_range.value
            if intent.time_range.start:
                time_range_data['start_date'] = intent.time_range.start
            if intent.time_range.end:
                time_range_data['end_date'] = intent.time_range.end
            slots['time_range'] = time_range_data
        if intent.org_scope:
            slots['org_scope'] = {
                'raw_text': intent.org_scope.raw_text,
                'type': intent.org_scope.type.value if hasattr(intent.org_scope.type, 'value') else intent.org_scope.type,
                'name': intent.org_scope.name,
                'code': intent.org_scope.code,
                'value': intent.org_scope.name or intent.org_scope.raw_text,
            }
        if intent.group_by:
            slots['group_by'] = intent.group_by
        if intent.compare_target:
            slots['compare_target'] = (
                intent.compare_target.value if hasattr(intent.compare_target, 'value') else intent.compare_target
            )
        if intent.top_n:
            slots['top_n'] = intent.top_n
        if intent.sort_by:
            slots['sort_by'] = intent.sort_by
        if intent.sort_direction:
            slots['sort_direction'] = (
                intent.sort_direction.value if hasattr(intent.sort_direction, 'value') else intent.sort_direction
            )
        return slots

    def _build_sql_from_intent(
        self,
        intent: "AnalyticsIntent",
        user_context,
        task_run: dict,
    ) -> tuple:
        """从 AnalyticsIntent 构建 SQL（新版主路径）。"""

        from core.agent.control_plane.intent_sql_builder import AnalyticsIntentSQLBuilder

        # 使用新的 AnalyticsIntentSQLBuilder
        intent_sql_builder = AnalyticsIntentSQLBuilder(
            schema_registry=self.analytics_service.schema_registry,
            metric_catalog=self.analytics_service.metric_catalog,
        )

        # 获取指标定义
        metric_name = intent.metric.metric_name if intent.metric else (intent.metric.raw_text if intent.metric else None)
        metric_code = intent.metric.metric_code if intent.metric else None

        if metric_code:
            metric_definition = self.analytics_service.metric_catalog.resolve_metric(metric_code)
            if metric_definition is None and metric_name:
                metric_definition = self.analytics_service.metric_catalog.resolve_metric(metric_name)
        elif metric_name:
            metric_definition = self.analytics_service.metric_catalog.resolve_metric(metric_name)
        else:
            raise AppException(
                error_code=error_codes.ANALYTICS_QUERY_FAILED,
                message="未识别到可执行指标",
                status_code=400,
                detail={"intent": intent.model_dump() if hasattr(intent, "model_dump") else str(intent)},
            )

        if metric_definition is None:
            raise AppException(
                error_code=error_codes.ANALYTICS_QUERY_FAILED,
                message="未识别到可执行指标",
                status_code=400,
                detail={"metric_name": metric_name, "metric_code": metric_code},
            )

        data_source_definition = (
            self.analytics_service.schema_registry.get_data_source(metric_definition.data_source)
        )
        table_definition = self.analytics_service.schema_registry.get_table_definition(
            table_name=metric_definition.table_name,
            data_source=metric_definition.data_source,
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

        # 更新 task_run
        self.analytics_service.task_run_repository.update_task_run(
            task_run["run_id"],
            sub_status="building_sql",
            context_snapshot=self.analytics_service.snapshot_builder.build_context_snapshot(
                slots=self._intent_to_slots(intent),
                planning_source="llm_parser",
                confidence=intent.confidence.overall if intent.confidence else 0.8,
                resume_step="run_sql_pipeline",
            ),
        )

        # 使用新的 intent_sql_builder 生成 SQL
        sql_bundle = intent_sql_builder.build(
            intent=intent,
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


    async def analytics_guard_sql(self, state: dict) -> dict:
        """SQL Guard 节点。

        职责：
        - 对 schema-aware SQL 做只读校验；
        - 强制表白名单与部门过滤约束；
        - 如果不安全则直接阻断。
        """

        # SSE 进度推送
        tracker = state.get("_sse_tracker")
        if tracker:
            await tracker.step("analytics_guard_sql")

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

    async def analytics_execute_sql(self, state: dict) -> dict:
        """SQL 执行节点。

        职责：
        - 调用 SQL Gateway 执行只读查询；
        - 记录 SQL Audit；
        - 完成结果脱敏。
        """

        # SSE 进度推送
        tracker = state.get("_sse_tracker")
        if tracker:
            await tracker.step("analytics_execute_sql")

        t2 = time.monotonic()
        state["workflow_stage"] = AnalyticsWorkflowStage.ANALYTICS_EXECUTE_SQL
        task_run = state["task_run"]
        user_context = state["user_context"]
        sql_bundle = state["sql_bundle"]
        guard_result = state["guard_result"]
        table_definition = state["table_definition"]
        permission_check_result = state["permission_check_result"]
        data_scope_result = state["data_scope_result"]
        intent = state.get("intent")

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
                        "planning_source": "llm_parser",
                        "confidence": intent.confidence.overall if intent and intent.confidence else 0.8,
                    },
                )
            )

        try:
            # 使用 asyncio.to_thread 将同步 IO 操作放到线程池执行，避免阻塞事件循环
            execution_result = await asyncio.to_thread(
                self.retry_controller.run,
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

    async def analytics_summarize(self, state: dict) -> dict:
        """结果总结节点（v2 并行 LLM 版本）。

        职责：
        - 生成 summary / insight / chart / report；
        - 使用 ParallelLLMGenerator 并行调用 LLM；
        - 按 output_mode 决定生成范围；
        - 构造统一 AnalyticsResult 对象。
        """

        # SSE 进度推送
        tracker = state.get("_sse_tracker")
        if tracker:
            await tracker.step("analytics_summarize")

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
        intent = state.get("intent")

        slots = self._intent_to_slots(intent)
        summary = self.analytics_service._build_summary(slots, execution_result)
        state["summary"] = summary
        sql_explain = None
        if need_sql_explain:
            sql_explain = (
                "当前阶段采用 schema-aware 受控模板 SQL。"
                f"主指标={slots.get('metric') or 'unknown'}，时间范围={slots.get('time_range', {}).get('label', 'unknown')}，"
                f"group_by={slots.get('group_by') or 'none'}，"
                f"compare_target={slots.get('compare_target') or 'none'}，"
                f"data_source={execution_result.data_source}。"
            )

        effective_filters = sql_bundle["builder_metadata"].get("effective_filters", {})

        # 确保 governance_decision 是字典
        masking_governance = masking_result.governance_decision
        if isinstance(masking_governance, str):
            masking_governance = {"action": masking_governance}

        governance_decision = {
            "permission_check_result": permission_check_result,
            "data_scope_result": data_scope_result,
            "masked_fields": masking_result.masked_fields,
            "visible_fields": masking_result.visible_fields,
            "sensitive_fields": masking_result.sensitive_fields,
            "governance_action": masking_governance,
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
        llm_summary = None
        llm_insights = None
        llm_chart = None
        llm_report = None

        # 准备行数据
        rows = masking_result.rows
        columns = masking_result.columns
        row_count = execution_result.row_count

        # 并行 LLM 生成（仅在 standard/full 模式下）
        if output_mode in {"standard", "full"}:
            t4 = time.monotonic()
            try:
                # 使用并行 LLM 生成器
                generator = self.parallel_llm_generator

                # 准备回调（如果有 SSE tracker）
                progress_callback = None
                tracker: RedisSSEProgressTracker | None = state.get("_sse_tracker")

                if tracker:
                    async def llm_progress_callback(product: str, progress: int, data: dict):
                        event_map = {
                            "summary": SSEEventType.SUMMARY_DONE,
                            "insight": SSEEventType.INSIGHT_DONE,
                            "chart": SSEEventType.CHART_DONE,
                            "report": SSEEventType.REPORT_DONE,
                        }
                        event_type = event_map.get(product)
                        if event_type:
                            data = {"run_id": state["task_run"]["run_id"], "progress": progress, product: data}
                            await tracker.publisher.publish(event_type, data)

                    progress_callback = llm_progress_callback

                # 直接 await 异步调用（节点现在是 async 的）
                llm_result = await generator.generate_all(
                    original_query=state["query"],
                    slots=slots,
                    rows=[dict(zip(columns, row)) for row in rows],
                    columns=list(columns),
                    row_count=row_count,
                    progress_callback=progress_callback,
                )

                # 解析 LLM 结果
                if llm_result.get("summary"):
                    llm_summary = llm_result["summary"]
                    # 优先使用 LLM 生成的摘要
                    if llm_summary.get("main_text"):
                        summary = llm_summary["main_text"]

                if llm_result.get("insights"):
                    llm_insights = llm_result["insights"]
                    if llm_insights.get("insights"):
                        insight_cards = llm_insights["insights"]

                if llm_result.get("chart"):
                    llm_chart = llm_result["chart"]
                    # 构建 chart_spec
                    chart_spec = {
                        "chart_type": llm_chart.get("chart_type", "bar"),
                        "title": llm_chart.get("title", slots.get("metric", "指标")),
                        "x_field": llm_chart.get("x_field"),
                        "y_field": llm_chart.get("y_field"),
                    }

                if llm_result.get("report"):
                    llm_report = llm_result["report"]

            except Exception as exc:
                logger.warning(f"并行 LLM 生成失败，降级到规则生成: {exc}")
                self.degradation_controller.mark_degraded(
                    state=state,
                    feature="parallel_llm",
                    reason=f"LLM 内容生成失败：{exc}",
                )
                # 降级：使用规则生成
                chart_spec = self.analytics_service._build_chart_spec(
                    slots=slots,
                    execution_result=execution_result,
                    metric_name=slots.get("metric"),
                )
                insight_cards = self.retry_controller.run(
                    node_name="analytics_summarize",
                    state=state,
                    action=lambda: self.analytics_service.insight_builder.build(
                        slots=slots,
                        rows=rows,
                        row_count=row_count,
                    ),
                )
            state["timing"]["llm_content_ms"] = round((time.monotonic() - t4) * 1000, 1)
        else:
            # lite 模式：只生成基础摘要
            state["timing"]["llm_content_ms"] = 0.0

        # 生成报告块（仅 full 模式）
        if output_mode == "full":
            t5 = time.monotonic()
            try:
                # 如果有 LLM 生成的报告，直接使用
                if llm_report:
                    report_blocks = llm_report.get("blocks", [])
                    if not report_blocks:
                        # 没有 blocks，尝试用 LLM 摘要构建
                        report_blocks = self._build_report_blocks_from_llm(
                            summary=llm_summary or {"main_text": summary},
                            insights=llm_insights,
                            chart=llm_chart,
                        )
                else:
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
                                    "rows": [list(row.values()) for row in rows],
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
            except Exception as exc:
                logger.warning(f"报告块生成失败: {exc}")
                self.degradation_controller.mark_degraded(
                    state=state,
                    feature="report_blocks",
                    reason=f"报告块生成失败：{exc}",
                )
                report_blocks = []
            state["timing"]["report_ms"] = round((time.monotonic() - t5) * 1000, 1)
        else:
            state["timing"].setdefault("report_ms", 0.0)

        governance_decision_value = masking_result.governance_decision
        if isinstance(governance_decision_value, str):
            governance_decision_value = {"action": governance_decision_value}

        state["llm_summary"] = llm_summary
        state["llm_insights"] = llm_insights
        state["llm_chart"] = llm_chart
        state["llm_report"] = llm_report

        state["analytics_result"] = AnalyticsResult(
            run_id=state["task_run"]["run_id"],
            trace_id=state["task_run"]["trace_id"],
            summary=summary,
            sql_preview=guard_result.checked_sql,
            row_count=row_count,
            latency_ms=execution_result.latency_ms,
            data_source=execution_result.data_source,
            metric_scope=sql_bundle["metric_scope"],
            compare_target=sql_bundle.get("compare_target"),
            group_by=sql_bundle.get("group_by"),
            slots=slots,
            planning_source="llm_parser",
            columns=execution_result.columns,
            rows=execution_result.rows,
            masked_columns=masking_result.columns,
            masked_rows=masking_result.rows,
            visible_fields=masking_result.visible_fields,
            sensitive_fields=masking_result.sensitive_fields,
            masked_fields=masking_result.masked_fields,
            hidden_fields=masking_result.hidden_fields,
            governance_decision=governance_decision_value,
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

    def _build_report_blocks_from_llm(
        self,
        summary: dict,
        insights: dict | None,
        chart: dict | None,
    ) -> list[dict]:
        """从 LLM 生成的内容构建报告块

        当 LLM 返回的报告没有 blocks 时，使用其他 LLM 结果构建。
        """
        blocks = []

        # 执行摘要
        main_text = summary.get("main_text", "")
        if main_text:
            blocks.append({
                "block_type": "overview",
                "title": "分析概览",
                "content": main_text,
            })

        # 关键发现
        if insights and insights.get("insights"):
            insights_list = insights["insights"]
            if insights_list:
                findings_text = "\n".join([
                    f"• **{insight.get('title', '洞察')}**：{insight.get('summary', '')}"
                    for insight in insights_list
                ])
                blocks.append({
                    "block_type": "findings",
                    "title": "关键发现",
                    "content": findings_text,
                })

        # 图表
        if chart and chart.get("chart_type"):
            blocks.append({
                "block_type": "chart",
                "title": chart.get("title", "可视化图表"),
                "content": {
                    "chart_type": chart.get("chart_type"),
                    "description": chart.get("description", ""),
                },
            })

        return blocks

    async def analytics_finish(self, state: dict) -> dict:
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
            last_metric=self._intent_to_slots(intent).get("metric"),
            last_time_range=self._intent_to_slots(intent).get("time_range") or {},
            last_org_scope=self._intent_to_slots(intent).get("org_scope") or {},
            short_term_memory={
                "last_analytics_run_id": task_run["run_id"],
                "last_group_by": self._intent_to_slots(intent).get("group_by"),
                "last_compare_target": self._intent_to_slots(intent).get("compare_target"),
                "last_top_n": self._intent_to_slots(intent).get("top_n"),
                "last_sort_direction": self._intent_to_slots(intent).get("sort_direction"),
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
                    sub_status="awaiting_reviewer",
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
