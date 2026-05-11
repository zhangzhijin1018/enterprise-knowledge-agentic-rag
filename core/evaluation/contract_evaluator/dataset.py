"""评估数据集管理模块。

定义合同审核评估所需的数据结构：
1. 测试用例（TestCase）
2. 测试套件（TestSuite）
3. 标准答案（GroundTruth）
4. 测试数据生成器

数据集设计原则：
- 覆盖多种合同类型和场景
- 包含正常和边界情况
- 支持自动化数据增强
- 支持人工标注和自动生成混合

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ContractType(str, Enum):
    """合同类型枚举。"""

    PROCUREMENT = "procurement"  # 采购合同
    SERVICE = "service"  # 服务合同
    CONSTRUCTION = "construction"  # 建设工程合同
    LEASE = "lease"  # 租赁合同
    LABOR = "labor"  # 劳动合同
    SALES = "sales"  # 销售合同
    LICENSE = "license"  # 许可合同
    PARTNERSHIP = "partnership"  # 合作协议
    LOAN = "loan"  # 借款合同
    CONSULTING = "consulting"  # 咨询合同


class RiskCategory(str, Enum):
    """风险类别枚举。"""

    TERMINATION = "termination"  # 终止/退出风险
    PAYMENT = "payment"  # 付款/财务风险
    LIABILITY = "liability"  # 责任/赔偿风险
    IP = "ip"  # 知识产权风险
    CONFIDENTIALITY = "confidentiality"  # 保密风险
    GOVERNING_LAW = "governing_law"  # 适用法律/争议解决风险
    DELIVERY = "delivery"  # 交付风险
    QUALITY = "quality"  # 质量风险
    FORCE_MAJEURE = "force_majeure"  # 不可抗力风险
    ASSIGNMENT = "assignment"  # 转让风险


class RiskLevel(str, Enum):
    """风险等级枚举。"""

    HIGH = "high"  # 高风险
    MEDIUM = "medium"  # 中风险
    LOW = "low"  # 低风险
    NONE = "none"  # 无风险


class DataSource(str, Enum):
    """数据来源枚举。"""

    MANUAL_ANNOTATION = "manual"  # 人工标注
    SYNTHETIC = "synthetic"  # 合成数据
    HISTORICAL = "historical"  # 历史数据
    AUGMENTED = "augmented"  # 增强数据


@dataclass
class ContractTestCase:
    """合同审核测试用例。

    包含一个测试用例的所有信息：
    1. 合同内容
    2. 标准答案（ground truth）
    3. 测试元数据
    """

    # 唯一标识
    case_id: str

    # 合同信息
    contract_name: str
    contract_type: str
    contract_text: str

    # 标准答案（放在带默认值的字段之前）
    ground_truth: "ContractGroundTruth"

    # 可选字段（带默认值）
    contract_summary: str = ""
    difficulty: str = "medium"  # easy, medium, hard
    category: str = "general"  # 测试类别
    data_source: str = DataSource.MANUAL_ANNOTATION.value
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    expected_tools: list[str] = field(default_factory=list)  # 预期调用的工具
    expected_human_review: bool = False  # 预期是否触发 Human Review
    expected_iterations: int = 5  # 预期迭代次数
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "case_id": self.case_id,
            "contract_name": self.contract_name,
            "contract_type": self.contract_type,
            "contract_text": self.contract_text,
            "contract_summary": self.contract_summary,
            "ground_truth": self.ground_truth.to_dict(),
            "difficulty": self.difficulty,
            "category": self.category,
            "data_source": self.data_source,
            "created_at": self.created_at,
            "expected_tools": self.expected_tools,
            "expected_human_review": self.expected_human_review,
            "expected_iterations": self.expected_iterations,
            "tags": self.tags,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContractTestCase":
        """从字典创建。"""
        gt_data = data.get("ground_truth", {})
        ground_truth = ContractGroundTruth.from_dict(gt_data)

        return cls(
            case_id=data["case_id"],
            contract_name=data["contract_name"],
            contract_type=data["contract_type"],
            contract_text=data["contract_text"],
            contract_summary=data.get("contract_summary", ""),
            ground_truth=ground_truth,
            difficulty=data.get("difficulty", "medium"),
            category=data.get("category", "general"),
            data_source=data.get("data_source", DataSource.MANUAL_ANNOTATION.value),
            created_at=data.get("created_at", datetime.now().isoformat()),
            expected_tools=data.get("expected_tools", []),
            expected_human_review=data.get("expected_human_review", False),
            expected_iterations=data.get("expected_iterations", 5),
            tags=data.get("tags", []),
            notes=data.get("notes", ""),
        )


@dataclass
class ContractGroundTruth:
    """合同审核标准答案。

    包含合同审核任务的完整标准答案。
    """

    # 合同分类标准答案
    correct_contract_type: str

    # 条款标准答案
    clauses: list["ClauseGroundTruth"] = field(default_factory=list)

    # 风险标准答案
    risks: list["RiskGroundTruth"] = field(default_factory=list)

    # 缺失条款标准答案
    missing_clauses: list[str] = field(default_factory=list)

    # 报告标准答案
    expected_report_summary: str = ""
    expected_conclusion: str = ""
    expected_suggestions: list[str] = field(default_factory=list)

    # Human Review 预期
    expected_human_review: bool = False
    high_risk_items: list[str] = field(default_factory=list)

    # 法规引用标准答案
    expected_regulations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "correct_contract_type": self.correct_contract_type,
            "clauses": [c.to_dict() for c in self.clauses],
            "risks": [r.to_dict() for r in self.risks],
            "missing_clauses": self.missing_clauses,
            "expected_report_summary": self.expected_report_summary,
            "expected_conclusion": self.expected_conclusion,
            "expected_suggestions": self.expected_suggestions,
            "expected_human_review": self.expected_human_review,
            "high_risk_items": self.high_risk_items,
            "expected_regulations": self.expected_regulations,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContractGroundTruth":
        """从字典创建。"""
        clauses = [
            ClauseGroundTruth.from_dict(c)
            for c in data.get("clauses", [])
        ]
        risks = [
            RiskGroundTruth.from_dict(r)
            for r in data.get("risks", [])
        ]

        return cls(
            correct_contract_type=data["correct_contract_type"],
            clauses=clauses,
            risks=risks,
            missing_clauses=data.get("missing_clauses", []),
            expected_report_summary=data.get("expected_report_summary", ""),
            expected_conclusion=data.get("expected_conclusion", ""),
            expected_suggestions=data.get("expected_suggestions", []),
            expected_human_review=data.get("expected_human_review", False),
            high_risk_items=data.get("high_risk_items", []),
            expected_regulations=data.get("expected_regulations", []),
        )


@dataclass
class ClauseGroundTruth:
    """条款标准答案。"""

    clause_id: str
    clause_type: str
    clause_title: str
    clause_content: str
    start_position: int = 0
    end_position: int = 0

    # 标准风险指示器
    risk_indicators: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "clause_id": self.clause_id,
            "clause_type": self.clause_type,
            "clause_title": self.clause_title,
            "clause_content": self.clause_content,
            "start_position": self.start_position,
            "end_position": self.end_position,
            "risk_indicators": self.risk_indicators,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClauseGroundTruth":
        return cls(
            clause_id=data["clause_id"],
            clause_type=data["clause_type"],
            clause_title=data["clause_title"],
            clause_content=data["clause_content"],
            start_position=data.get("start_position", 0),
            end_position=data.get("end_position", 0),
            risk_indicators=data.get("risk_indicators", []),
        )


@dataclass
class RiskGroundTruth:
    """风险标准答案。"""

    risk_id: str
    risk_type: str  # RiskCategory
    risk_level: str  # RiskLevel
    related_clause_id: str
    risk_description: str
    suggestion: str = ""

    # 关联法规
    related_regulations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_id": self.risk_id,
            "risk_type": self.risk_type,
            "risk_level": self.risk_level,
            "related_clause_id": self.related_clause_id,
            "risk_description": self.risk_description,
            "suggestion": self.suggestion,
            "related_regulations": self.related_regulations,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RiskGroundTruth":
        return cls(
            risk_id=data["risk_id"],
            risk_type=data["risk_type"],
            risk_level=data["risk_level"],
            related_clause_id=data["related_clause_id"],
            risk_description=data["risk_description"],
            suggestion=data.get("suggestion", ""),
            related_regulations=data.get("related_regulations", []),
        )


@dataclass
class ContractTestSuite:
    """合同审核测试套件。

    包含一组相关的测试用例，用于全面评估合同审核 Agent。
    """

    # 套件标识
    suite_id: str
    suite_name: str
    suite_description: str

    # 测试用例
    test_cases: list[ContractTestCase] = field(default_factory=list)

    # 统计信息
    total_cases: int = 0
    by_difficulty: dict[str, int] = field(default_factory=dict)
    by_contract_type: dict[str, int] = field(default_factory=dict)
    by_category: dict[str, int] = field(default_factory=dict)

    # 元数据
    version: str = "1.0.0"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def __post_init__(self) -> None:
        """初始化后处理，计算统计信息。"""
        self.total_cases = len(self.test_cases)

        # 按难度统计
        self.by_difficulty = {}
        for case in self.test_cases:
            self.by_difficulty[case.difficulty] = self.by_difficulty.get(case.difficulty, 0) + 1

        # 按合同类型统计
        self.by_contract_type = {}
        for case in self.test_cases:
            self.by_contract_type[case.contract_type] = self.by_contract_type.get(case.contract_type, 0) + 1

        # 按类别统计
        self.by_category = {}
        for case in self.test_cases:
            self.by_category[case.category] = self.by_category.get(case.category, 0) + 1

    def filter_cases(
        self,
        contract_type: str | None = None,
        difficulty: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
    ) -> list[ContractTestCase]:
        """过滤测试用例。

        Args:
            contract_type: 合同类型过滤
            difficulty: 难度过滤
            category: 类别过滤
            tags: 标签过滤

        Returns:
            过滤后的测试用例列表
        """
        filtered = self.test_cases

        if contract_type:
            filtered = [c for c in filtered if c.contract_type == contract_type]

        if difficulty:
            filtered = [c for c in filtered if c.difficulty == difficulty]

        if category:
            filtered = [c for c in filtered if c.category == category]

        if tags:
            filtered = [c for c in filtered if any(tag in c.tags for tag in tags)]

        return filtered

    def get_sample(
        self,
        n: int,
        stratify_by: str = "difficulty",
    ) -> list[ContractTestCase]:
        """获取分层采样测试用例。

        Args:
            n: 采样数量
            stratify_by: 分层字段（difficulty/contract_type/category）

        Returns:
            采样的测试用例列表
        """
        import random

        if stratify_by == "difficulty":
            groups = {}
            for case in self.test_cases:
                groups.setdefault(case.difficulty, []).append(case)

            samples_per_group = n // len(groups)
            samples = []
            for group_cases in groups.values():
                samples.extend(random.sample(
                    group_cases,
                    min(samples_per_group, len(group_cases))
                ))

            # 如果不够，随机补充
            while len(samples) < n and samples:
                remaining = [c for c in self.test_cases if c not in samples]
                if remaining:
                    samples.append(random.choice(remaining))
                else:
                    break

            return samples[:n]

        else:
            return random.sample(self.test_cases, min(n, len(self.test_cases)))

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "suite_id": self.suite_id,
            "suite_name": self.suite_name,
            "suite_description": self.suite_description,
            "test_cases": [case.to_dict() for case in self.test_cases],
            "total_cases": self.total_cases,
            "by_difficulty": self.by_difficulty,
            "by_contract_type": self.by_contract_type,
            "by_category": self.by_category,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContractTestSuite":
        """从字典创建。"""
        test_cases = [
            ContractTestCase.from_dict(c)
            for c in data.get("test_cases", [])
        ]

        return cls(
            suite_id=data["suite_id"],
            suite_name=data["suite_name"],
            suite_description=data["suite_description"],
            test_cases=test_cases,
            version=data.get("version", "1.0.0"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
        )

    @classmethod
    def from_json_file(cls, file_path: str | Path) -> "ContractTestSuite":
        """从 JSON 文件加载测试套件。"""
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def to_json_file(self, file_path: str | Path) -> None:
        """保存测试套件到 JSON 文件。"""
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)


class ContractTestDataGenerator:
    """测试数据生成器。

    用于生成合成测试数据，支持：
    1. 模板化合同生成
    2. 数据增强
    3. 边界情况生成
    """

    def __init__(self) -> None:
        """初始化生成器。"""
        self._templates = self._load_templates()

    def _load_templates(self) -> dict[str, Any]:
        """加载合同模板。"""
        # 简化的模板定义，实际项目中应从文件或数据库加载
        return {
            "procurement": {
                "structure": [
                    {"type": "header", "description": "合同双方信息"},
                    {"type": "clause", "clause_type": "contract_subject", "description": "合同标的"},
                    {"type": "clause", "clause_type": "price", "description": "合同价款"},
                    {"type": "clause", "clause_type": "payment", "description": "付款方式"},
                    {"type": "clause", "clause_type": "delivery", "description": "交付条款"},
                    {"type": "clause", "clause_type": "quality", "description": "质量标准"},
                    {"type": "clause", "clause_type": "warranty", "description": "质保条款"},
                    {"type": "clause", "clause_type": "liability", "description": "违约责任"},
                    {"type": "clause", "clause_type": "termination", "description": "终止条款"},
                ],
                "risk_patterns": [
                    {
                        "pattern": "无条件解除",
                        "risk_level": "high",
                        "risk_type": "termination",
                    },
                    {
                        "pattern": "30日内付款",
                        "risk_level": "medium",
                        "risk_type": "payment",
                    },
                ],
            },
            "service": {
                "structure": [
                    {"type": "header", "description": "服务双方信息"},
                    {"type": "clause", "clause_type": "service_scope", "description": "服务范围"},
                    {"type": "clause", "clause_type": "service_fee", "description": "服务费用"},
                    {"type": "clause", "clause_type": "performance", "description": "服务标准"},
                    {"type": "clause", "clause_type": "confidentiality", "description": "保密条款"},
                    {"type": "clause", "clause_type": "ip", "description": "知识产权"},
                    {"type": "clause", "clause_type": "termination", "description": "终止条款"},
                ],
            },
        }

    def generate_synthetic_case(
        self,
        contract_type: str,
        include_risks: bool = True,
        difficulty: str = "medium",
    ) -> ContractTestCase:
        """生成合成测试用例。

        Args:
            contract_type: 合同类型
            include_risks: 是否包含风险
            difficulty: 难度级别

        Returns:
            生成的测试用例
        """
        import uuid
        from datetime import datetime

        case_id = f"synthetic_{uuid.uuid4().hex[:8]}"

        # 生成合同文本（简化版，实际应使用模板引擎）
        contract_text = self._generate_contract_text(contract_type, difficulty)
        ground_truth = self._generate_ground_truth(contract_text, contract_type, include_risks)

        return ContractTestCase(
            case_id=case_id,
            contract_name=f"合成{contract_type}测试合同",
            contract_type=contract_type,
            contract_text=contract_text,
            ground_truth=ground_truth,
            difficulty=difficulty,
            data_source=DataSource.SYNTHETIC.value,
            created_at=datetime.now().isoformat(),
        )

    def _generate_contract_text(self, contract_type: str, difficulty: str) -> str:
        """生成合同文本。"""
        # 简化实现，实际应使用更复杂的模板和生成逻辑
        templates = {
            "procurement": """采购合同

