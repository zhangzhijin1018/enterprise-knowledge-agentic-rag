"""经营分析导出应用服务。"""

from __future__ import annotations

from datetime import datetime, timezone

from core.analytics.data_source_registry import DataSourceRegistry
from core.analytics.report_formatter import ReportFormatter
from core.analytics.report_templates import ReportTemplateEngine
from core.common import error_codes
from core.common.exceptions import AppException
from core.common.response import build_response_meta
from core.repositories.analytics_review_repository import AnalyticsReviewRepository
from core.repositories.analytics_export_repository import AnalyticsExportRepository
from core.repositories.conversation_repository import ConversationRepository
from core.repositories.task_run_repository import TaskRunRepository
from core.security.auth import UserContext
from core.agent.control_plane.analytics_review_policy import AnalyticsReviewPolicy
from core.tools.mcp import ReportGatewayExecutionError, ReportRenderRequest
from core.tools.report.report_gateway import ReportGateway


class AnalyticsExportService:
    """经营分析导出应用服务。

    当前阶段该 Service 负责把“分析结果”转换成“可交付导出任务”：
    1. 读取既有 analytics run 结果；
    2. 组织标准化 report payload；
    3. 创建并更新导出任务状态；
    4. 通过 Report Gateway 调用最小 Report MCP server 生成导出产物。

    设计重点：
    - router 不直接接触 report contract 和本地文件系统；
    - 当前虽然同步生成文件，但状态流转仍按异步任务语义设计；
    - 后续切 Celery 或远端 Report MCP 服务时，优先复用这里的编排边界。
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

    def create_export(
        self,
        *,
        run_id: str,
        export_type: str,
        export_template: str | None = None,
        user_context: UserContext,
    ) -> dict:
        """创建经营分析导出任务并同步生成最小导出产物。"""

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
                    is_async=False,
                    need_human_review=True,
                ),
            }

        return self._render_export_task(export_task=export_task, task_run=task_run)
 
    def resume_export_after_review(self, *, export_id: str) -> dict:
        """审核通过后恢复导出任务执行。"""

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
        return self._render_export_task(export_task=export_task, task_run=task_run)

    def _render_export_task(self, *, export_task: dict, task_run: dict) -> dict:
        """真正执行导出渲染链路。

        这个方法被拆出来的原因是：
        - 普通导出可直接调用；
        - 命中 Human Review 的导出可在审核通过后复用同一条渲染链路；
        - 避免在 approve review 时复制一套导出逻辑。
        """

        run_id = export_task["run_id"]
        export_type = export_task["export_type"]
        output_snapshot = task_run.get("output_snapshot") or {}
        normalized_export_template = export_task.get("export_template")
        governance_decision = output_snapshot.get("governance_decision") or {}
        normalized_report_blocks = self.report_formatter.build(
            summary=output_snapshot.get("summary") or "",
            insight_cards=output_snapshot.get("insight_cards", []),
            tables=output_snapshot.get("tables", []),
            chart_spec=output_snapshot.get("chart_spec"),
            governance_note=governance_decision,
        )
        export_report_blocks = (
            self.report_template_engine.build(
                export_template=normalized_export_template,
                summary=output_snapshot.get("summary") or "",
                insight_cards=output_snapshot.get("insight_cards", []),
                report_blocks=normalized_report_blocks,
                chart_spec=output_snapshot.get("chart_spec"),
                tables=output_snapshot.get("tables", []),
                governance_note=governance_decision,
            )
            if normalized_export_template
            else normalized_report_blocks
        )
        export_task = self.analytics_export_repository.update_export_task(
            export_task["export_id"],
            status="running",
        ) or export_task

        try:
            render_response = self.report_gateway.render_report(
                ReportRenderRequest(
                    export_id=export_task["export_id"],
                    run_id=run_id,
                    export_type=export_type,
                    export_template=normalized_export_template,
                    summary=output_snapshot.get("summary"),
                    insight_cards=output_snapshot.get("insight_cards", []),
                    report_blocks=export_report_blocks,
                    chart_spec=output_snapshot.get("chart_spec"),
                    tables=output_snapshot.get("tables", []),
                    trace_id=task_run.get("trace_id"),
                    metadata={
                        "sql_preview": output_snapshot.get("sql_preview"),
                        "audit_info": output_snapshot.get("audit_info"),
                        "governance_decision": output_snapshot.get("governance_decision"),
                        "report_blocks_source": "template" if normalized_export_template else "default_formatter",
                    },
                )
            )
            export_task = self.analytics_export_repository.update_export_task(
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
                    **render_response.metadata,
                },
                finished_at=datetime.now(timezone.utc),
            ) or export_task
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
            raise AppException(
                error_code=error_codes.ANALYTICS_EXPORT_FAILED,
                message="经营分析导出失败",
                status_code=500,
                detail={
                    "run_id": run_id,
                    "export_type": export_type,
                    "reason": str(exc),
                    "gateway_error_code": exc.error_code,
                    "gateway_detail": exc.detail,
                },
            ) from exc
        except Exception as exc:  # pragma: no cover - 兜底保护
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
            raise AppException(
                error_code=error_codes.ANALYTICS_EXPORT_FAILED,
                message="经营分析导出失败",
                status_code=500,
                detail={
                    "run_id": run_id,
                    "export_type": export_type,
                    "reason": str(exc),
                },
            ) from exc

        return {
            "data": self._serialize_export_task(export_task),
            "meta": build_response_meta(
                run_id=run_id,
                status=export_task["status"],
                is_async=False,
                need_human_review=export_task.get("review_status") == "pending",
            ),
        }

    def get_export_detail(
        self,
        *,
        export_id: str,
        user_context: UserContext,
    ) -> dict:
        """读取经营分析导出任务详情。"""

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
        return {
            "data": self._serialize_export_task(export_task),
            "meta": build_response_meta(
                run_id=export_task["run_id"],
                status=export_task["status"],
                is_async=False,
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

        # 当前阶段导出 review policy 优先基于既有 analytics 结果工作，
        # 因此这里不重新做 Planner，只复用 output_snapshot 中已经落下来的 metric 名称。
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
