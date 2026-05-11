"""合同风险识别器。

识别合同中的风险条款和风险点。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.contracts.models import (
    ContractClause,
    ContractRisk,
    RiskCategory,
    RiskIndicatorKeywords,
    RiskLevel,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class RiskIdentifier:
    """合同风险识别器。

    职责：
    - 分析条款中的风险指标
    - 识别风险类型和等级
    - 生成风险描述和修改建议

    设计原因：
    - 企业合同审查必须识别潜在风险
    - 不同风险等级需要不同处理方式
    - 高风险条款需要法务复核
    """

    def __init__(self) -> None:
        """初始化风险识别器。"""
        pass

    def identify_risks(
        self,
        clauses: list[ContractClause],
        contract_type: str | None = None,
    ) -> tuple[list[ContractRisk], list[str]]:
        """识别合同风险。

        Args:
            clauses: 条款列表
            contract_type: 合同类型

        Returns:
            (风险列表, 重点关注项列表)
        """

        logger.info(f"开始识别风险，共 {len(clauses)} 个条款")

        risks = []
        key_concerns = []

        for clause in clauses:
            clause_risks = self._identify_clause_risks(clause)

            for risk in clause_risks:
                risks.append(risk)

                # 高风险条款加入重点关注
                if risk.risk_type == RiskLevel.HIGH or risk.risk_type == RiskLevel.CRITICAL:
                    key_concerns.append(
                        f"{clause.clause_id} {clause.clause_title}：{risk.risk_description[:50]}..."
                    )

        # 排序：先高风险，后中风险，低风险
        risk_level_order = {
            RiskLevel.CRITICAL: 0,
            RiskLevel.HIGH: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.LOW: 3,
        }
        risks.sort(key=lambda x: (risk_level_order.get(x.risk_type, 99), x.risk_id))

        logger.info(f"识别出 {len(risks)} 个风险点，{len(key_concerns)} 个重点关注项")

        return risks, key_concerns

    def _identify_clause_risks(
        self,
        clause: ContractClause,
    ) -> list[ContractRisk]:
        """识别单个条款的风险。

        Args:
            clause: 合同条款

        Returns:
            风险列表
        """

        risks = []
        clause_content = clause.clause_content
        clause_id = clause.clause_id

        # 检查条款中的风险指标
        for indicator in clause.risk_indicators:
            risk_type, risk_category = self._parse_risk_indicator(indicator)

            if risk_type:
                risk = ContractRisk(
                    risk_id=f"R{len(risks) + 1:03d}",
                    risk_type=risk_type,
                    risk_category=risk_category,
                    risk_description=self._build_risk_description(
                        clause_content, indicator
                    ),
                    related_clause=clause_id,
                    suggestion=self._build_suggestion(risk_type, indicator),
                    legal_basis=self._find_legal_basis(indicator),
                    is_blocking=risk_type in (RiskLevel.HIGH, RiskLevel.CRITICAL),
                )
                risks.append(risk)

        # 检查缺失条款
        missing = self._check_missing_clauses(clause)
        for miss in missing:
            risks.append(miss)

        return risks

    def _parse_risk_indicator(
        self,
        indicator: str,
    ) -> tuple[RiskLevel | None, RiskCategory]:
        """解析风险指标。

        Args:
            indicator: 风险指标字符串

        Returns:
            (风险等级, 风险类别)
        """

        if "[高风险]" in indicator:
            keyword = indicator.replace("[高风险] ", "")
            category = self._categorize_risk(keyword, RiskLevel.HIGH)
            return RiskLevel.HIGH, category

        if "[中风险]" in indicator:
            keyword = indicator.replace("[中风险] ", "")
            category = self._categorize_risk(keyword, RiskLevel.MEDIUM)
            return RiskLevel.MEDIUM, category

        if "[提示]" in indicator:
            keyword = indicator.replace("[提示] ", "")
            category = self._categorize_risk(keyword, RiskLevel.LOW)
            return RiskLevel.LOW, category

        return None, RiskCategory.UNEQUAL

    def _categorize_risk(self, keyword: str, level: RiskLevel) -> RiskCategory:
        """对风险进行分类。

        Args:
            keyword: 风险关键词
            level: 风险等级

        Returns:
            风险类别
        """

        # 霸王条款
        if any(k in keyword for k in ["无条件", "单方", "免除", "强制", "不得"]):
            return RiskCategory.TYRANNY

        # 模糊表述
        if any(k in keyword for k in ["模糊", "未明确", "无具体"]):
            return RiskCategory.AMBIGUOUS

        # 违规条款
        if any(k in keyword for k in ["违反", "违法", "不合规"]):
            return RiskCategory.VIOLATION

        # 默认
        return RiskCategory.UNEQUAL

    def _build_risk_description(
        self,
        clause_content: str,
        indicator: str,
    ) -> str:
        """构建风险描述。

        Args:
            clause_content: 条款内容
            indicator: 风险指标

        Returns:
            风险描述
        """

        desc = f"该条款存在风险：{indicator}"

        if len(clause_content) > 100:
            desc += f"。条款内容：{clause_content[:100]}..."
        else:
            desc += f"。条款内容：{clause_content}"

        return desc

    def _build_suggestion(
        self,
        risk_type: RiskLevel,
        indicator: str,
    ) -> str:
        """生成修改建议。

        Args:
            risk_type: 风险等级
            indicator: 风险指标

        Returns:
            修改建议
        """

        keyword = indicator.replace("[高风险] ", "").replace("[中风险] ", "").replace("[提示] ", "")

        if risk_type == RiskLevel.CRITICAL:
            return "建议删除该条款，该条款可能违反法律法规，必须修改或删除。"
        elif risk_type == RiskLevel.HIGH:
            return "建议删除或修改该条款，如必须保留请经法务部门审批。"
        elif risk_type == RiskLevel.MEDIUM:
            return "建议与对方协商修改，明确责任范围和违约金额。"
        else:
            return f"建议进一步明确'{keyword}'的表述，减少争议空间。"

    def _find_legal_basis(self, indicator: str) -> str | None:
        """查找相关法律依据。

        Args:
            indicator: 风险指标

        Returns:
            法律依据，如无则返回 None
        """

        legal_bases = {
            "违约金过高": "《民法典》第五百八十五条：约定的违约金过分高于造成的损失的，当事人可以请求人民法院或者仲裁机构予以适当减少",
            "无限责任": "《民法典》第三条：民事主体的人身权利、财产权利以及其他合法权益受法律保护",
            "单方解释权": "《民法典》第四百六十六条：当事人对合同条款的理解有争议的，应当依据诚实信用原则，确定争议条款的含义",
            "强制仲裁": "《仲裁法》第四条：当事人采用仲裁方式解决纠纷，应当双方自愿，达成仲裁协议",
            "不得诉讼": "《民事诉讼法》第八条：当事人有权在法律规定的范围内处分自己的民事权利和诉讼权利",
        }

        for key, basis in legal_bases.items():
            if key in indicator:
                return basis

        return None

    def _check_missing_clauses(
        self,
        clause: ContractClause,
    ) -> list[ContractRisk]:
        """检查缺失条款。

        Args:
            clause: 条款

        Returns:
            缺失条款的风险列表
        """

        # 这是一个简化的实现
        # 实际可以根据合同类型检查特定条款是否缺失
        return []

    def calculate_overall_risk_level(
        self,
        risks: list[ContractRisk],
    ) -> RiskLevel:
        """计算整体风险等级。

        Args:
            risks: 风险列表

        Returns:
            整体风险等级
        """

        if not risks:
            return RiskLevel.LOW

        # 统计各级风险数量
        level_counts = {
            RiskLevel.CRITICAL: 0,
            RiskLevel.HIGH: 0,
            RiskLevel.MEDIUM: 0,
            RiskLevel.LOW: 0,
        }

        for risk in risks:
            if risk.risk_type in level_counts:
                level_counts[risk.risk_type] += 1

        # 决策规则
        if level_counts[RiskLevel.CRITICAL] > 0:
            return RiskLevel.CRITICAL
        if level_counts[RiskLevel.HIGH] >= 2:
            return RiskLevel.HIGH
        if level_counts[RiskLevel.HIGH] >= 1:
            return RiskLevel.MEDIUM
        if level_counts[RiskLevel.MEDIUM] >= 3:
            return RiskLevel.MEDIUM
        if level_counts[RiskLevel.MEDIUM] >= 1:
            return RiskLevel.LOW

        return RiskLevel.LOW