甲方：新疆能源集团有限公司
乙方：设备供应商有限公司

第一条 合同标的
甲方向乙方采购光伏发电设备一批，具体型号和数量见附件。

第二条 合同价款
合同总金额为人民币壹仟万元整（含税）。

第三条 付款方式
甲方应在设备验收合格后30日内支付全部款项。

第四条 交付条款
乙方应在合同签订后60日内交付全部设备。

第五条 质量标准
设备质量应符合国家相关标准和甲方技术要求。

第六条 违约责任
任何一方违约，应向对方支付合同总金额20%的违约金。

第七条 争议解决
因本合同引起的争议，双方应协商解决；协商不成的，提交合同签订地人民法院管辖。
""",
            "service": """服务合同

甲方：新疆能源集团有限公司
乙方：咨询服务有限公司

第一条 服务内容
乙方为甲方提供企业管理咨询服务，包括战略规划、组织优化等。

第二条 服务费用
服务费用为人民币伍拾万元整，分三期支付。

第三条 服务标准
乙方应按照甲方要求按时完成咨询服务，提交书面报告。

第四条 知识产权
咨询服务过程中产生的所有知识产权归甲方所有。

第五条 保密条款
双方应对合作过程中知悉的商业秘密保密，保密期限为合同终止后两年。

