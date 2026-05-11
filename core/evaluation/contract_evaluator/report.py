"""合同审核评估报告生成模块。

生成格式化的评估报告，支持：
1. 单用例评估报告
2. 批量评估汇总报告
3. 多维度对比报告
4. 可视化数据导出

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from core.evaluation.contract_evaluator.metrics import (
    ContractEvaluationResult,
)

logger = logging.getLogger(__name__)


@dataclass
class ContractEvaluationReport:
    """合同审核评估报告。"""

    # 报告基本信息
    report_id: str
    report_title: str
    report_type: str  # single, batch, comparison
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # 评估配置
    judge_model: str = ""
    judge_config: dict[str, Any] = field(default_factory=dict)

    # 单用例评估结果
    single_result: ContractEvaluationResult | None = None

    # 批量评估结果
    batch_results: list[ContractEvaluationResult] = field(default_factory=list)
    total_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0

    # 汇总统计
    summary_statistics: dict[str, Any] = field(default_factory=dict)
    dimension_scores: dict[str, float] = field(default_factory=dict)
    performance_by_contract_type: dict[str, Any] = field(default_factory=dict)
    performance_by_difficulty: dict[str, Any] = field(default_factory=dict)

    # 问题分析
    common_issues: list[dict[str, Any]] = field(default_factory=list)
    improvement_suggestions: list[str] = field(default_factory=list)

    # 详细结果
    detailed_results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "report_id": self.report_id,
            "report_title": self.report_title,
            "report_type": self.report_type,
            "generated_at": self.generated_at,
            "judge_model": self.judge_model,
            "judge_config": self.judge_config,
            "single_result": self.single_result.to_dict() if self.single_result else None,
            "batch_results": [r.to_dict() for r in self.batch_results],
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "summary_statistics": self.summary_statistics,
            "dimension_scores": self.dimension_scores,
            "performance_by_contract_type": self.performance_by_contract_type,
            "performance_by_difficulty": self.performance_by_difficulty,
            "common_issues": self.common_issues,
            "improvement_suggestions": self.improvement_suggestions,
            "detailed_results": self.detailed_results,
        }

    def to_json_string(self, indent: int = 2) -> str:
        """转换为 JSON 字符串。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_markdown(self) -> str:
        """转换为 Markdown 格式。"""
        lines = [
            f"# {self.report_title}",
            "",
            f"**报告ID**: {self.report_id}",
            f"**生成时间**: {self.generated_at}",
            f"**评估模型**: {self.judge_model}",
            "",
            "---",
            "",
            "## 评估摘要",
            "",
        ]

        # 汇总统计
        if self.summary_statistics:
            lines.extend([
                f"| 指标 | 值 |",
                f"|------|----|",
                f"| 总用例数 | {self.summary_statistics.get('total_cases', 0)} |",
                f"| 通过率 | {self.summary_statistics.get('pass_rate', 0) * 100:.1f}% |",
                f"| 平均分 | {self.summary_statistics.get('avg_overall', 0):.2f} |",
                f"| 最低分 | {self.summary_statistics.get('min_score', 0):.2f} |",
                f"| 最高分 | {self.summary_statistics.get('max_score', 0):.2f} |",
                "",
            ])

        # 维度得分
        if self.dimension_scores:
            lines.extend([
                "## 各维度得分",
                "",
                f"| 维度 | 得分 |",
                f"|------|------|",
            ])
            for dim, score in self.dimension_scores.items():
                lines.append(f"| {dim} | {score:.2f} |")
            lines.append("")

        # 按合同类型分析
        if self.performance_by_contract_type:
            lines.extend([
                "## 按合同类型分析",
                "",
                f"| 合同类型 | 用例数 | 平均分 | 通过率 |",
                f"|----------|--------|--------|--------|",
            ])
            for ct, data in self.performance_by_contract_type.items():
                lines.append(
                    f"| {ct} | {data.get('count', 0)} | "
                    f"{data.get('avg_score', 0):.2f} | "
                    f"{data.get('pass_rate', 0) * 100:.1f}% |"
                )
            lines.append("")

        # 常见问题
        if self.common_issues:
            lines.extend([
                "## 常见问题",
                "",
            ])
            for i, issue in enumerate(self.common_issues, 1):
                lines.append(f"### {i}. {issue.get('title', '问题')}")
                lines.append(f"- **发生次数**: {issue.get('count', 0)}")
                lines.append(f"- **影响**: {issue.get('impact', '未知')}")
                lines.append(f"- **建议**: {issue.get('suggestion', '')}")
                lines.append("")
            lines.append("")

        # 改进建议
        if self.improvement_suggestions:
            lines.extend([
                "## 改进建议",
                "",
            ])
            for i, suggestion in enumerate(self.improvement_suggestions, 1):
                lines.append(f"{i}. {suggestion}")
            lines.append("")

        return "\n".join(lines)

    def to_csv(self) -> str:
        """导出为 CSV 格式。"""
        import csv
        from io import StringIO

        output = StringIO()
        writer = csv.writer(output)

        # 表头
        writer.writerow([
            "case_id", "contract_name", "contract_type", "overall_score",
            "classification_accuracy", "clause_extraction_f1",
            "risk_identification_f1", "report_quality",
            "workflow_success", "passed"
        ])

        # 数据行
        for result in self.batch_results:
            writer.writerow([
                result.contract_id,
                result.contract_name,
                result.contract_type,
                f"{result.overall_score:.2f}",
                f"{result.metrics.contract_classification_accuracy:.2f}",
                f"{result.metrics.clause_extraction_f1:.2f}",
                f"{result.metrics.risk_identification_f1:.2f}",
                f"{result.metrics.report_quality_score:.2f}",
                "Yes" if result.workflow_result and result.workflow_result.success else "No",
                "Yes" if result.overall_score >= 70 else "No",
            ])

        return output.getvalue()


