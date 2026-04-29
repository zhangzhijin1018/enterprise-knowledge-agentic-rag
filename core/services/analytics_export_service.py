"""经营分析导出应用服务。

V1 性能优化改造要点：
1. 导出已改为"真正异步任务语义"：POST 只创建任务并返回 export_id，
   后台通过 AsyncTaskRunner 异步处理，GET 轮询读取状态；
2. 重内容（tables / insight_cards / report_blocks / chart_spec）
   从 analytics_result_repository 读取，不再依赖 output_snapshot 中的重数据；
3. 接口和状态模型按真实异步任务设计，后续切 Celery 时只替换执行器；
4. 保持与 Human Review 链路兼容：review 未通过时不能直接导出，
   review 通过后可继续异步导出。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from core.analytics.data_source_registry import DataSourceRegistry
from core.analytics.report_formatter import ReportFormatter
from core.analytics.report_templates import ReportTemplateEngine
from core.common import error_codes
from core.common.async_task_runner import AsyncTaskRunner, get_async_task_runner
from core.common.exceptions import AppException
from core.common.response import build_response_meta
from core.repositories.analytics_result_repository import AnalyticsResultRepository
from core.repositories.analytics_review_repository import AnalyticsReviewRepository
from core.repositories.analytics_export_repository import AnalyticsExportRepository
from core.repositories.conversation_repository import ConversationRepository
from core.repositories.task_run_repository import TaskRunRepository
from core.security.auth import UserContext
from core.agent.control_plane.analytics_review_policy import AnalyticsReviewPolicy
from core.tools.mcp import ReportGatewayExecutionError, ReportRenderRequest
from core.tools.report.report_gateway import ReportGateway

logger = logging.getLogger(__name__)


class AnalyticsExportService:
    """经营分析导出应用服务。

    当前阶段该 Service 负责把"分析结果"转换成"可交付导出任务"：
    1. 读取既有 analytics run 结果；
    2. 组织标准化 report payload；
    3. 创建并更新导出任务状态；
    4. 通过 Report Gateway 调用最小 Report MCP server 生成导出产物。

    V1 性能优化改造：
    - POST export 只创建任务并返回 export_id，后台异步处理；
    - GET export detail 轮询读取状态；
    - 重内容从 analytics_result_repository 读取；
    - 接口和状态模型按真实异步任务设计。
    """

    SUPPORTED_EXPORT_TYPES = {"json", "markdown", "docx", "pdf"}

    def __init__(
        self,
        conversation_repository: ConversationRepository,
        task_run_repository: TaskRunRepository,
        analytics_export_repository: AnalyticsExportRepository,
        analytics_review_repository: AnalyticsReviewRepository,
        report_gateway: ReportGateway,
        review_policy: AnalyticsReviewPolicy,
        data_source_registry: DataSourceRegistry | None = None,
        report_template_engine: ReportTemplateEngine | None = None,
        report_formatter: ReportFormatter | None = None,
        analytics_result_repository: AnalyticsResultRepository | None = None,
        async_task_runner: AsyncTaskRunner | None = None,
    ) -> None:
        self.conversation_repository = conversation_repository
        self.task_run_repository = task_run_repository
        self.analytics_export_repository = analytics_export_repository
        self.analytics_review_repository = analytics_review_repository
        self.report_gateway = report_gateway
        self.review_policy = review_policy
        self.data_source_registry = data_source_registry
        self.report_template_engine = report_template_engine or ReportTemplateEngine()
        self.report_formatter = report_formatter or ReportFormatter()
        self.analytics_result_repository = analytics_result_repository or AnalyticsResultRepository()
        self.async_task_runner = async_task_runner or get_async_task_runner()

    def create_export(
        self,
        *,
        run_id: str,
        export_type: str,
        export_template: str | None = None,
        user_context: UserContext,
    ) -> dict:
        """创建经营分析导出任务。

        V1 性能优化：POST 只创建任务并返回 export_id，后台异步处理。
        不再同步等待渲染完成，前端通过 GET 轮询读取状态。

        为什么导出必须异步化：
        1. 导出涉及 report_blocks 构建 + Report Gateway 渲染，属于 CPU 和 IO 密集操作；
        2. 同步阻塞会导致 HTTP 请求超时，影响用户体验；
        3. 异步化后前端可以立即拿到 export_id，通过轮询感知进度；
        4. 后续切 Celery 时，只需替换 AsyncTaskRunner 实现。
        """

        normalized_export_type = export_type.strip().lower()
        if normalized_export_type not in self.SUPPORTED_EXPORT_TYPES:
            raise AppException(
                error_code=error_codes.ANALYTICS_EXPORT_FAILED,
                message="当前导出类型不受支持",
                status_code=400,
                detail={
                    "export_type": export_type,
                    "supported_export_types": sorted(self.SUPPORTED_EXPORT_TYPES),
                },
            )

        task_run = self._get_accessible_analytics_run_or_raise(
            run_id=run_id,
            user_context=user_context,
        )
        if task_run["status"] != "succeeded":
            raise AppException(
                error_code=error_codes.ANALYTICS_EXPORT_FAILED,
                message="当前经营分析任务尚未成功完成，无法导出",
                status_code=400,
                detail={
                    "run_id": run_id,
                    "status": task_run["status"],
                    "sub_status": task_run["sub_status"],
                },
            )

        output_snapshot = task_run.get("output_snapshot") or {}
        if not output_snapshot:
            raise AppException(
                error_code=error_codes.ANALYTICS_EXPORT_FAILED,
                message="当前经营分析结果为空，无法导出",
                status_code=400,
                detail={"run_id": run_id},
            )

        slots = output_snapshot.get("slots") or {}
        metric_definition = self._resolve_metric_definition(metric_name=slots.get("metric"))
        data_source_definition = self._resolve_data_source_definition(output_snapshot=output_snapshot)

        review_decision = self.review_policy.evaluate_export(
            export_type=normalized_export_type,
            output_snapshot=output_snapshot,
            metric_definition=metric_definition,
            data_source_definition=data_source_definition,
        )

        export_task = self.analytics_export_repository.create_export_task(
            run_id=run_id,
            user_id=user_context.user_id,
            export_type=normalized_export_type,
            export_template=export_template,
            status="pending",
            review_required=review_decision.review_required,
            review_status="pending" if review_decision.review_required else "not_required",
            review_level=review_decision.review_level if review_decision.review_required else None,
            review_reason=review_decision.review_reason,
            metadata={
                "trigger_mode": "manual",
                "source": "analytics_run",
                "export_template": export_template,
                "governance_decision": output_snapshot.get("governance_decision") or {},
            },
        )

        if review_decision.review_required:
            review_task = self.analytics_review_repository.create_review_task(
                subject_type="analytics_export",
                subject_id=export_task["export_id"],
                run_id=run_id,
                requester_user_id=user_context.user_id,
                review_status="pending",
                review_level=review_decision.review_level,
                review_reason=review_decision.review_reason or "高风险经营分析导出需要人工审核",
                metadata={
                    "reason_details": review_decision.reason_details,
                    "export_type": normalized_export_type,
                    "export_template": export_template,
                },
            )
            export_task = self.analytics_export_repository.update_export_task(
                export_task["export_id"],
                status="awaiting_human_review",
                review_id=review_task["review_id"],
            ) or export_task
            return {
                "data": self._serialize_export_task(export_task),
                "meta": build_response_meta(
                    run_id=run_id,
                    review_id=review_task["review_id"],
                    status="awaiting_human_review",
                    is_async=True,
                    need_human_review=True,
                ),
            }

        self._submit_async_render(export_id=export_task["export_id"])

        return {
            "data": self._serialize_export_task(export_task),
            "meta": build_response_meta(
                run_id=run_id,
                status="pending",
                is_async=True,
                need_human_review=False,
            ),
        }

    def resume_export_after_review(self, *, export_id: str) -> dict:
        """审核通过后恢复导出任务执行。

        V1 性能优化：审核通过后也走异步渲染，不再同步等待。
        """

        export_task = self.analytics_export_repository.get_export_task(export_id)
        if export_task is None:
            raise AppException(
                error_code=error_codes.ANALYTICS_EXPORT_NOT_FOUND,
                message="指定经营分析导出任务不存在",
                status_code=404,
                detail={"export_id": export_id},
            )
        if export_task.get("review_status") != "approved":
            raise AppException(
                error_code=error_codes.ANALYTICS_REVIEW_INVALID_STATUS,
                message="当前导出任务尚未通过审核，不能继续执行",
                status_code=400,
                detail={
                    "export_id": export_id,
                    "review_status": export_task.get("review_status"),
                },
            )
        task_run = self.task_run_repository.get_task_run(export_task["run_id"])
        if task_run is None or task_run["task_type"] != "analytics":
            raise AppException(
                error_code=error_codes.ANALYTICS_RUN_NOT_FOUND,
                message="导出任务关联的经营分析运行不存在",
                status_code=404,
                detail={"run_id": export_task["run_id"]},
            )

        self._submit_async_render(export_id=export_id)

        export_task = self.analytics_export_repository.get_export_task(export_id) or export_task
        return {
            "data": self._serialize_export_task(export_task),
            "meta": build_response_meta(
                run_id=export_task["run_id"],
                status="pending",
                is_async=True,
                need_human_review=False,
            ),
        }

    def _submit_async_render(self, *, export_id: str) -> str:
        """提交异步渲染任务到后台执行器。

        为什么用 AsyncTaskRunner 而不是直接同步执行：
        1. 导出渲染是 CPU + IO 密集操作，同步执行会阻塞 HTTP 请求；
        2. AsyncTaskRunner 提供了任务提交、状态查询的标准接口；
        3. 后续切 Celery 时，只需替换此方法内部实现；
        4. 当前阶段用 threading 实现，不依赖外部任务队列。
        """

        task_id = self.async_task_runner.submit(
            self._execute_render,
            export_id=export_id,
        )

        self.analytics_export_repository.update_export_task(
            export_id,
            metadata={
                "async_task_id": task_id,
            },
        )

        return task_id

    def _execute_render(self, *, export_id: str) -> None:
        """在后台线程中执行导出渲染。

        为什么这个方法不抛异常到调用方：
        1. 它在后台线程中运行，调用方已经返回；
        2. 异常通过 export_task.status = "failed" 记录；
        3. 前端通过 GET 轮询感知失败状态。
        """

        export_task = self.analytics_export_repository.get_export_task(export_id)
        if export_task is None:
            logger.error("Export task %s not found during async render", export_id)
            return

        run_id = export_task["run_id"]
        task_run = self.task_run_repository.get_task_run(run_id)
        if task_run is None:
            self.analytics_export_repository.update_export_task(
                export_id,
                status="failed",
                metadata={
                    **(export_task.get("metadata") or {}),
                    "error_code": "analytics_run_not_found",
                    "error_detail": {"reason": f"Run {run_id} not found"},
                },
                finished_at=datetime.now(timezone.utc),
            )
            return

        try:
            self._render_export_task_sync(export_task=export_task, task_run=task_run)
        except Exception as exc:
            logger.exception("Async export render failed for %s", export_id)
            self.analytics_export_repository.update_export_task(
                export_id,
                status="failed",
                metadata={
                    **(export_task.get("metadata") or {}),
                    "error_code": "analytics_export_render_error",
                    "error_detail": {"reason": str(exc)},
                },
                finished_at=datetime.now(timezone.utc),
            )

    def _render_export_task_sync(self, *, export_task: dict, task_run: dict) -> dict:
        """真正执行导出渲染链路。

        V1 性能优化：
        1. 重内容从 analytics_result_repository 读取，不再依赖 output_snapshot 中的重数据；
        2. 记录导出渲染耗时到 export metadata；
        3. 这个方法在后台线程中执行，不再阻塞 HTTP 请求。

        为什么重内容要从 analytics_result_repository 读取：
        1. output_snapshot 轻量化后，tables / insight_cards / report_blocks / chart_spec
           不再写入 output_snapshot；
        2. 这些重内容已单独存储在 analytics_result_repository 中；
        3. 导出需要完整数据，因此必须从结果仓储读取。
        """

        t0 = time.monotonic()
        run_id = export_task["run_id"]
        export_type = export_task["export_type"]
        output_snapshot = task_run.get("output_snapshot") or {}
        normalized_export_template = export_task.get("export_template")
        governance_decision = output_snapshot.get("governance_decision") or {}

        heavy_result = self.analytics_result_repository.get_heavy_result(run_id)
        tables = heavy_result.get("tables", []) if heavy_result else output_snapshot.get("tables", [])
        insight_cards = heavy_result.get("insight_cards", []) if heavy_result else output_snapshot.get("insight_cards", [])
        chart_spec = heavy_result.get("chart_spec") if heavy_result else output_snapshot.get("chart_spec")
        audit_info = heavy_result.get("audit_info") if heavy_result else output_snapshot.get("audit_info")

        normalized_report_blocks = self.report_formatter.build(
            summary=output_snapshot.get("summary") or "",
            insight_cards=insight_cards,
            tables=tables,
            chart_spec=chart_spec,
            governance_note=governance_decision,
        )
        export_report_blocks = (
            self.report_template_engine.build(
                export_template=normalized_export_template,
                summary=output_snapshot.get("summary") or "",
                insight_cards=insight_cards,
                report_blocks=normalized_report_blocks,
                chart_spec=chart_spec,
                tables=tables,
                governance_note=governance_decision,
            )
            if normalized_export_template
            else normalized_report_blocks
        )
        self.analytics_export_repository.update_export_task(
            export_task["export_id"],
            status="running",
        )

        try:
            render_response = self.report_gateway.render_report(
                ReportRenderRequest(
                    export_id=export_task["export_id"],
                    run_id=run_id,
                    export_type=export_type,
                    export_template=normalized_export_template,
                    summary=output_snapshot.get("summary"),
                    insight_cards=insight_cards,
                    report_blocks=export_report_blocks,
                    chart_spec=chart_spec,
                    tables=tables,
                    trace_id=task_run.get("trace_id"),
                    metadata={
                        "sql_preview": output_snapshot.get("sql_preview"),
                        "audit_info": audit_info,
                        "governance_decision": governance_decision,
                        "report_blocks_source": "template" if normalized_export_template else "default_formatter",
                    },
                )
            )
            export_render_ms = round((time.monotonic() - t0) * 1000, 1)
            self.analytics_export_repository.update_export_task(
                export_task["export_id"],
                status="succeeded",
                filename=render_response.filename,
                artifact_path=render_response.artifact_path,
                file_uri=render_response.file_uri,
                content_preview=render_response.content_preview,
                metadata={
                    **(export_task.get("metadata") or {}),
                    "export_template": normalized_export_template,
                    "governance_decision": governance_decision,
                    "export_render_ms": export_render_ms,
                    **render_response.metadata,
                },
                finished_at=datetime.now(timezone.utc),
            )
        except ReportGatewayExecutionError as exc:
            self.analytics_export_repository.update_export_task(
                export_task["export_id"],
                status="failed",
                metadata={
                    **(export_task.get("metadata") or {}),
                    "error_code": exc.error_code,
                    "error_detail": exc.detail,
                },
                finished_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            self.analytics_export_repository.update_export_task(
                export_task["export_id"],
                status="failed",
                metadata={
                    **(export_task.get("metadata") or {}),
                    "error_code": "analytics_export_unexpected_error",
                    "error_detail": {"reason": str(exc)},
                },
                finished_at=datetime.now(timezone.utc),
            )

        updated_task = self.analytics_export_repository.get_export_task(export_task["export_id"]) or export_task
        return {
            "data": self._serialize_export_task(updated_task),
            "meta": build_response_meta(
                run_id=run_id,
                status=updated_task.get("status", "unknown"),
                is_async=True,
                need_human_review=updated_task.get("review_status") == "pending",
            ),
        }

    def get_export_detail(
        self,
        *,
        export_id: str,
        user_context: UserContext,
    ) -> dict:
        """读取经营分析导出任务详情。

        V1 性能优化：支持异步任务状态轮询。
        前端通过此接口轮询导出任务状态，直到状态变为 succeeded / failed。
        """

        export_task = self.analytics_export_repository.get_export_task(export_id)
        if export_task is None:
            raise AppException(
                error_code=error_codes.ANALYTICS_EXPORT_NOT_FOUND,
                message="指定经营分析导出任务不存在",
                status_code=404,
                detail={"export_id": export_id},
            )

        self._get_accessible_analytics_run_or_raise(
            run_id=export_task["run_id"],
            user_context=user_context,
        )

        is_still_processing = export_task.get("status") in {"pending", "running"}

        return {
            "data": self._serialize_export_task(export_task),
            "meta": build_response_meta(
                run_id=export_task["run_id"],
                status=export_task["status"],
                is_async=True,
                need_human_review=export_task.get("review_status") == "pending",
            ),
        }

    def _get_accessible_analytics_run_or_raise(
        self,
        *,
        run_id: str,
        user_context: UserContext,
    ) -> dict:
        """读取当前用户有权访问的经营分析运行记录。"""

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
                message="当前用户无权访问该经营分析任务",
                status_code=403,
                detail={
                    "run_id": run_id,
                    "conversation_id": task_run["conversation_id"],
                    "owner_user_id": conversation["user_id"],
                    "current_user_id": user_context.user_id,
                },
            )

        return task_run

    def _serialize_export_task(self, export_task: dict) -> dict:
        """把导出任务记录转换成稳定接口结构。"""

        return {
            "export_id": export_task["export_id"],
            "run_id": export_task["run_id"],
            "export_type": export_task["export_type"],
            "export_template": export_task.get("export_template"),
            "status": export_task["status"],
            "review_required": export_task.get("review_required", False),
            "review_id": export_task.get("review_id"),
            "review_status": export_task.get("review_status", "not_required"),
            "review_level": export_task.get("review_level"),
            "review_reason": export_task.get("review_reason"),
            "reviewer": export_task.get("reviewer_name"),
            "filename": export_task.get("filename"),
            "content_preview": export_task.get("content_preview"),
            "artifact_path": export_task.get("artifact_path"),
            "file_uri": export_task.get("file_uri"),
            "created_at": export_task["created_at"].isoformat(),
            "reviewed_at": export_task.get("reviewed_at").isoformat() if export_task.get("reviewed_at") else None,
            "finished_at": export_task.get("finished_at").isoformat() if export_task.get("finished_at") else None,
            "metadata": export_task.get("metadata") or {},
            "governance_decision": (export_task.get("metadata") or {}).get("governance_decision") or {},
        }

    def _resolve_metric_definition(self, *, metric_name: str | None):
        """从 task_run 输出快照解析指标定义。"""

        from core.analytics.metric_catalog import MetricCatalog

        metric_catalog = MetricCatalog()
        metric_definition = metric_catalog.resolve_metric(metric_name)
        if metric_definition is None:
            metric_definition = metric_catalog.find_metric_in_query(metric_name or "") or metric_catalog.resolve_metric("发电量")
        if metric_definition is None:
            metric_definition = metric_catalog._build_default_metrics()["发电量"]
        return metric_definition

    def _resolve_data_source_definition(self, *, output_snapshot: dict):
        """从 analytics 输出快照解析数据源定义。"""

        if self.data_source_registry is not None:
            return self.data_source_registry.get_data_source(output_snapshot.get("data_source"))

        from core.analytics.schema_registry import SchemaRegistry

        schema_registry = SchemaRegistry()
        return schema_registry.get_data_source(output_snapshot.get("data_source"))
