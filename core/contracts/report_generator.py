"""合同审查报告生成器。

生成结构化的合同审查报告。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from core.contracts.models import (
    ContractMetadata,
    ContractParty,
    ContractReviewReport,
    ContractRisk,
    ContractType,
    ReviewStatus,
    RiskLevel,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ReportGenerator:
    """合同审查报告生成器。

    职责：
    - 汇总条款抽取和风险识别的结果
    - 生成结构化的审查报告
    - 确定整体风险等级
    - 生成审查结论和建议

    设计原因：
    - 企业合同审查需要完整的报告输出
    - 报告需要包含所有关键信息
    - 报告需要可追溯、可审计
    """

    def __init__(self) -> None:
        """初始化报告生成器。"""
        pass

    def generate_report(
        self,
        report_id: str,
        contract_id: str,
        contract_name: str,
        contract_type: ContractType | str | None,
        clauses: list,
        parties: list[ContractParty],
        metadata: ContractMetadata,
        risks: list[ContractRisk],
        key_concerns: list[str],
        missing_clauses: list[str] | None = None,
        template_comparison: dict | None = None,
    ) -> ContractReviewReport:
        """生成合同审查报告。

        Args:
            report_id: 报告 ID
            contract_id: 合同 ID
            contract_name: 合同名称
            contract_type: 合同类型
            clauses: 抽取的条款列表
            parties: 当事人列表
            metadata: 合同元数据
            risks: 识别到的风险列表
            key_concerns: 重点关注项列表
            missing_clauses: 缺失条款列表
            template_comparison: 模板对比结果

        Returns:
            合同审查报告
        """

        logger.info(f"生成审查报告: {report_id}")

        # 确定合同类型
        if isinstance(contract_type, ContractType):
            contract_type_enum = contract_type
        else:
            contract_type_enum = ContractType(contract_type) if contract_type else ContractType.其他

        # 计算各级风险数量
        high_risk_count = sum(1 for r in risks if r.risk_type == RiskLevel.HIGH)
        medium_risk_count = sum(1 for r in risks if r.risk_type == RiskLevel.MEDIUM)
        low_risk_count = sum(1 for r in risks if r.risk_type == RiskLevel.LOW)

        # 确定整体风险等级
        overall_risk_level = self._calculate_overall_risk(risks)

        # 生成风险概要
        risk_summary = self._generate_risk_summary(
            overall_risk_level,
            high_risk_count,
            medium_risk_count,
            low_risk_count,
        )

        # 生成建议
        suggestions = self._generate_suggestions(risks, overall_risk_level)

        # 生成结论
        conclusion = self._generate_conclusion(overall_risk_level, high_risk_count)

        # 确定审查状态
        if overall_risk_level == RiskLevel.HIGH or overall_risk_level == RiskLevel.CRITICAL:
            status = ReviewStatus.PENDING  # 需要人工复核
        else:
            status = ReviewStatus.APPROVED  # 自动通过

        # 构建报告
        report = ContractReviewReport(
            report_id=report_id,
            contract_id=contract_id,
            contract_name=contract_name,
            contract_type=contract_type_enum,
            review_time=datetime.now(),
            parties=parties,
            metadata=metadata,
            overall_risk_level=overall_risk_level,
            risk_summary=risk_summary,
            high_risk_count=high_risk_count,
            medium_risk_count=medium_risk_count,
            low_risk_count=low_risk_count,
            risks=risks,
            key_concerns=key_concerns,
            clauses=clauses,
            missing_clauses=missing_clauses or [],
            template_comparison=template_comparison,
            suggestions=suggestions,
            conclusion=conclusion,
        )

        logger.info(
            f"报告生成完成: {report_id}, "
            f"风险等级: {overall_risk_level.value}, "
            f"风险数量: 高={high_risk_count}, 中={medium_risk_count}, 低={low_risk_count}"
        )

        return report

    def _calculate_overall_risk(self, risks: list[ContractRisk]) -> RiskLevel:
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

    def _generate_risk_summary(
        self,
        overall_risk: RiskLevel,
        high_count: int,
        medium_count: int,
        low_count: int,
    ) -> str:
        """生成风险概要。

        Args:
            overall_risk: 整体风险等级
            high_count: 高风险数量
            medium_count: 中风险数量
            low_count: 低风险数量

        Returns:
            风险概要文本
        """

        level_text = {
            RiskLevel.LOW: "低",
            RiskLevel.MEDIUM: "中",
            RiskLevel.HIGH: "高",
            RiskLevel.CRITICAL: "严重",
        }

        parts = [
            f"整体风险等级：{level_text.get(overall_risk, '未知')}风险",
            f"高风险 {high_count} 项",
            f"中风险 {medium_count} 项",
            f"低风险 {low_count} 项",
        ]

        if overall_risk == RiskLevel.CRITICAL:
            parts.append("⚠️ 该合同存在严重风险，建议法务部门重点审查")
        elif overall_risk == RiskLevel.HIGH:
            parts.append("⚠️ 该合同存在高风险条款，建议修改后审查")
        elif overall_risk == RiskLevel.MEDIUM:
            parts.append("⚡ 该合同存在中等风险，建议关注重点条款")
        else:
            parts.append("✓ 该合同整体风险较低")

        return "；".join(parts)

    def _generate_suggestions(
        self,
        risks: list[ContractRisk],
        overall_risk: RiskLevel,
    ) -> list[str]:
        """生成修改建议。

        Args:
            risks: 风险列表
            overall_risk: 整体风险等级

        Returns:
            建议列表
        """

        suggestions = []

        # 根据整体风险等级添加建议
        if overall_risk == RiskLevel.CRITICAL:
            suggestions.append("该合同存在严重风险，建议法务部门重点审查后再签约")
            suggestions.append("建议与对方协商修改高风险条款后再提交审查")
        elif overall_risk == RiskLevel.HIGH:
            suggestions.append("建议修改高风险条款后再提交审查")
            suggestions.append("如必须签约，请确保高风险条款已获得法务部门批准")

        # 从风险中提取建议
        for risk in risks[:5]:  # 最多添加 5 条
            if risk.suggestion and risk.suggestion not in suggestions:
                suggestions.append(f"{risk.related_clause}: {risk.suggestion}")

        # 默认建议
        if not suggestions:
            suggestions.append("合同整体无明显风险，建议按流程签约")

        return suggestions[:10]  # 最多 10 条建议

    def _generate_conclusion(
        self,
        overall_risk: RiskLevel,
        high_count: int,
    ) -> str:
        """生成审查结论。

        Args:
            overall_risk: 整体风险等级
            high_count: 高风险数量

        Returns:
            审查结论
        """

        if overall_risk == RiskLevel.CRITICAL:
            return (
                "该合同存在严重风险条款，可能违反法律法规或存在明显不公平约定。\n"
                "建议法务部门重点审查，并与对方协商修改相关条款后再签约。"
            )
        elif overall_risk == RiskLevel.HIGH:
            return (
                f"该合同存在 {high_count} 项高风险条款，需要关注和修改。\n"
                "建议修改高风险条款后重新提交审查。"
            )
        elif overall_risk == RiskLevel.MEDIUM:
            return (
                "该合同整体风险可控，但存在一些需要注意的条款。\n"
                "建议在签约前确认相关条款，或与法务部门确认。"
            )
        else:
            return (
                "该合同整体风险较低，符合一般签约标准。\n"
                "建议按流程办理签约手续。"
            )

    def format_report_text(self, report: ContractReviewReport) -> str:
        """格式化报告为文本。

        Args:
            report: 审查报告

        Returns:
            格式化的文本报告
        """

        lines = []

        # 标题
        lines.append("=" * 60)
        lines.append(f"合同审查报告")
        lines.append("=" * 60)
        lines.append("")

        # 基本信息
        lines.append(f"报告编号：{report.report_id}")
        lines.append(f"合同名称：{report.contract_name}")
        lines.append(f"合同类型：{report.contract_type.value}")
        lines.append(f"审查时间：{report.review_time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        # 当事人
        if report.parties:
            lines.append("当事人：")
            for party in report.parties:
                lines.append(f"  - {party.role}：{party.name}")
            lines.append("")

        # 风险概要
        lines.append("风险概要：")
        lines.append(f"  {report.risk_summary}")
        lines.append("")

        # 风险列表
        if report.risks:
            lines.append(f"风险详情（共 {len(report.risks)} 项）：")
            for risk in report.risks:
                lines.append(f"  [{risk.risk_id}] {risk.risk_type.value} - {risk.risk_category.value}")
                lines.append(f"      条款：{risk.related_clause}")
                lines.append(f"      描述：{risk.risk_description[:100]}...")
                lines.append(f"      建议：{risk.suggestion}")
                if risk.legal_basis:
                    lines.append(f"      依据：{risk.legal_basis[:50]}...")
                lines.append("")
        else:
            lines.append("风险详情：未发现风险")
            lines.append("")

        # 审查结论
        lines.append("审查结论：")
        lines.append(f"  {report.conclusion.replace(chr(10), '  ')}")
        lines.append("")

        # 建议
        if report.suggestions:
            lines.append("修改建议：")
            for i, suggestion in enumerate(report.suggestions, 1):
                lines.append(f"  {i}. {suggestion}")
            lines.append("")

        lines.append("=" * 60)

        return "\n".join(lines)
