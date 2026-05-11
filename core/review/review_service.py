"""Human Review 审核管理服务。

提供审核任务的创建、分配、审核和查询功能。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from core.review.models import (
    ReviewDecision,
    ReviewHistory,
    ReviewPolicy,
    ReviewRequest,
    ReviewStatus,
    ReviewTask,
    RiskLevel,
    TaskType,
    create_review_task,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ReviewService:
    """Human Review 审核管理服务。

    职责：
    - 创建审核任务
    - 分配审核人
    - 执行审核决策
    - 查询审核状态

    设计原因：
    - 高风险任务需要人工复核
    - 审核流程需要完整记录
    - 支持多级审核和升级
    """

    def __init__(
        self,
        review_policy: ReviewPolicy | None = None,
    ) -> None:
        """初始化审核服务。

        Args:
            review_policy: 审核策略
        """

        self.review_policy = review_policy or ReviewPolicy()

        # 内存存储（后续可替换为数据库）
        self._tasks: dict[str, ReviewTask] = {}
        self._history: list[ReviewHistory] = []

    def create_review(
        self,
        request: ReviewRequest,
    ) -> ReviewTask:
        """创建审核任务。

        Args:
            request: 审核请求

        Returns:
            审核任务
        """
        import uuid

        review_id = f"review_{uuid.uuid4().hex[:12]}"

        task = create_review_task(
            review_id=review_id,
            task_id=request.task_id,
            run_id=request.run_id,
            task_type=request.task_type,
            risk_level=request.risk_level,
            title=request.title,
            description=request.description,
            content_summary=request.content_summary,
            submitted_by=request.submitted_by,
            content_detail=request.content_detail,
            resource_id=request.resource_id,
            resource_type=request.resource_type,
            expires_in_hours=request.expires_in_hours,
            auto_approve=request.auto_approve,
        )

        self._tasks[review_id] = task

        # 记录历史
        self._add_history(
            review_id=review_id,
            action="created",
            actor=request.submitted_by,
            new_status=ReviewStatus.PENDING,
            details=f"创建审核任务: {request.title}",
        )

        logger.info(
            f"[ReviewService] 创建审核任务 | "
            f"review_id={review_id} | "
            f"task_type={request.task_type} | "
            f"risk_level={request.risk_level}"
        )

        return task

    def should_require_review(
        self,
        task_type: TaskType,
        risk_level: RiskLevel,
    ) -> bool:
        """判断是否需要审核。

        Args:
            task_type: 任务类型
            risk_level: 风险等级

        Returns:
            是否需要审核
        """
        # 检查风险等级
        if risk_level in self.review_policy.require_review_risk_levels:
            return True

        # 检查任务类型
        if task_type in self.review_policy.require_review_task_types:
            return True

        return False

    def assign_reviewer(
        self,
        review_id: str,
        reviewer_id: str,
        assigned_by: str | None = None,
    ) -> ReviewTask:
        """分配审核人。

        Args:
            review_id: 审核 ID
            reviewer_id: 审核人 ID
            assigned_by: 分配人 ID

        Returns:
            更新后的审核任务
        """
        task = self._get_task(review_id)

        task.assigned_to = reviewer_id
        task.assigned_at = datetime.now()
        task.status = ReviewStatus.IN_REVIEW

        self._add_history(
            review_id=review_id,
            action="assigned",
            actor=assigned_by or "system",
            new_status=ReviewStatus.IN_REVIEW,
            details=f"分配审核人: {reviewer_id}",
        )

        logger.info(
            f"[ReviewService] 分配审核人 | review_id={review_id} | reviewer={reviewer_id}"
        )

        return task

    def submit_decision(
        self,
        review_id: str,
        decision: ReviewDecision,
        reviewer_id: str,
        reason: str | None = None,
        revised_content: str | None = None,
        revision_notes: str | None = None,
    ) -> ReviewTask:
        """提交审核决策。

        Args:
            review_id: 审核 ID
            decision: 审核决策
            reviewer_id: 审核人 ID
            reason: 决策理由
            revised_content: 修订后的内容
            revision_notes: 修订说明

        Returns:
            更新后的审核任务
        """
        task = self._get_task(review_id)

        previous_status = task.status

        task.decision = decision
        task.decision_reason = reason
        task.reviewed_by = reviewer_id
        task.reviewed_at = datetime.now()
        task.revised_content = revised_content
        task.revision_notes = revision_notes

        # 根据决策更新状态
        if decision == ReviewDecision.APPROVE:
            task.status = ReviewStatus.APPROVED
        elif decision == ReviewDecision.REJECT:
            task.status = ReviewStatus.REJECTED
        elif decision == ReviewDecision.REVISE:
            task.status = ReviewStatus.REVISED
        elif decision == ReviewDecision.ESCALATE:
            task.status = ReviewStatus.PENDING
            task.assigned_to = None
            task.assigned_at = None

        self._add_history(
            review_id=review_id,
            action="decided",
            actor=reviewer_id,
            previous_status=previous_status,
            new_status=task.status,
            details=f"审核决策: {decision.value}",
        )

        logger.info(
            f"[ReviewService] 审核决策 | review_id={review_id} | "
            f"decision={decision} | reviewer={reviewer_id}"
        )

        return task

    def get_task(
        self,
        review_id: str,
    ) -> ReviewTask | None:
        """获取审核任务。

        Args:
            review_id: 审核 ID

        Returns:
            审核任务，如果不存在返回 None
        """
        return self._tasks.get(review_id)

    def get_pending_tasks(
        self,
        reviewer_id: str | None = None,
        task_type: TaskType | None = None,
        limit: int = 20,
    ) -> list[ReviewTask]:
        """获取待审核任务。

        Args:
            reviewer_id: 审核人 ID（可选）
            task_type: 任务类型（可选）
            limit: 返回数量

        Returns:
            待审核任务列表
        """
        pending = [
            task for task in self._tasks.values()
            if task.status in (ReviewStatus.PENDING, ReviewStatus.IN_REVIEW)
        ]

        # 过滤审核人
        if reviewer_id:
            pending = [
                task for task in pending
                if task.assigned_to == reviewer_id or task.assigned_to is None
            ]

        # 过滤任务类型
        if task_type:
            pending = [
                task for task in pending
                if task.task_type == task_type
            ]

        # 按提交时间排序
        pending.sort(key=lambda t: t.submitted_at, reverse=True)

        return pending[:limit]

    def get_reviewed_tasks(
        self,
        reviewer_id: str | None = None,
        status: ReviewStatus | None = None,
        limit: int = 20,
    ) -> list[ReviewTask]:
        """获取已审核任务。

        Args:
            reviewer_id: 审核人 ID（可选）
            status: 审核状态（可选）
            limit: 返回数量

        Returns:
            已审核任务列表
        """
        reviewed = [
            task for task in self._tasks.values()
            if task.status not in (ReviewStatus.PENDING, ReviewStatus.IN_REVIEW)
        ]

        # 过滤审核人
        if reviewer_id:
            reviewed = [
                task for task in reviewed
                if task.reviewed_by == reviewer_id
            ]

        # 过滤状态
        if status:
            reviewed = [
                task for task in reviewed
                if task.status == status
            ]

        # 按审核时间排序
        reviewed.sort(key=lambda t: t.reviewed_at or datetime.min, reverse=True)

        return reviewed[:limit]

    def cancel_review(
        self,
        review_id: str,
        cancelled_by: str,
        reason: str | None = None,
    ) -> ReviewTask:
        """取消审核任务。

        Args:
            review_id: 审核 ID
            cancelled_by: 取消人 ID
            reason: 取消原因

        Returns:
            更新后的审核任务
        """
        task = self._get_task(review_id)

        previous_status = task.status
        task.status = ReviewStatus.CANCELLED

        self._add_history(
            review_id=review_id,
            action="cancelled",
            actor=cancelled_by,
            previous_status=previous_status,
            new_status=ReviewStatus.CANCELLED,
            details=f"取消审核: {reason}" if reason else "取消审核",
        )

        logger.info(
            f"[ReviewService] 取消审核 | review_id={review_id} | cancelled_by={cancelled_by}"
        )

        return task

    def get_statistics(self) -> dict:
        """获取审核统计信息。

        Returns:
            统计信息
        """
        total = len(self._tasks)
        pending = sum(1 for t in self._tasks.values() if t.status == ReviewStatus.PENDING)
        in_review = sum(1 for t in self._tasks.values() if t.status == ReviewStatus.IN_REVIEW)
        approved = sum(1 for t in self._tasks.values() if t.status == ReviewStatus.APPROVED)
        rejected = sum(1 for t in self._tasks.values() if t.status == ReviewStatus.REJECTED)

        return {
            "total": total,
            "pending": pending,
            "in_review": in_review,
            "approved": approved,
            "rejected": rejected,
            "approved_rate": approved / total if total > 0 else 0,
        }

    def _get_task(self, review_id: str) -> ReviewTask:
        """获取审核任务，如果不存在抛出异常。"""
        task = self._tasks.get(review_id)
        if not task:
            raise ValueError(f"审核任务不存在: {review_id}")
        return task

    def _add_history(
        self,
        review_id: str,
        action: str,
        actor: str,
        new_status: ReviewStatus,
        details: str | None = None,
        previous_status: ReviewStatus | None = None,
    ) -> None:
        """添加历史记录。"""
        history = ReviewHistory(
            review_id=review_id,
            action=action,
            actor=actor,
            timestamp=datetime.now(),
            details=details,
            previous_status=previous_status,
            new_status=new_status,
        )
        self._history.append(history)
