"""合同审查数据模型。

定义合同解析、条款抽取和风险识别的数据结构。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ==================== 枚举定义 ====================


class RiskLevel(str, Enum):
    """风险等级。"""

    LOW = "low"  # 低风险
    MEDIUM = "medium"  # 中风险
    HIGH = "high"  # 高风险
    CRITICAL = "critical"  # 严重风险


class RiskCategory(str, Enum):
    """风险类别。"""

    TYRANNY = "霸王条款"  # 明显不公平的条款
    AMBIGUOUS = "模糊表述"  # 表述不明确可能引发争议
    VIOLATION = "违规条款"  # 违反法律法规的条款
    MISSING = "缺失条款"  # 应该约定但缺失的条款
    UNEQUAL = "不对等条款"  # 双方权利义务不对等


class ContractType(str, Enum):
    """合同类型。"""

    PROCUREMENT = "采购合同"
    SALES = "销售合同"
    SERVICE = "服务合同"
    LEASE = "租赁合同"
    LABOR = "劳动合同"
    CONSTRUCTION = "施工合同"
    NDA = "保密协议"
    COOPERATION = "合作协议"
    OTHER = "其他"


class ReviewStatus(str, Enum):
    """审查状态。"""

    PENDING = "pending"  # 待审查
    APPROVED = "approved"  # 通过
    REJECTED = "rejected"  # 拒绝
    REVISED = "revised"  # 修改后通过
    EXPIRED = "expired"  # 已过期
    CANCELLED = "cancelled"  # 已取消


# ==================== 基础模型 ====================


class ContractParty(BaseModel):
    """合同当事人。"""

    name: str = Field(description="当事人名称")
    role: Literal["甲方", "乙方", "丙方", "丁方", "其他"] = Field(description="角色")
    entity_type: Optional[str] = Field(default=None, description="主体类型（公司/个人）")
    address: Optional[str] = Field(default=None, description="地址")
    contact: Optional[str] = Field(default=None, description="联系方式")
    legal_representative: Optional[str] = Field(default=None, description="法定代表人")


class ContractClause(BaseModel):
    """合同条款。"""

    clause_id: str = Field(description="条款编号，如'第1条'")
    clause_type: str = Field(description="条款类型（标的/价款/期限/违约责任等）")
    clause_title: str = Field(description="条款标题")
    clause_content: str = Field(description="条款内容原文")
    key_points: list[str] = Field(default_factory=list, description="关键要点")
    risk_indicators: list[str] = Field(default_factory=list, description="风险指标")
    importance: Literal["关键", "重要", "一般"] = Field(default="一般", description="条款重要性")


class ContractRisk(BaseModel):
    """合同风险。"""

    risk_id: str = Field(description="风险编号，如'R001'")
    risk_type: RiskLevel = Field(description="风险等级")
    risk_category: RiskCategory = Field(description="风险类别")
    risk_description: str = Field(description="风险描述")
    related_clause: str = Field(description="相关条款编号")
    suggestion: str = Field(description="修改建议")
    legal_basis: Optional[str] = Field(default=None, description="法律依据")
    is_blocking: bool = Field(default=False, description="是否为阻断性问题")


class ContractMetadata(BaseModel):
    """合同元数据。"""

    contract_value: Optional[str] = Field(default=None, description="合同金额")
    contract_period: Optional[str] = Field(default=None, description="合同期限")
    payment_method: Optional[str] = Field(default=None, description="付款方式")
    delivery_terms: Optional[str] = Field(default=None, description="交付条款")
    warranty_period: Optional[str] = Field(default=None, description="质保期")
    effective_date: Optional[datetime] = Field(default=None, description="生效日期")
    expiration_date: Optional[datetime] = Field(default=None, description="到期日期")


# ==================== 审查报告模型 ====================


class ContractReviewReport(BaseModel):
    """合同审查报告。"""

    report_id: str = Field(description="报告 ID")
    contract_id: str = Field(description="合同 ID")
    contract_name: str = Field(description="合同名称")
    contract_type: ContractType = Field(description="合同类型")
    review_time: datetime = Field(description="审查时间")

    # 合同基本信息
    parties: list[ContractParty] = Field(description="当事人列表")
    metadata: ContractMetadata = Field(description="合同元数据")

    # 审查结果摘要
    overall_risk_level: RiskLevel = Field(description="整体风险等级")
    risk_summary: str = Field(description="风险概要")
    high_risk_count: int = Field(default=0, description="高风险数量")
    medium_risk_count: int = Field(default=0, description="中风险数量")
    low_risk_count: int = Field(default=0, description="低风险数量")

    # 风险列表
    risks: list[ContractRisk] = Field(default_factory=list, description="风险列表")
    key_concerns: list[str] = Field(default_factory=list, description="重点关注项")

    # 条款分析
    clauses: list[ContractClause] = Field(default_factory=list, description="抽取的条款")
    missing_clauses: list[str] = Field(default_factory=list, description="缺失的重要条款")

    # 模板对比
    template_comparison: Optional[dict] = Field(default=None, description="模板对比结果")

    # 建议
    suggestions: list[str] = Field(default_factory=list, description="修改建议")
    conclusion: str = Field(description="审查结论")
    reviewer_notes: Optional[str] = Field(default=None, description="审查备注")


# ==================== 审查请求/响应 ====================


class ContractReviewRequest(BaseModel):
    """合同审查请求。"""

    contract_file_id: str = Field(description="合同文件 ID")
    contract_name: Optional[str] = Field(default=None, description="合同名称")
    contract_type: Optional[ContractType] = Field(default=None, description="合同类型")
    business_domain: Optional[str] = Field(default=None, description="业务域")
    submitted_by: str = Field(description="提交人")
    submitter_role: str = Field(default="user", description="提交人角色")


class ContractReviewResponse(BaseModel):
    """合同审查响应。"""

    review_id: str = Field(description="审查 ID")
    contract_id: str = Field(description="合同 ID")
    contract_name: str = Field(description="合同名称")
    contract_type: ContractType = Field(description="合同类型")
    overall_risk_level: RiskLevel = Field(description="整体风险等级")
    status: ReviewStatus = Field(description="审查状态")
    need_human_review: bool = Field(description="是否需要人工复核")
    report: Optional[ContractReviewReport] = Field(default=None, description="审查报告")
    created_at: datetime = Field(description="创建时间")
    processing_time_ms: int = Field(description="处理时间（毫秒）")


# ==================== 辅助模型 ====================


class ClauseType(str, Enum):
    """条款类型枚举。"""

    当事人信息 = "当事人信息"
    标的条款 = "标的条款"
    价款条款 = "价款条款"
    履行期限 = "履行期限"
    履行地点 = "履行地点"
    履行方式 = "履行方式"
    质量标准 = "质量标准"
    验收标准 = "验收标准"
    保密条款 = "保密条款"
    知识产权 = "知识产权"
    违约责任 = "违约责任"
    争议解决 = "争议解决"
    合同变更 = "合同变更"
    合同解除 = "合同解除"
    不可抗力 = "不可抗力"
    其他条款 = "其他条款"


class RiskIndicatorKeywords:
    """风险关键词映射。

    用于识别合同中的潜在风险点。
    """

    HIGH_RISK = [
        "无条件解除",
        "无限责任",
        "免除全部责任",
        "强制仲裁",
        "不得诉讼",
        "放弃抗辩",
        "单方解释权",
        "无条件赔偿",
        "排除对方权利",
        "永久有效",
        "不得终止",
    ]

    MEDIUM_RISK = [
        "违约金过高",
        "赔偿无上限",
        "单方变更",
        "限制权利",
        "不得转让",
        "保密范围过宽",
        "竞业限制过严",
        "延迟付款",
        "自动续期",
    ]

    LOW_RISK = [
        "建议明确",
        "建议补充",
        "可进一步细化",
        "建议增加",
        "建议修改",
    ]
