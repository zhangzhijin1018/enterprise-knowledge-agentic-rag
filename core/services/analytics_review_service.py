"""经营分析 Human Review 应用服务。"""

from __future__ import annotations

from datetime import datetime, timezone

from core.common import error_codes
from core.common.exceptions import AppException
from core.common.response import build_response_meta
from core.repositories.analytics_export_repository import AnalyticsExportRepository
from core.repositories.analytics_review_repository import AnalyticsReviewRepository
from core.repositories.conversation_repository import ConversationRepository
from core.repositories.task_run_repository import TaskRunRepository
from core.security.auth import UserContext
from core.services.analytics_export_service import AnalyticsExportService


class AnalyticsReviewService:
    """经营分析 Human Review 编排服务。

    当前阶段优先解决“高风险导出先审再出”的最小闭环：
    1. 查询既有 review；
    2. 审核通过后恢复导出；
    3. 审核驳回后终止导出；
    4. 保留 review 与 export 两套状态，便于前端和审计准确追踪。
    """

    def __init__(
        self,
        conversation_repository: ConversationRepository,
        task_run_repository: TaskRunRepository,
        analytics_export_repository: AnalyticsExportRepository,
        analytics_review_repository: AnalyticsReviewRepository,
        analytics_export_service: AnalyticsExportService,
    ) -> None:
        self.conversation_repository = conversation_repository
        self.task_run_repository = task_run_repository
        self.analytics_export_repository = analytics_export_repository
        self.analytics_review_repository = analytics_review_repository
        self.analytics_export_service = analytics_export_service

    def submit_export_review(self, *, export_id: str, user_context: UserContext) -> dict:
        """提交或读取导出审核请求。"""

        export_task, _task_run = self._get_accessible_export_and_run(
            export_id=export_id,
            user_context=user_context,
        )
        if not export_task.get("review_required"):
            raise AppException(
                error_code=error_codes.ANALYTICS_REVIEW_NOT_REQUIRED,
                message="当前导出任务不需要人工审核",
                status_code=400,
                detail={"export_id": export_id},
            )

        review_task = self.analytics_review_repository.get_by_subject(
            subject_type="analytics_export",
            subject_id=export_id,
        )
        if review_task is None:
            raise AppException(
                error_code=error_codes.ANALYTICS_REVIEW_NOT_FOUND,
                message="当前导出任务尚未创建审核记录",
                status_code=404,
                detail={"export_id": export_id},
            )

        return {
            "data": self._serialize_review_task(review_task),
            "meta": build_response_meta(
                run_id=review_task["run_id"],
                review_id=review_task["review_id"],
                status=export_task["status"],
                is_async=False,
                need_human_review=True,
            ),
        }

    def approve_review(
        self,
        *,
        review_id: str,
        comment: str | None,
        reviewer_context: UserContext,
    ) -> dict:
        """审批通过审核任务，并恢复原导出。"""

        self._assert_user_can_decide_review(reviewer_context)
        review_task = self._get_review_task_or_raise(review_id)
        if review_task["review_status"] != "pending":
            raise AppException(
                error_code=error_codes.ANALYTICS_REVIEW_INVALID_STATUS,
                message="当前审核任务已完成，不能重复审批",
                status_code=400,
                detail={
                    "review_id": review_id,
                    "review_status": review_task["review_status"],
                },
            )

        export_task = self.analytics_export_repository.get_export_task(review_task["subject_id"])
        if export_task is None:
            raise AppException(
                error_code=error_codes.ANALYTICS_EXPORT_NOT_FOUND,
                message="关联导出任务不存在",
                status_code=404,
                detail={"export_id": review_task["subject_id"]},
            )

        reviewed_at = datetime.now(timezone.utc)
        review_task = self.analytics_review_repository.update_review_task(
            review_id,
            review_status="approved",
            reviewer_id=reviewer_context.user_id,
            reviewer_name=reviewer_context.display_name,
            review_comment=comment,
            reviewed_at=reviewed_at,
        ) or review_task
        self.analytics_export_repository.update_export_task(
            export_task["export_id"],
            review_status="approved",
            reviewer_id=reviewer_context.user_id,
            reviewer_name=reviewer_context.display_name,
            reviewed_at=reviewed_at,
            metadata={
                **(export_task.get("metadata") or {}),
                "review_approved_comment": comment,
            },
        )

        resumed_result = self.analytics_export_service.resume_export_after_review(
            export_id=export_task["export_id"],
        )
        return {
            "data": {
                "review": self._serialize_review_task(review_task),
                "export": resumed_result["data"],
            },
            "meta": build_response_meta(
                run_id=review_task["run_id"],
                review_id=review_task["review_id"],
                status=resumed_result["meta"]["status"],
                is_async=False,
            ),
        }

    def reject_review(
        self,
        *,
        review_id: str,
        comment: str | None,
        reviewer_context: UserContext,
    ) -> dict:
        """驳回审核任务，并终止导出。"""

        self._assert_user_can_decide_review(reviewer_context)
        review_task = self._get_review_task_or_raise(review_id)
        if review_task["review_status"] != "pending":
            raise AppException(
                error_code=error_codes.ANALYTICS_REVIEW_INVALID_STATUS,
                message="当前审核任务已完成，不能重复驳回",
                status_code=400,
                detail={
                    "review_id": review_id,
                    "review_status": review_task["review_status"],
                },
            )

        export_task = self.analytics_export_repository.get_export_task(review_task["subject_id"])
        if export_task is None:
            raise AppException(
                error_code=error_codes.ANALYTICS_EXPORT_NOT_FOUND,
                message="关联导出任务不存在",
                status_code=404,
                detail={"export_id": review_task["subject_id"]},
            )

        reviewed_at = datetime.now(timezone.utc)
        review_task = self.analytics_review_repository.update_review_task(
            review_id,
            review_status="rejected",
            reviewer_id=reviewer_context.user_id,
            reviewer_name=reviewer_context.display_name,
            review_comment=comment,
            reviewed_at=reviewed_at,
        ) or review_task
        export_task = self.analytics_export_repository.update_export_task(
            export_task["export_id"],
            status="failed",
            review_status="rejected",
            reviewer_id=reviewer_context.user_id,
            reviewer_name=reviewer_context.display_name,
            reviewed_at=reviewed_at,
            finished_at=reviewed_at,
            metadata={
                **(export_task.get("metadata") or {}),
                "review_rejected_comment": comment,
            },
        ) or export_task

        return {
            "data": {
                "review": self._serialize_review_task(review_task),
                "export": self.analytics_export_service._serialize_export_task(export_task),
            },
            "meta": build_response_meta(
                run_id=review_task["run_id"],
                review_id=review_task["review_id"],
                status=export_task["status"],
                is_async=False,
            ),
        }

    def get_review_detail(self, *, review_id: str, user_context: UserContext) -> dict:
        """读取审核任务详情。"""

        review_task = self._get_review_task_or_raise(review_id)
        self._assert_user_can_access_review(review_task=review_task, user_context=user_context)
        export_task = self.analytics_export_repository.get_export_task(review_task["subject_id"])

        return {
            "data": {
                **self._serialize_review_task(review_task),
                "export_status": export_task["status"] if export_task else None,
                "export_review_status": export_task["review_status"] if export_task else None,
            },
            "meta": build_response_meta(
                run_id=review_task["run_id"],
                review_id=review_task["review_id"],
                status=review_task["review_status"],
                is_async=False,
                need_human_review=review_task["review_status"] == "pending",
            ),
        }

    def _get_review_task_or_raise(self, review_id: str) -> dict:
        """读取审核任务，不存在则抛错。"""

        review_task = self.analytics_review_repository.get_review_task(review_id)
        if review_task is None:
            raise AppException(
                error_code=error_codes.ANALYTICS_REVIEW_NOT_FOUND,
                message="指定经营分析审核任务不存在",
                status_code=404,
                detail={"review_id": review_id},
            )
        return review_task

    def _get_accessible_export_and_run(self, *, export_id: str, user_context: UserContext) -> tuple[dict, dict]:
        """读取当前用户有权访问的导出任务及其关联运行。"""

        export_task = self.analytics_export_repository.get_export_task(export_id)
        if export_task is None:
            raise AppException(
                error_code=error_codes.ANALYTICS_EXPORT_NOT_FOUND,
                message="指定经营分析导出任务不存在",
                status_code=404,
                detail={"export_id": export_id},
            )

        task_run = self.task_run_repository.get_task_run(export_task["run_id"])
        if task_run is None or task_run["task_type"] != "analytics":
            raise AppException(
                error_code=error_codes.ANALYTICS_RUN_NOT_FOUND,
                message="导出任务关联的经营分析运行不存在",
                status_code=404,
                detail={"run_id": export_task["run_id"]},
            )

        conversation = self.conversation_repository.get_conversation(task_run["conversation_id"])
        if conversation is None:
            raise AppException(
                error_code=error_codes.CONVERSATION_NOT_FOUND,
                message="经营分析任务关联的会话不存在",
                status_code=404,
                detail={"run_id": export_task["run_id"]},
            )
        if conversation["user_id"] != user_context.user_id:
            raise AppException(
                error_code=error_codes.PERMISSION_DENIED,
                message="当前用户无权访问该经营分析导出任务",
                status_code=403,
                detail={
                    "export_id": export_id,
                    "owner_user_id": conversation["user_id"],
                    "current_user_id": user_context.user_id,
                },
            )

        return export_task, task_run

    def _assert_user_can_access_review(self, *, review_task: dict, user_context: UserContext) -> None:
        """校验当前用户是否可访问审核任务。"""

        if "analytics:review" in set(user_context.permissions or []):
            return
        _export_task, _task_run = self._get_accessible_export_and_run(
            export_id=review_task["subject_id"],
            user_context=user_context,
        )
        _ = (_export_task, _task_run)

    def _assert_user_can_decide_review(self, user_context: UserContext) -> None:
        """校验当前用户是否有审批权限。"""

        reviewer_roles = {"admin", "manager", "reviewer", "analyst"}
        if "analytics:review" in set(user_context.permissions or []):
            return
        if set(user_context.roles or []).intersection(reviewer_roles):
            return
        raise AppException(
            error_code=error_codes.PERMISSION_DENIED,
            message="当前用户无权执行经营分析审核动作",
            status_code=403,
            detail={
                "required_permission": "analytics:review",
                "allowed_roles": sorted(reviewer_roles),
                "current_roles": user_context.roles,
            },
        )

    def _serialize_review_task(self, review_task: dict) -> dict:
        """把审核任务转换成稳定接口结构。"""

        return {
            "review_id": review_task["review_id"],
            "subject_type": review_task["subject_type"],
            "subject_id": review_task["subject_id"],
            "run_id": review_task["run_id"],
            "requester_user_id": review_task["requester_user_id"],
            "review_status": review_task["review_status"],
            "review_level": review_task["review_level"],
            "review_reason": review_task["review_reason"],
            "reviewer": review_task.get("reviewer_name"),
            "review_comment": review_task.get("review_comment"),
            "reviewed_at": review_task["reviewed_at"].isoformat() if review_task.get("reviewed_at") else None,
            "metadata": review_task.get("metadata") or {},
        }
