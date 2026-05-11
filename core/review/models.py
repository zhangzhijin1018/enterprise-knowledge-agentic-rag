"""Human Review 审核管理数据模型。

定义审核任务、审核状态和审核决策的数据结构。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ==================== 枚举定义 ====================


class ReviewStatus(str, Enum):
    """审核状态。"""

    PENDING = "pending"  # 待审核
    IN_REVIEW = "in_review"  # 审核中
    APPROVED = "approved"  # 通过
    REJECTED = "rejected"  # 拒绝
    REVISED = "revised"  # 修改后通过
    EXPIRED = "expired"  # 已过期
    CANCELLED = "cancelled"  # 已取消


class ReviewDecision(str, Enum):
    """审核决策。"""

    APPROVE = "approve"  # 批准
    REJECT = "reject"  # 拒绝
    REVISE = "revise"  # 要求修改
    ESCALATE = "escalate"  # 升级处理


class RiskLevel(str, Enum):
    """风险等级。"""

    LOW = "low"  # 低风险
    MEDIUM = "medium"  # 中风险
    HIGH = "high"  # 高风险
    CRITICAL = "critical"  # 严重风险


class TaskType(str, Enum):
    """任务类型。"""

    CONTRACT_REVIEW = "contract_review"  # 合同审查
    BUSINESS_ANALYSIS = "business_analysis"  # 经营分析
    REPORT_GENERATION = "report_generation"  # 报告生成
    DATA_EXPORT = "data_export"  # 数据导出
    EXTERNAL_API = "external_api"  # 外部系统调用
    OTHER = "other"  # 其他


# ==================== 审核任务 ====================


class ReviewTask(BaseModel):
    """审核任务。

    记录需要人工复核的任务信息。
    """

    # 任务标识
    review_id: str = Field(description="审核任务 ID")
    task_id: str = Field(description="关联的任务 ID")
    run_id: str = Field(description="关联的运行 ID")

    # 任务信息
    task_type: TaskType = Field(description="任务类型")
    risk_level: RiskLevel = Field(description="风险等级")
    title: str = Field(description="任务标题")
    description: str = Field(description="任务描述")

    # 内容摘要（待审核内容）
    content_summary: str = Field(description="内容摘要")
    content_detail: Optional[str] = Field(default=None, description="详细内容")

    # 关联资源
    resource_id: Optional[str] = Field(default=None, description="关联资源 ID")
    resource_type: Optional[str] = Field(default=None, description="关联资源类型")

    # 提交信息
    submitted_by: str = Field(description="提交人 ID")
    submitted_at: datetime = Field(description="提交时间")

    # 审核信息
    status: ReviewStatus = Field(default=ReviewStatus.PENDING, description="审核状态")
    assigned_to: Optional[str] = Field(default=None, description="审核人 ID")
    assigned_at: Optional[datetime] = Field(default=None, description="分配时间")

    # 审核决策
    decision: Optional[ReviewDecision] = Field(default=None, description="审核决策")
    decision_reason: Optional[str] = Field(default=None, description="决策理由")
    reviewed_by: Optional[str] = Field(default=None, description="审核人")
    reviewed_at: Optional[datetime] = Field(default=None, description="审核时间")

    # 修订信息
    revised_content: Optional[str] = Field(default=None, description="修订后的内容")
    revision_notes: Optional[str] = Field(default=None, description="修订说明")

    # 过期设置
    expires_at: Optional[datetime] = Field(default=None, description="过期时间")
    auto_approve: bool = Field(default=False, description="是否自动批准")

    # 元数据
    metadata: dict = Field(default_factory=dict, description="扩展元数据")


# ==================== 审核请求/响应 ====================


class ReviewRequest(BaseModel):
    """创建审核请求。"""

    task_id: str = Field(description="任务 ID")
    run_id: str = Field(description="运行 ID")
    task_type: TaskType = Field(description="任务类型")
    risk_level: RiskLevel = Field(description="风险等级")
    title: str = Field(description="任务标题")
    description: str = Field(description="任务描述")
    content_summary: str = Field(description="内容摘要")
    content_detail: Optional[str] = Field(default=None, description="详细内容")
    resource_id: Optional[str] = Field(default=None, description="关联资源 ID")
    resource_type: Optional[str] = Field(default=None, description="关联资源类型")
    submitted_by: str = Field(description="提交人 ID")
    expires_in_hours: Optional[int] = Field(default=72, description="过期时间（小时）")
    auto_approve: bool = Field(default=False, description="是否自动批准")


class ReviewResponse(BaseModel):
    """审核响应。"""

    review_id: str = Field(description="审核 ID")
    status: ReviewStatus = Field(description="审核状态")
    message: str = Field(description="响应消息")


class ReviewDecisionRequest(BaseModel):
    """审核决策请求。"""

    decision: ReviewDecision = Field(description="审核决策")
    reason: Optional[str] = Field(default=None, description="决策理由")
    revised_content: Optional[str] = Field(default=None, description="修订后的内容")
    revision_notes: Optional[str] = Field(default=None, description="修订说明")


# ==================== 审核策略 ====================


class ReviewPolicy(BaseModel):
    """审核策略。

    定义哪些任务需要人工审核。
    """

    # 需要审核的风险等级
    require_review_risk_levels: list[RiskLevel] = Field(
        default_factory=lambda: [RiskLevel.HIGH, RiskLevel.CRITICAL],
        description="需要审核的风险等级"
    )

    # 需要审核的任务类型
    require_review_task_types: list[TaskType] = Field(
        default_factory=lambda: [
            TaskType.CONTRACT_REVIEW,
            TaskType.DATA_EXPORT,
            TaskType.EXTERNAL_API,
        ],
        description="需要审核的任务类型"
    )

    # 自动批准的条件
    auto_approve_conditions: dict = Field(
        default_factory=dict,
        description="自动批准条件"
    )

    # 审核超时（小时）
    review_timeout_hours: int = Field(default=72, description="审核超时时间")

    # 升级策略
    escalate_on_timeout: bool = Field(default=True, description="超时时是否升级")


# ==================== 审核历史 ====================


class ReviewHistory(BaseModel):
    """审核历史记录。"""

    review_id: str = Field(description="审核 ID")
    action: str = Field(description="操作类型")
    actor: str = Field(description="操作人")
    timestamp: datetime = Field(description="操作时间")
    details: Optional[str] = Field(default=None, description="操作详情")
    previous_status: Optional[ReviewStatus] = Field(default=None, description="操作前状态")
    new_status: ReviewStatus = Field(description="操作后状态")


# ==================== 辅助函数 ====================


def create_review_task(
    review_id: str,
    task_id: str,
    run_id: str,
    task_type: TaskType,
    risk_level: RiskLevel,
    title: str,
    description: str,
    content_summary: str,
    submitted_by: str,
    **kwargs,
) -> ReviewTask:
    """创建审核任务。

    Args:
        review_id: 审核 ID
        task_id: 任务 ID
        run_id: 运行 ID
        task_type: 任务类型
        risk_level: 风险等级
        title: 标题
        description: 描述
        content_summary: 内容摘要
        submitted_by: 提交人
        **kwargs: 其他参数

    Returns:
        审核任务
    """
    from datetime import timedelta

    # 计算过期时间
    expires_in_hours = kwargs.get("expires_in_hours", 72)
    expires_at = None
    if expires_in_hours:
        expires_at = datetime.now() + timedelta(hours=expires_in_hours)

    return ReviewTask(
        review_id=review_id,
        task_id=task_id,
        run_id=run_id,
        task_type=task_type,
        risk_level=risk_level,
        title=title,
        description=description,
        content_summary=content_summary,
        content_detail=kwargs.get("content_detail"),
        resource_id=kwargs.get("resource_id"),
        resource_type=kwargs.get("resource_type"),
        submitted_by=submitted_by,
        submitted_at=datetime.now(),
        status=ReviewStatus.PENDING,
        expires_at=expires_at,
        auto_approve=kwargs.get("auto_approve", False),
        metadata=kwargs.get("metadata", {}),
    )
