"""经营分析 Human Review 接口 Schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyticsReviewDecisionRequest(BaseModel):
    """经营分析审核决策请求。"""

    # 审核意见。
    # 当前阶段先保留一个统一 comment 字段，既能用于“通过说明”，也能用于“驳回原因”。
    comment: str | None = Field(default=None, description="审核意见或驳回原因")


class AnalyticsReviewData(BaseModel):
    """经营分析审核任务详情。"""

    review_id: str = Field(description="审核任务 ID")
    subject_type: str = Field(description="审核主题类型")
    subject_id: str = Field(description="审核主题对象 ID")
    run_id: str = Field(description="经营分析运行 ID")
    review_status: str = Field(description="审核状态")
    review_level: str = Field(description="审核级别")
    review_reason: str = Field(description="审核原因")
    requester_user_id: int | None = Field(default=None, description="原始请求用户 ID")
    reviewer: str | None = Field(default=None, description="审核人显示名")
    review_comment: str | None = Field(default=None, description="审核意见")
    reviewed_at: str | None = Field(default=None, description="审核完成时间")
    metadata: dict = Field(default_factory=dict, description="审核扩展元数据")
