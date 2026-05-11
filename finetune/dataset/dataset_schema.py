"""合同审查条款提取数据集格式定义。

本模块定义 LoRA 微调训练数据集的格式规范，包括：
1. 数据格式类型（训练/验证/测试）
2. 各字段的含义和约束
3. 质量评估标准

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
import json


class ContractClauseType(str, Enum):
    """合同条款类型枚举。

    用于条款分类，便于训练数据标注和模型评估。
    """

    # 标的条款
    SUBJECT = "标的条款"

    # 价款条款
    PRICE = "价款条款"

    # 履行期限
    PERFORMANCE_PERIOD = "履行期限"

    # 质量标准
    QUALITY = "质量标准"

    # 违约责任
    BREACH = "违约责任"

    # 争议解决
    DISPUTE = "争议解决"

    # 保密条款
    CONFIDENTIALITY = "保密条款"

    # 知识产权
    IP = "知识产权"

    # 不可抗力
    FORCE_MAJEURE = "不可抗力"

    # 合同变更
    MODIFICATION = "合同变更"

    # 合同解除
    TERMINATION = "合同解除"

    # 其他条款
    OTHER = "其他条款"


class RiskLevel(str, Enum):
    """风险等级枚举。"""

    HIGH = "高风险"
    MEDIUM = "中风险"
    LOW = "低风险"
    NONE = "无风险"


@dataclass
class ClauseAnnotation:
    """条款标注数据。

    对应 output 中的单个条款对象。
    """

    # 条款编号
    clause_id: str

    # 条款类型
    clause_type: str

    # 条款标题（50字以内）
    clause_title: str

    # 条款完整内容
    clause_content: str

    # 风险指示器
    risk_indicators: list[str] = field(default_factory=list)

    # 风险等级
    risk_level: str = RiskLevel.NONE.value

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "clause_id": self.clause_id,
            "clause_type": self.clause_type,
            "clause_title": self.clause_title,
            "clause_content": self.clause_content,
            "risk_indicators": self.risk_indicators,
            "risk_level": self.risk_level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClauseAnnotation":
        """从字典创建。"""
        return cls(
            clause_id=data["clause_id"],
            clause_type=data["clause_type"],
            clause_title=data["clause_title"],
            clause_content=data["clause_content"],
            risk_indicators=data.get("risk_indicators", []),
            risk_level=data.get("risk_level", RiskLevel.NONE.value),
        )


@dataclass
class PartyAnnotation:
    """当事人标注数据。"""

    # 当事人名称
    name: str

    # 角色（甲方/乙方/丙方等）
    role: str

    # 统一社会信用代码（可选）
    credit_code: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        result = {
            "name": self.name,
            "role": self.role,
        }
        if self.credit_code:
            result["credit_code"] = self.credit_code
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PartyAnnotation":
        """从字典创建。"""
        return cls(
            name=data["name"],
            role=data["role"],
            credit_code=data.get("credit_code"),
        )


@dataclass
class ContractAnnotation:
    """合同完整标注数据。

    对应一条完整的训练样本。
    """

    # 唯一标识
    sample_id: str

    # 合同文本
    contract_text: str

    # 合同类型
    contract_type: str

    # 条款列表
    clauses: list[ClauseAnnotation]

    # 当事人列表
    parties: list[PartyAnnotation]

    # 疑似缺失的必要条款类型
    missing_clauses: list[str]

    # 法律检索主题（供 search_laws 使用）
    legal_search_topics: list[str]

    # 合同涉及的法律问题
    contract_legal_issues: list[str]

    # 元数据
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_training_sample(self) -> dict[str, Any]:
        """转换为训练样本格式。

        生成符合 LLaMA-Factory 和 PEFT 要求的 JSON 格式。
        """
        output = {
            "clauses": [c.to_dict() for c in self.clauses],
            "parties": [p.to_dict() for p in self.parties],
            "missing_clauses": self.missing_clauses,
            "legal_search_topics": self.legal_search_topics,
            "contract_legal_issues": self.contract_legal_issues,
        }

        return {
            "sample_id": self.sample_id,
            "instruction": self._build_instruction(),
            "input": self._build_input(),
            "output": json.dumps(output, ensure_ascii=False),
            "metadata": self.metadata,
        }

    def _build_instruction(self) -> str:
        """构建 instruction 部分。"""
        return (
            "你是一个专业的合同法律审查助手。请分析以下合同内容，"
            "提取完整的条款信息，以JSON格式返回。"
        )

    def _build_input(self) -> str:
        """构建 input 部分。"""
        contract_type_hint = f"合同类型：{self.contract_type}"
        return f"{contract_type_hint}\n\n合同全文：\n---\n{self.contract_text}\n---"

    @classmethod
    def from_training_sample(cls, sample: dict[str, Any]) -> "ContractAnnotation":
        """从训练样本创建标注对象。"""
        output = json.loads(sample["output"])
        return cls(
            sample_id=sample["sample_id"],
            contract_text=cls._extract_contract_text(sample["input"]),
            contract_type=cls._extract_contract_type(sample["input"]),
            clauses=[ClauseAnnotation.from_dict(c) for c in output.get("clauses", [])],
            parties=[PartyAnnotation.from_dict(p) for p in output.get("parties", [])],
            missing_clauses=output.get("missing_clauses", []),
            legal_search_topics=output.get("legal_search_topics", []),
            contract_legal_issues=output.get("contract_legal_issues", []),
            metadata=sample.get("metadata", {}),
        )

    @staticmethod
    def _extract_contract_text(input_text: str) -> str:
        """从 input 中提取合同文本。"""
        if "---" in input_text:
            parts = input_text.split("---")
            if len(parts) >= 2:
                return parts[-1].strip()
        return input_text

    @staticmethod
    def _extract_contract_type(input_text: str) -> str:
        """从 input 中提取合同类型。"""
        if "合同类型：" in input_text:
            lines = input_text.split("\n")
            for line in lines:
                if "合同类型：" in line:
                    return line.split("合同类型：")[-1].strip()
        return "未知"


@dataclass
class DatasetConfig:
    """数据集配置。"""

    # 数据集名称
    name: str = "contract_clauses"

    # 训练集比例
    train_ratio: float = 0.8

    # 验证集比例
    val_ratio: float = 0.1

    # 测试集比例
    test_ratio: float = 0.1

    # 最小合同长度（字符）
    min_contract_length: int = 200

    # 最大合同长度（字符）
    max_contract_length: int = 10000

    # 每种条款类型最少样本数
    min_samples_per_clause_type: int = 20

    def validate(self) -> list[str]:
        """验证配置合法性。

        Returns:
            错误列表，空表示配置合法
        """
        errors = []

        total = self.train_ratio + self.val_ratio + self.test_ratio
        if abs(total - 1.0) > 0.001:
            errors.append(f"数据集比例之和必须为1.0，当前为 {total}")

        if self.train_ratio <= 0 or self.val_ratio <= 0 or self.test_ratio <= 0:
            errors.append("各数据集比例必须大于0")

        if self.min_contract_length <= 0:
            errors.append("最小合同长度必须大于0")

        if self.max_contract_length <= self.min_contract_length:
            errors.append("最大合同长度必须大于最小合同长度")

        return errors


# ==================== 数据质量标准 ====================


class DataQualityStandard:
    """数据质量标准定义。

    用于评估训练数据的质量和完整性。
    """

    # 条款完整性：正常合同应包含的必要条款数量范围
    CLAUSE_COUNT_RANGE = (3, 50)

    # 当事人完整性：正常合同应有1-10个当事人
    PARTY_COUNT_RANGE = (1, 10)

    # 风险指示器最大数量（避免过于冗余）
    MAX_RISK_INDICATORS = 5

    # 缺失条款最大数量（合理范围）
    MAX_MISSING_CLAUSES = 5

    # 检索主题数量范围
    LEGAL_TOPIC_RANGE = (2, 10)

    @classmethod
    def validate_clause_annotation(cls, clause: ClauseAnnotation) -> list[str]:
        """验证条款标注质量。

        Args:
            clause: 条款标注

        Returns:
            问题列表，空表示质量合格
        """
        issues = []

        if not clause.clause_id:
            issues.append("条款ID为空")

        if not clause.clause_type:
            issues.append("条款类型为空")

        if clause.clause_type not in [t.value for t in ContractClauseType]:
            issues.append(f"条款类型 '{clause.clause_type}' 不符合枚举定义")

        if len(clause.clause_content) < 10:
            issues.append("条款内容过短（少于10字符）")

        if clause.risk_level not in [r.value for r in RiskLevel]:
            issues.append(f"风险等级 '{clause.risk_level}' 不符合枚举定义")

        if len(clause.risk_indicators) > cls.MAX_RISK_INDICATORS:
            issues.append(
                f"风险指示器数量({len(clause.risk_indicators)})超过最大限制({cls.MAX_RISK_INDICATORS})"
            )

        return issues

    @classmethod
    def validate_contract_annotation(
        cls, annotation: ContractAnnotation
    ) -> list[str]:
        """验证合同标注质量。

        Args:
            annotation: 合同标注

        Returns:
            问题列表，空表示质量合格
        """
        issues = []

        # 检查合同文本长度
        if len(annotation.contract_text) < cls.min_contract_length:
            issues.append(
                f"合同文本过短（{len(annotation.contract_text)}字符，"
                f"要求至少{cls.min_contract_length}字符）"
            )

        if len(annotation.contract_text) > cls.max_contract_length:
            issues.append(
                f"合同文本过长（{len(annotation.contract_text)}字符，"
                f"要求最多{cls.max_contract_length}字符）"
            )

        # 检查条款数量
        clause_count = len(annotation.clauses)
        if clause_count < cls.CLAUSE_COUNT_RANGE[0]:
            issues.append(
                f"条款数量过少（{clause_count}条，"
                f"要求至少{cls.CLAUSE_COUNT_RANGE[0]}条）"
            )

        if clause_count > cls.CLAUSE_COUNT_RANGE[1]:
            issues.append(
                f"条款数量过多（{clause_count}条，"
                f"要求最多{cls.CLAUSE_COUNT_RANGE[1]}条）"
            )

        # 检查当事人数量
        party_count = len(annotation.parties)
        if party_count < cls.PARTY_COUNT_RANGE[0]:
            issues.append(
                f"当事人数量过少（{party_count}个，"
                f"要求至少{cls.PARTY_COUNT_RANGE[0]}个）"
            )

        if party_count > cls.PARTY_COUNT_RANGE[1]:
            issues.append(
                f"当事人数量过多（{party_count}个，"
                f"要求最多{cls.PARTY_COUNT_RANGE[1]}个）"
            )

        # 检查缺失条款数量
        if len(annotation.missing_clauses) > cls.MAX_MISSING_CLAUSES:
            issues.append(
                f"缺失条款数量过多（{len(annotation.missing_clauses)}个，"
                f"要求最多{cls.MAX_MISSING_CLAUSES}个）"
            )

        # 检查检索主题数量
        topic_count = len(annotation.legal_search_topics)
        if topic_count < cls.LEGAL_TOPIC_RANGE[0]:
            issues.append(
                f"检索主题过少（{topic_count}个，"
                f"要求至少{cls.LEGAL_TOPIC_RANGE[0]}个）"
            )

        if topic_count > cls.LEGAL_TOPIC_RANGE[1]:
            issues.append(
                f"检索主题过多（{topic_count}个，"
                f"要求最多{cls.LEGAL_TOPIC_RANGE[1]}个）"
            )

        # 检查每个条款的质量
        for i, clause in enumerate(annotation.clauses):
            clause_issues = cls.validate_clause_annotation(clause)
            for issue in clause_issues:
                issues.append(f"条款{i+1}: {issue}")

        return issues