第六条 合同解除
甲方有权在提前30日通知乙方后解除本合同。
""",
        }

        return templates.get(contract_type, templates["procurement"])

    def _generate_ground_truth(
        self,
        contract_text: str,
        contract_type: str,
        include_risks: bool,
    ) -> ContractGroundTruth:
        """生成标准答案。"""
        clauses = []
        risks = []

        if contract_type == "procurement":
            clauses = [
                ClauseGroundTruth(
                    clause_id="第1条",
                    clause_type="contract_subject",
                    clause_title="合同标的",
                    clause_content="甲方向乙方采购光伏发电设备一批",
                ),
                ClauseGroundTruth(
                    clause_id="第2条",
                    clause_type="price",
                    clause_title="合同价款",
                    clause_content="合同总金额为人民币壹仟万元整",
                ),
                ClauseGroundTruth(
                    clause_id="第3条",
                    clause_type="payment",
                    clause_title="付款方式",
                    clause_content="甲方应在设备验收合格后30日内支付全部款项",
                    risk_indicators=["[中风险] 付款条件较为严格"],
                ),
            ]

            if include_risks:
                risks = [
                    RiskGroundTruth(
                        risk_id="R001",
                        risk_type=RiskCategory.PAYMENT.value,
                        risk_level=RiskLevel.MEDIUM.value,
                        related_clause_id="第3条",
                        risk_description="付款条件与设备验收挂钩，可能导致付款延迟",
                        suggestion="建议增加预付款条款或明确验收标准",
                    ),
                ]

        return ContractGroundTruth(
            correct_contract_type=contract_type,
            clauses=clauses,
            risks=risks,
            expected_human_review=include_risks and len(risks) > 0,
        )
