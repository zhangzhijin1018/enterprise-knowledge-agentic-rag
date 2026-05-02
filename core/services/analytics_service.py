"""经营分析主链路 Service（v2 纯 Workflow 链路）。

本版本移除了旧链路代码，只走 LangGraph Workflow：

用户问题
-> LLMAnalyticsIntentParser 解析意图（生成 AnalyticsIntent）
-> AnalyticsIntentValidator 校验槽位
-> 缺槽位则澄清
-> AnalyticsIntentSQLBuilder 构建 SQL
-> SQL Guard 安全校验
-> SQL Gateway 执行查询
-> Summary / Chart / Insight / Report 生成
-> 记录 SQL Audit
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.agent.workflows.analytics.snapshot_builder import AnalyticsSnapshotBuilder
from core.analytics.analytics_result_model import AnalyticsResult
from core.analytics.data_masking import DataMaskingService
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
from core.tools.sql.sql_gateway import SQLGateway

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型提示
    from core.agent.control_plane.sql_guard import SQLGuard
    from core.agent.workflows.analytics.adapter import AnalyticsWorkflowAdapter

VALID_OUTPUT_MODES = {"lite", "standard", "full"}
DEFAULT_OUTPUT_MODE = "lite"


class AnalyticsService:
    """经营分析应用编排层（v2 纯 Workflow 链路）。

    职责：
    - 持有 Repository 层依赖（会话、任务、SQL审计、结果）
    - 持有 Workflow Adapter（负责编排 LangGraph 节点）
    - 持有辅助组件（指标目录、Schema、数据脱敏等），供 Workflow 节点复用
    - 对外暴露 submit_query / get_run_detail 等稳定业务接口
    - 不直接执行 SQL，不直接调用 LLM，不直接操作 LangGraph 状态
    """

    def __init__(
        self,
        conversation_repository: ConversationRepository,
        task_run_repository: TaskRunRepository,
        sql_audit_repository: SQLAuditRepository,
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
        snapshot_builder: AnalyticsSnapshotBuilder | None = None,
    ) -> None:
        # Repository 层依赖
        self.conversation_repository = conversation_repository
        self.task_run_repository = task_run_repository
        self.sql_audit_repository = sql_audit_repository
        self.analytics_result_repository = analytics_result_repository or AnalyticsResultRepository()

        # SQL 执行链路依赖
        self.sql_guard = sql_guard
        self.sql_gateway = sql_gateway

        # Registry 层依赖（供 Workflow 节点复用）
        self.schema_registry = schema_registry
        self.metric_catalog = metric_catalog
        self.data_source_registry = data_source_registry

        # 辅助组件
        self.data_masking_service = data_masking_service or DataMaskingService()
        self.insight_builder = insight_builder or InsightBuilder()
        self.report_formatter = report_formatter or ReportFormatter()
        self.registry_cache = registry_cache or get_global_cache()
        self.snapshot_builder = snapshot_builder or AnalyticsSnapshotBuilder()

        # v2：延迟创建 Workflow Adapter（避免循环导入）
        self._workflow_adapter: "AnalyticsWorkflowAdapter | None" = None

    @property
    def workflow_adapter(self) -> "AnalyticsWorkflowAdapter":
        """获取 Workflow Adapter（懒加载）。"""
        if self._workflow_adapter is None:
            from core.agent.workflows.analytics.adapter import AnalyticsWorkflowAdapter
            self._workflow_adapter = AnalyticsWorkflowAdapter(analytics_service=self)
        return self._workflow_adapter

    def submit_query(
        self,
        *,
        query: str,
        conversation_id: str | None,
        output_mode: str,
        need_sql_explain: bool,
        user_context: UserContext,
    ) -> dict:
        """提交经营分析请求（v2 纯 Workflow 链路）。

        直接委托给 Workflow Adapter 执行，不做额外处理。
        """

        normalized_query = query.strip()
        if not normalized_query:
            raise AppException(
                error_code=error_codes.ANALYTICS_QUERY_FAILED,
                message="经营分析问题不能为空",
                status_code=400,
                detail={},
            )

        # 直接调用 Workflow Adapter
        return self.workflow_adapter.execute_query(
            query=normalized_query,
            conversation_id=conversation_id,
            output_mode=output_mode,
            need_sql_explain=need_sql_explain,
            user_context=user_context,
        )

    def get_run_detail(
        self,
        *,
        run_id: str,
        output_mode: str = "full",
        user_context: UserContext,
    ) -> dict:
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

    def _get_or_create_conversation(
        self,
        *,
        conversation_id: str | None,
        query: str,
        user_context: UserContext,
    ) -> dict:
        """读取已有会话或创建新会话（供 Workflow 节点调用）。"""

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

    # 以下是保留的辅助方法，供 Workflow 节点复用

    def _get_cached_metric(self, metric_name: str | None):
        """通过缓存获取指标定义（供 Workflow 节点调用）。"""

        if metric_name is None:
            return None
        cache_key = f"metric:{metric_name}"
        return self.registry_cache.get_or_compute(
            cache_key,
            lambda: self.metric_catalog.resolve_metric(metric_name),
        )

    def _get_cached_allowed_tables(self, data_source: str) -> list[str]:
        """通过缓存获取表白名单（供 Workflow 节点调用）。"""

        cache_key = f"allowed_tables:{data_source}"
        return self.registry_cache.get_or_compute(
            cache_key,
            lambda: self.schema_registry.get_allowed_tables(data_source=data_source),
        )

    def _get_cached_visible_fields(self, table_name: str, data_source: str) -> list[str]:
        """通过缓存获取可见字段（供 Workflow 节点调用）。"""

        cache_key = f"visible_fields:{data_source}:{table_name}"
        return self.registry_cache.get_or_compute(
            cache_key,
            lambda: self.schema_registry.get_table_visible_fields(
                table_name=table_name,
                data_source=data_source,
            ),
        )

    def _get_cached_sensitive_fields(self, table_name: str, data_source: str) -> list[str]:
        """通过缓存获取敏感字段（供 Workflow 节点调用）。"""

        cache_key = f"sensitive_fields:{data_source}:{table_name}"
        return self.registry_cache.get_or_compute(
            cache_key,
            lambda: self.schema_registry.get_table_sensitive_fields(
                table_name=table_name,
                data_source=data_source,
            ),
        )

    def _get_cached_masked_fields(self, table_name: str, data_source: str) -> list[str]:
        """通过缓存获取脱敏字段（供 Workflow 节点调用）。"""

        cache_key = f"masked_fields:{data_source}:{table_name}"
        return self.registry_cache.get_or_compute(
            cache_key,
            lambda: self.schema_registry.get_table_masked_fields(
                table_name=table_name,
                data_source=data_source,
            ),
        )

    def _get_cached_field_whitelist(self, table_name: str, data_source: str) -> list[str]:
        """通过缓存获取字段白名单（供 Workflow 节点调用）。"""

        cache_key = f"field_whitelist:{data_source}:{table_name}"
        return self.registry_cache.get_or_compute(
            cache_key,
            lambda: self.schema_registry.get_table_field_whitelist(
                table_name=table_name,
                data_source=data_source,
            ),
        )

    def _assert_metric_permission(self, *, metric_definition, user_context: UserContext) -> dict:
        """断言指标权限（供 Workflow 节点调用）。"""

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
            "sensitivity_level": getattr(metric_definition, "sensitivity_level", None),
        }

    def _assert_data_source_permission(self, *, data_source_definition, user_context: UserContext) -> dict:
        """断言数据源权限（供 Workflow 节点调用）。"""

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
        """构建数据范围结果（供 Workflow 节点调用）。"""

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

    def _build_summary(self, slots: dict, execution_result) -> str:
        """构建摘要文本（供 Workflow 节点调用）。"""

        metric = slots.get("metric", "未知指标")
        time_label = slots.get("time_range", {}).get("label", "目标时间范围")
        org_scope = slots.get("org_scope")
        group_by = slots.get("group_by")
        rows = execution_result.rows

        scope_text = org_scope.get("value", "全部范围") if isinstance(org_scope, dict) else "全部范围"
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
        """构建图表规格（供 Workflow 节点调用）。"""

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
            }
        if group_by in {"region", "station"}:
            return {
                "chart_type": "ranking_bar" if slots.get("top_n") else "bar",
                "title": f"{metric_name}{'对比' if compare_target else ''}{group_by}分布",
                "x_field": group_by,
                "y_field": "current_value" if compare_target in {"mom", "yoy"} else "total_value",
                "series_field": None,
                "dataset_ref": "main_result",
            }
        return {
            "chart_type": "pie" if execution_result.row_count > 1 else "stacked_bar",
            "title": f"{metric_name}汇总",
            "x_field": None,
            "y_field": "current_value" if compare_target in {"mom", "yoy"} else "total_value",
            "series_field": None,
            "dataset_ref": "main_result",
        }

    def _build_audit_info(
        self,
        audit_record: dict | None,
        *,
        permission_check_result: dict | None = None,
        data_scope_result: dict | None = None,
        masking_result=None,
        effective_filters: dict | None = None,
        guard_result=None,
    ) -> dict | None:
        """构建审计信息（供 Workflow 节点调用）。"""

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
            "masked_fields": getattr(masking_result, "masked_fields", []) if masking_result else [],
            "effective_filters": effective_filters or {},
            "governance_decision": {
                "action": getattr(masking_result, "governance_decision", "no_masking_needed") if masking_result else "no_masking_needed",
                "guard_stage": getattr(guard_result, "governance_detail", None) if guard_result else None,
            },
        }

    def _has_all_permissions(self, user_permissions: list[str], required_permissions: list[str]) -> bool:
        """判断用户是否满足全部权限。"""

        if not required_permissions:
            return True
        permission_set = set(user_permissions or [])
        return all(permission in permission_set for permission in required_permissions)