class ReportGenerator:
    """评估报告生成器。"""

    def __init__(self) -> None:
        """初始化报告生成器。"""
        logger.info("ReportGenerator 初始化完成")

    def generate_single_report(
        self,
        evaluation_result: ContractEvaluationResult,
        judge_model: str,
        judge_config: dict[str, Any],
    ) -> ContractEvaluationReport:
        """生成单用例评估报告。

        Args:
            evaluation_result: 评估结果
            judge_model: 评估模型
            judge_config: 评估配置

        Returns:
            评估报告
        """
        import uuid

        report = ContractEvaluationReport(
            report_id=f"report_{uuid.uuid4().hex[:8]}",
            report_title=f"合同审核评估报告 - {evaluation_result.contract_name}",
            report_type="single",
            judge_model=judge_model,
            judge_config=judge_config,
            single_result=evaluation_result,
            total_cases=1,
            passed_cases=1 if evaluation_result.overall_score >= 70 else 0,
            failed_cases=0 if evaluation_result.overall_score >= 70 else 1,
            dimension_scores={
                "合同分类": evaluation_result.metrics.contract_classification_accuracy * 100,
                "条款抽取": evaluation_result.metrics.clause_extraction_f1 * 100,
                "风险识别": evaluation_result.metrics.risk_identification_f1 * 100,
                "报告质量": evaluation_result.metrics.report_quality_score * 100,
                "工作流": evaluation_result.metrics.workflow_success_rate * 100,
            },
        )

        # 添加详细结果
        report.detailed_results = [evaluation_result.to_dict()]

        # 分析问题
        if evaluation_result.errors:
            report.common_issues.append({
                "title": "执行错误",
                "count": len(evaluation_result.errors),
                "impact": "可能导致评估不完整",
                "suggestion": "检查 Agent 执行日志",
            })

        # 生成改进建议
        report.improvement_suggestions = self._generate_suggestions(evaluation_result)

        return report

    def generate_batch_report(
        self,
        evaluation_results: list[ContractEvaluationResult],
        judge_model: str,
        judge_config: dict[str, Any],
        test_suite_info: dict[str, Any] | None = None,
    ) -> ContractEvaluationReport:
        """生成批量评估报告。

        Args:
            evaluation_results: 评估结果列表
            judge_model: 评估模型
            judge_config: 评估配置
            test_suite_info: 测试套件信息

        Returns:
            评估报告
        """
        import uuid

        total = len(evaluation_results)
        passed = sum(1 for r in evaluation_results if r.overall_score >= 70)

        # 计算汇总统计
        overall_scores = [r.overall_score for r in evaluation_results]
        avg_overall = sum(overall_scores) / total if total > 0 else 0

        # 计算各维度平均分
        dimension_sums = {
            "合同分类": 0.0,
            "条款抽取": 0.0,
            "风险识别": 0.0,
            "报告质量": 0.0,
            "工作流": 0.0,
        }
        for r in evaluation_results:
            dimension_sums["合同分类"] += r.metrics.contract_classification_accuracy
            dimension_sums["条款抽取"] += r.metrics.clause_extraction_f1
            dimension_sums["风险识别"] += r.metrics.risk_identification_f1
            dimension_sums["报告质量"] += r.metrics.report_quality_score
            dimension_sums["工作流"] += r.metrics.workflow_success_rate

        dimension_scores = {k: (v / total * 100) for k, v in dimension_sums.items()}

        # 按合同类型分析
        performance_by_type = {}
        type_scores: dict[str, list[float]] = {}
        for r in evaluation_results:
            ct = r.contract_type
            type_scores.setdefault(ct, []).append(r.overall_score)

        for ct, scores in type_scores.items():
            performance_by_type[ct] = {
                "count": len(scores),
                "avg_score": sum(scores) / len(scores),
                "pass_rate": sum(1 for s in scores if s >= 70) / len(scores),
            }

        # 识别常见问题
        common_issues = self._identify_common_issues(evaluation_results)

        # 生成改进建议
        improvement_suggestions = self._generate_batch_suggestions(evaluation_results)

        report = ContractEvaluationReport(
            report_id=f"batch_report_{uuid.uuid4().hex[:8]}",
            report_title="合同审核批量评估报告",
            report_type="batch",
            judge_model=judge_model,
            judge_config=judge_config,
            batch_results=evaluation_results,
            total_cases=total,
            passed_cases=passed,
            failed_cases=total - passed,
            summary_statistics={
                "total_cases": total,
                "pass_rate": passed / total if total > 0 else 0,
                "avg_overall": avg_overall,
                "min_score": min(overall_scores) if overall_scores else 0,
                "max_score": max(overall_scores) if overall_scores else 0,
            },
            dimension_scores=dimension_scores,
            performance_by_contract_type=performance_by_type,
            common_issues=common_issues,
            improvement_suggestions=improvement_suggestions,
            detailed_results=[r.to_dict() for r in evaluation_results],
        )

        return report

    def _identify_common_issues(
        self,
        evaluation_results: list[ContractEvaluationResult],
    ) -> list[dict[str, Any]]:
        """识别常见问题。"""
        issues = []

        # 统计各维度低分情况
        low_clause_extraction = sum(
            1 for r in evaluation_results
            if r.metrics.clause_extraction_f1 < 0.6
        )
        if low_clause_extraction > len(evaluation_results) * 0.2:
            issues.append({
                "title": "条款抽取质量偏低",
                "count": low_clause_extraction,
                "impact": f"发生在 {low_clause_extraction}/{len(evaluation_results)} 个用例中",
                "suggestion": "考虑优化条款抽取 Prompt 或使用更强大的模型",
            })

        low_risk_id = sum(
            1 for r in evaluation_results
            if r.metrics.risk_identification_f1 < 0.5
        )
        if low_risk_id > len(evaluation_results) * 0.2:
            issues.append({
                "title": "风险识别能力不足",
                "count": low_risk_id,
                "impact": f"发生在 {low_risk_id}/{len(evaluation_results)} 个用例中",
                "suggestion": "考虑添加风险识别专项微调数据",
            })

        low_report = sum(
            1 for r in evaluation_results
            if r.metrics.report_quality_score < 0.6
        )
        if low_report > len(evaluation_results) * 0.2:
            issues.append({
                "title": "报告生成质量不稳定",
                "count": low_report,
                "impact": f"发生在 {low_report}/{len(evaluation_results)} 个用例中",
                "suggestion": "优化报告生成 Prompt 或增加标准报告数据",
            })

        workflow_failures = sum(
            1 for r in evaluation_results
            if r.workflow_result and not r.workflow_result.success
        )
        if workflow_failures > 0:
            issues.append({
                "title": "工作流执行失败",
                "count": workflow_failures,
                "impact": f"发生在 {workflow_failures}/{len(evaluation_results)} 个用例中",
                "suggestion": "检查工具执行日志，修复执行路径问题",
            })

        return issues

    def _generate_suggestions(
        self,
        result: ContractEvaluationResult,
    ) -> list[str]:
        """生成单用例改进建议。"""
        suggestions = []

        if result.metrics.contract_classification_accuracy < 0.8:
            suggestions.append("优化合同类型分类 Prompt，明确各类合同的特征")

        if result.metrics.clause_extraction_f1 < 0.7:
            suggestions.append("改进条款抽取策略，提高召回率和精确率")

        if result.metrics.risk_identification_f1 < 0.6:
            suggestions.append("增强风险识别能力，特别是中低风险项的识别")

        if result.metrics.report_quality_score < 0.7:
            suggestions.append("优化报告生成逻辑，提高内容完整性和准确性")

        if result.workflow_result and not result.workflow_result.success:
            suggestions.append("修复工作流执行问题，确保所有必要工具正确调用")

        if not suggestions:
            suggestions.append("当前表现良好，可继续监控生产环境表现")

        return suggestions

    def _generate_batch_suggestions(
        self,
        results: list[ContractEvaluationResult],
    ) -> list[str]:
        """生成批量评估改进建议。"""
        suggestions = []

        # 分析整体表现
        avg_scores = {
            "分类": sum(r.metrics.contract_classification_accuracy for r in results) / len(results),
            "抽取": sum(r.metrics.clause_extraction_f1 for r in results) / len(results),
            "风险": sum(r.metrics.risk_identification_f1 for r in results) / len(results),
            "报告": sum(r.metrics.report_quality_score for r in results) / len(results),
        }

        weakest = min(avg_scores.items(), key=lambda x: x[1])
        suggestions.append(f"重点优化 {weakest[0]} 能力，当前得分 {weakest[1]:.2f}")

        # 建议微调
        if weakest[1] < 0.7:
            suggestions.append(
                f"建议针对 {weakest[0]} 任务进行 LoRA 微调，使用领域专属数据"
            )

        # 建议优化 Prompt
        suggestions.append("考虑引入 Few-shot Prompting 提高特定任务表现")

        # 建议增加评估数据
        suggestions.append("持续扩充评估数据集，特别是边界情况和复杂合同")

        return suggestions

    def save_report(
        self,
        report: ContractEvaluationReport,
        output_path: str | Path,
        format: str = "json",
    ) -> None:
        """保存报告到文件。

        Args:
            report: 评估报告
            output_path: 输出路径
            format: 输出格式（json, markdown, csv）
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if format == "json":
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report.to_json_string())
        elif format == "markdown":
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report.to_markdown())
        elif format == "csv":
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report.to_csv())

        logger.info(f"报告已保存: {output_path}")
