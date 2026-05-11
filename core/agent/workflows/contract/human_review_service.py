"""合同审核 Human Review 服务。

提供人工复核功能：
1. 创建复核任务
2. 获取复核状态
3. 提交复核结果
4. 复核历史记录

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ReviewPriority(str, Enum):
    """复核优先级。"""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ReviewDecision(str, Enum):
    """复核决定。"""

    APPROVED = "approved"  # 通过
    REJECTED = "rejected"  # 拒绝
    REVISED = "revised"  # 修改后通过
    ESCALATED = "escalated"  # 升级处理


class RiskItem(BaseModel):
    """风险项。"""

    risk_id: str = Field(description="风险ID")
    risk_type: str = Field(description="风险类型")
    risk_description: str = Field(description="风险描述")
    related_clause: str = Field(description="相关条款")
    suggestion: str = Field(description="建议")


class HumanReviewTask(BaseModel):
    """人工复核任务。"""

    review_id: str = Field(description="复核任务ID")
    run_id: str = Field(description="关联的运行ID")
    contract_name: str = Field(description="合同名称")
    contract_type: Optional[str] = Field(default=None, description="合同类型")

    # 任务信息
    priority: ReviewPriority = Field(default=ReviewPriority.NORMAL, description="优先级")
    status: str = Field(default="pending", description="状态：pending/in_progress/completed/cancelled")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")
    deadline: Optional[datetime] = Field(default=None, description="截止时间")

    # 复核内容
    risk_items: List[RiskItem] = Field(default_factory=list, description="高风险项")
    review_reason: str = Field(description="请求复核原因")
    contract_summary: Optional[str] = Field(default=None, description="合同摘要")

    # 复核结果
    reviewer_id: Optional[str] = Field(default=None, description="复核人ID")
    reviewer_name: Optional[str] = Field(default=None, description="复核人名称")
    decision: Optional[ReviewDecision] = Field(default=None, description="复核决定")
    comments: Optional[str] = Field(default=None, description="复核意见")
    completed_at: Optional[datetime] = Field(default=None, description="完成时间")


class HumanReviewService:
    """人工复核服务。

    职责：
    - 创建复核任务
    - 分配复核人员
    - 记录复核结果
    - 查询复核历史

    设计原因：
    - 高风险合同必须经过人工复核
    - 复核流程需要可追溯
    - 复核意见需要记录到报告中
    """

    def __init__(self, db_session: Any = None) -> None:
        """初始化复核服务。

        Args:
            db_session: 数据库会话（可选）
        """
        self.db_session = db_session
        self._tasks: Dict[str, HumanReviewTask] = {}  # 内存存储，生产环境应使用数据库

    def create_review_task(
        self,
        run_id: str,
        contract_name: str,
        risk_items: List[Dict],
        review_reason: str,
        contract_type: Optional[str] = None,
        priority: ReviewPriority = ReviewPriority.NORMAL,
        deadline: Optional[datetime] = None,
        contract_summary: Optional[str] = None,
    ) -> HumanReviewTask:
        """创建人工复核任务。

        Args:
            run_id: 关联的运行ID
            contract_name: 合同名称
            risk_items: 高风险项列表
            review_reason: 请求复核原因
            contract_type: 合同类型
            priority: 优先级
            deadline: 截止时间
            contract_summary: 合同摘要

        Returns:
            创建的复核任务
        """
        review_id = f"review_{uuid4().hex[:12]}"

        # 转换风险项
        risk_models = [
            RiskItem(
                risk_id=item.get("risk_id", f"R{i}"),
                risk_type=item.get("risk_type", "unknown"),
                risk_description=item.get("risk_description", ""),
                related_clause=item.get("related_clause", ""),
                suggestion=item.get("suggestion", ""),
            )
            for i, item in enumerate(risk_items)
        ]

        task = HumanReviewTask(
            review_id=review_id,
            run_id=run_id,
            contract_name=contract_name,
            contract_type=contract_type,
            priority=priority,
            status="pending",
            risk_items=risk_models,
            review_reason=review_reason,
            deadline=deadline,
            contract_summary=contract_summary,
        )

        # 存储任务
        self._tasks[review_id] = task

        logger.info(
            f"[HumanReview] 创建复核任务 | review_id={review_id} | "
            f"contract={contract_name} | 高风险项: {len(risk_items)}"
        )

        return task

    def get_review_task(self, review_id: str) -> Optional[HumanReviewTask]:
        """获取复核任务。

        Args:
            review_id: 复核任务ID

        Returns:
            复核任务，如果不存在返回 None
        """
        return self._tasks.get(review_id)

    def get_review_task_by_run_id(self, run_id: str) -> Optional[HumanReviewTask]:
        """根据 run_id 获取复核任务。

        Args:
            run_id: 运行ID

        Returns:
            复核任务
        """
        for task in self._tasks.values():
            if task.run_id == run_id:
                return task
        return None

    def update_review_task(
        self,
        review_id: str,
        reviewer_id: Optional[str] = None,
        reviewer_name: Optional[str] = None,
        status: Optional[str] = None,
        decision: Optional[ReviewDecision] = None,
        comments: Optional[str] = None,
    ) -> Optional[HumanReviewTask]:
        """更新复核任务。

        Args:
            review_id: 复核任务ID
            reviewer_id: 复核人ID
            reviewer_name: 复核人名称
            status: 状态
            decision: 复核决定
            comments: 复核意见

        Returns:
            更新后的任务
        """
        task = self._tasks.get(review_id)
        if not task:
            logger.warning(f"[HumanReview] 任务不存在: {review_id}")
            return None

        # 更新字段
        if reviewer_id is not None:
            task.reviewer_id = reviewer_id
        if reviewer_name is not None:
            task.reviewer_name = reviewer_name
        if status is not None:
            task.status = status
        if decision is not None:
            task.decision = decision
        if comments is not None:
            task.comments = comments

        task.updated_at = datetime.now()

        if decision and task.status != "completed":
            task.status = "completed"
            task.completed_at = datetime.now()

        logger.info(
            f"[HumanReview] 更新复核任务 | review_id={review_id} | "
            f"decision={decision} | status={task.status}"
        )

        return task

    def submit_review_result(
        self,
        review_id: str,
        reviewer_id: str,
        reviewer_name: str,
        decision: ReviewDecision,
        comments: str,
    ) -> Optional[HumanReviewTask]:
        """提交复核结果。

        Args:
            review_id: 复核任务ID
            reviewer_id: 复核人ID
            reviewer_name: 复核人名称
            decision: 复核决定
            comments: 复核意见

        Returns:
            更新后的任务
        """
        return self.update_review_task(
            review_id=review_id,
            reviewer_id=reviewer_id,
            reviewer_name=reviewer_name,
            status="completed",
            decision=decision,
            comments=comments,
        )

    def cancel_review_task(self, review_id: str) -> Optional[HumanReviewTask]:
        """取消复核任务。

        Args:
            review_id: 复核任务ID

        Returns:
            更新后的任务
        """
        return self.update_review_task(review_id=review_id, status="cancelled")

    def list_pending_reviews(
        self,
        priority: Optional[ReviewPriority] = None,
        limit: int = 100,
    ) -> List[HumanReviewTask]:
        """列出待复核任务。

        Args:
            priority: 按优先级过滤
            limit: 返回数量限制

        Returns:
            待复核任务列表
        """
        tasks = [
            task for task in self._tasks.values()
            if task.status == "pending"
        ]

        if priority:
            tasks = [t for t in tasks if t.priority == priority]

        # 按优先级和创建时间排序
        priority_order = {
            ReviewPriority.URGENT: 0,
            ReviewPriority.HIGH: 1,
            ReviewPriority.NORMAL: 2,
            ReviewPriority.LOW: 3,
        }
        tasks.sort(key=lambda t: (priority_order.get(t.priority, 99), t.created_at))

        return tasks[:limit]

    def list_reviews_by_reviewer(
        self,
        reviewer_id: str,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[HumanReviewTask]:
        """列出复核人的复核任务。

        Args:
            reviewer_id: 复核人ID
            status: 按状态过滤
            limit: 返回数量限制

        Returns:
            复核任务列表
        """
        tasks = [
            task for task in self._tasks.values()
            if task.reviewer_id == reviewer_id
        ]

        if status:
            tasks = [t for t in tasks if t.status == status]

        # 按更新时间倒序
        tasks.sort(key=lambda t: t.updated_at, reverse=True)

        return tasks[:limit]

    def get_review_history(
        self,
        run_id: Optional[str] = None,
        contract_name: Optional[str] = None,
        reviewer_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[HumanReviewTask]:
        """获取复核历史。

        Args:
            run_id: 按运行ID过滤
            contract_name: 按合同名称过滤
            reviewer_id: 按复核人过滤
            start_date: 开始日期
            end_date: 结束日期
            limit: 返回数量限制

        Returns:
            复核任务列表
        """
        tasks = list(self._tasks.values())

        # 应用过滤条件
        if run_id:
            tasks = [t for t in tasks if t.run_id == run_id]
        if contract_name:
            tasks = [t for t in tasks if contract_name in t.contract_name]
        if reviewer_id:
            tasks = [t for t in tasks if t.reviewer_id == reviewer_id]
        if start_date:
            tasks = [t for t in tasks if t.created_at >= start_date]
        if end_date:
            tasks = [t for t in tasks if t.created_at <= end_date]

        # 只返回已完成的任务
        tasks = [t for t in tasks if t.status == "completed"]

        # 按完成时间倒序
        tasks.sort(key=lambda t: t.completed_at or t.updated_at, reverse=True)

        return tasks[:limit]

    def get_review_statistics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """获取复核统计信息。

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            统计信息
        """
        tasks = list(self._tasks.values())

        # 应用日期过滤
        if start_date:
            tasks = [t for t in tasks if t.created_at >= start_date]
        if end_date:
            tasks = [t for t in tasks if t.created_at <= end_date]

        # 统计
        total = len(tasks)
        pending = len([t for t in tasks if t.status == "pending"])
        completed = len([t for t in tasks if t.status == "completed"])
        cancelled = len([t for t in tasks if t.status == "cancelled"])

        # 按决定统计
        decisions = {}
        for task in tasks:
            if task.decision:
                decision_key = task.decision.value
                decisions[decision_key] = decisions.get(decision_key, 0) + 1

        # 按优先级统计
        priorities = {}
        for task in tasks:
            priority_key = task.priority.value
            priorities[priority_key] = priorities.get(priority_key, 0) + 1

        return {
            "total": total,
            "pending": pending,
            "completed": completed,
            "cancelled": cancelled,
            "completion_rate": completed / total if total > 0 else 0,
            "decisions": decisions,
            "priorities": priorities,
            "period": {
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
            },
        }


# ==================== 全局实例 ====================

_human_review_service: HumanReviewService | None = None


def get_human_review_service() -> HumanReviewService:
    """获取 Human Review 服务全局实例。"""
    global _human_review_service

    if _human_review_service is None:
        _human_review_service = HumanReviewService()

    return _human_review_service


def create_review_from_contract_result(
    run_id: str,
    contract_name: str,
    high_risk_items: List[Dict],
    contract_type: Optional[str] = None,
    contract_summary: Optional[str] = None,
) -> HumanReviewTask:
    """从合同审查结果创建复核任务。

    便捷函数，用于在发现高风险项时快速创建复核任务。

    Args:
        run_id: 运行ID
        contract_name: 合同名称
        high_risk_items: 高风险项列表
        contract_type: 合同类型
        contract_summary: 合同摘要

    Returns:
        创建的复核任务
    """
    service = get_human_review_service()

    # 判断优先级
    priority = ReviewPriority.NORMAL
    if len(high_risk_items) >= 5:
        priority = ReviewPriority.HIGH
    if len(high_risk_items) >= 10:
        priority = ReviewPriority.URGENT

    return service.create_review_task(
        run_id=run_id,
        contract_name=contract_name,
        risk_items=high_risk_items,
        review_reason=f"发现 {len(high_risk_items)} 个高风险项，需要人工复核",
        contract_type=contract_type,
        priority=priority,
        contract_summary=contract_summary,
    )
