"""合同审核 Agent 评估指标定义。

评估维度设计基于 2026 年最新研究：
1. 合同分类任务（Contract Classification）
2. 条款抽取任务（Clause Extraction）
3. 风险识别任务（Risk Identification）
4. 报告生成质量（Report Generation）
5. 整体工作流评估（End-to-End Workflow）

每个维度对应不同的评估指标：
- 精确率（Precision）
- 召回率（Recall）
- F1 分数
- 准确率（Accuracy）
- 语义相似度（Semantic Similarity）

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvaluationDimension(str, Enum):
    """评估维度枚举。

    定义合同审核 Agent 的主要评估维度，每个维度对应不同的业务任务。
    """

    # ===== 基础任务维度 =====
    CONTRACT_CLASSIFICATION = "contract_classification"  # 合同类型分类
    CLAUSE_EXTRACTION = "clause_extraction"  # 条款抽取
    CLAUSE_CLASSIFICATION = "clause_classification"  # 条款类型分类
    RISK_IDENTIFICATION = "risk_identification"  # 风险识别
    RISK_LEVEL_ASSESSMENT = "risk_level_assessment"  # 风险等级评估

    # ===== 高级任务维度 =====
    CLAUSE_COMPLETENESS = "clause_completeness"  # 条款完整性
    CLAUSE_QUALITY = "clause_quality"  # 条款质量
    LEGAL_COMPLIANCE = "legal_compliance"  # 法律合规性
    TEMPLATE_MATCHING = "template_matching"  # 模板匹配

    # ===== 生成质量维度 =====
    REPORT_QUALITY = "report_quality"  # 报告质量
    SUGGESTION_QUALITY = "suggestion_quality"  # 建议质量
    CITATION_ACCURACY = "citation_accuracy"  # 引用准确性

    # ===== 工作流维度 =====
    END_TO_END_WORKFLOW = "end_to_end_workflow"  # 端到端工作流
    HUMAN_REVIEW_TRIGGER = "human_review_trigger"  # Human Review 触发
    REFLECTION_QUALITY = "reflection_quality"  # 反思质量


class MetricType(str, Enum):
    """指标类型枚举。"""

    # 分类指标
    ACCURACY = "accuracy"  # 准确率
    PRECISION = "precision"  # 精确率
    RECALL = "recall"  # 召回率
    F1 = "f1"  # F1 分数
    MACRO_F1 = "macro_f1"  # 宏平均 F1
    MICRO_F1 = "micro_f1"  # 微平均 F1

    # 排序指标
    NDCG = "ndcg"  # 归一化折扣累积增益
    MAP = "map"  # 平均精确率

    # 语义指标
    SEMANTIC_SIMILARITY = "semantic_similarity"  # 语义相似度
    ROUGE_L = "rouge_l"  # ROUGE-L
    BLEU = "bleu"  # BLEU

    # 质量指标
    QUALITY_SCORE = "quality_score"  # 质量评分（LLM-as-Judge）
    REASONING_SCORE = "reasoning_score"  # 推理评分

    # 工作流指标
    SUCCESS_RATE = "success_rate"  # 成功率
    TOOL_CALL_ACCURACY = "tool_call_accuracy"  # 工具调用准确率
    ITERATION_COUNT = "iteration_count"  # 迭代次数


@dataclass
class ContractEvaluationMetrics:
    """合同审核评估指标数据类。

    包含所有评估维度的指标值，以及用于计算综合评分的权重配置。
    设计原因：
    1. 单一指标无法全面评估合同审核质量
    2. 不同业务场景对各维度权重有不同需求
    3. 支持细粒度诊断和针对性优化
    """

    # ===== 合同分类指标 =====
    contract_classification_accuracy: float = 0.0  # 合同类型分类准确率
    contract_classification_precision: float = 0.0  # 精确率
    contract_classification_recall: float = 0.0  # 召回率
    contract_classification_f1: float = 0.0  # F1 分数

    # ===== 条款抽取指标 =====
    clause_extraction_precision: float = 0.0  # 条款抽取精确率
    clause_extraction_recall: float = 0.0  # 条款抽取召回率
    clause_extraction_f1: float = 0.0  # F1 分数
    clause_extraction_span_f1: float = 0.0  # 条款跨度 F1（用于 span-level 评估）
    clause_extraction_accuracy: float = 0.0  # 条款抽取准确率

    # ===== 条款分类指标 =====
    clause_classification_precision: float = 0.0
    clause_classification_recall: float = 0.0
    clause_classification_f1: float = 0.0
    clause_classification_macro_f1: float = 0.0

    # ===== 风险识别指标 =====
    risk_identification_precision: float = 0.0  # 风险识别精确率
    risk_identification_recall: float = 0.0  # 风险识别召回率
    risk_identification_f1: float = 0.0  # F1 分数
    risk_identification_accuracy: float = 0.0  # 风险识别准确率

    # ===== 风险等级评估指标 =====
    risk_level_accuracy: float = 0.0  # 风险等级判定准确率
    risk_level_confusion_matrix: dict[str, Any] = field(default_factory=dict)  # 混淆矩阵

    # ===== 条款完整性指标 =====
    clause_completeness_rate: float = 0.0  # 条款完整率（实际抽取/应该抽取）
    missing_clause_detection_rate: float = 0.0  # 缺失条款检测率

    # ===== 法律合规性指标 =====
    legal_compliance_rate: float = 0.0  # 法律合规率
    regulation_citation_rate: float = 0.0  # 法规引用率

    # ===== 报告质量指标 =====
    report_quality_score: float = 0.0  # 报告质量评分（LLM-as-Judge）
    report_rouge_l: float = 0.0  # ROUGE-L
    report_semantic_similarity: float = 0.0  # 报告语义相似度
    suggestion_quality_score: float = 0.0  # 建议质量评分

    # ===== 引用准确性指标 =====
    citation_recall: float = 0.0  # 引用召回率（引用的风险项在合同中存在）
    citation_precision: float = 0.0  # 引用精确率（引用的条款内容准确）
    citation_accuracy: float = 0.0  # 引用准确率

    # ===== 工作流指标 =====
    workflow_success_rate: float = 0.0  # 工作流成功率
    tool_call_accuracy: float = 0.0  # 工具调用准确率
    tool_call_completeness: float = 0.0  # 工具调用完整性
    average_iterations: float = 0.0  # 平均迭代次数
    human_review_trigger_rate: float = 0.0  # Human Review 触发率
    human_review_agreement_rate: float = 0.0  # Human Review 一致率

    # ===== 反思质量指标 =====
    reflection_confidence_accuracy: float = 0.0  # 反思置信度与实际一致性
    reflection_issue_detection_rate: float = 0.0  # 反思问题检出率

    def to_dict(self) -> dict[str, float]:
        """转换为字典格式。"""
        return {
            "contract_classification": {
                "accuracy": self.contract_classification_accuracy,
                "precision": self.contract_classification_precision,
                "recall": self.contract_classification_recall,
                "f1": self.contract_classification_f1,
            },
            "clause_extraction": {
                "precision": self.clause_extraction_precision,
                "recall": self.clause_extraction_recall,
                "f1": self.clause_extraction_f1,
                "span_f1": self.clause_extraction_span_f1,
            },
            "clause_classification": {
                "precision": self.clause_classification_precision,
                "recall": self.clause_classification_recall,
                "f1": self.clause_classification_f1,
                "macro_f1": self.clause_classification_macro_f1,
            },
            "risk_identification": {
                "precision": self.risk_identification_precision,
                "recall": self.risk_identification_recall,
                "f1": self.risk_identification_f1,
                "accuracy": self.risk_identification_accuracy,
            },
            "risk_level_assessment": {
                "accuracy": self.risk_level_accuracy,
            },
            "clause_completeness": {
                "completeness_rate": self.clause_completeness_rate,
                "missing_detection_rate": self.missing_clause_detection_rate,
            },
            "legal_compliance": {
                "compliance_rate": self.legal_compliance_rate,
                "citation_rate": self.regulation_citation_rate,
            },
            "report_quality": {
                "quality_score": self.report_quality_score,
                "rouge_l": self.report_rouge_l,
                "semantic_similarity": self.report_semantic_similarity,
            },
            "citation": {
                "recall": self.citation_recall,
                "precision": self.citation_precision,
                "accuracy": self.citation_accuracy,
            },
            "workflow": {
                "success_rate": self.workflow_success_rate,
                "tool_call_accuracy": self.tool_call_accuracy,
                "tool_call_completeness": self.tool_call_completeness,
                "average_iterations": self.average_iterations,
                "human_review_trigger_rate": self.human_review_trigger_rate,
            },
        }

    def get_weighted_overall_score(
        self,
        weights: dict[str, float] | None = None,
    ) -> float:
        """计算加权综合评分。

        Args:
            weights: 各维度权重配置，默认为推荐权重

        Returns:
            加权综合评分（0-100）
        """
        if weights is None:
            # 默认权重配置（基于业务重要性）
            weights = {
                "contract_classification": 0.10,
                "clause_extraction": 0.15,
                "risk_identification": 0.20,
                "risk_level_assessment": 0.10,
                "report_quality": 0.15,
                "citation": 0.10,
                "workflow": 0.10,
                "legal_compliance": 0.05,
                "reflection": 0.05,
            }

        score = 0.0
        total_weight = 0.0

        # 合同分类
        score += self.contract_classification_f1 * weights.get("contract_classification", 0.10)
        total_weight += weights.get("contract_classification", 0.10)

        # 条款抽取
        score += self.clause_extraction_f1 * weights.get("clause_extraction", 0.15)
        total_weight += weights.get("clause_extraction", 0.15)

        # 风险识别
        score += self.risk_identification_f1 * weights.get("risk_identification", 0.20)
        total_weight += weights.get("risk_identification", 0.20)

        # 风险等级评估
        score += self.risk_level_accuracy * weights.get("risk_level_assessment", 0.10)
        total_weight += weights.get("risk_level_assessment", 0.10)

        # 报告质量
        score += self.report_quality_score * weights.get("report_quality", 0.15)
        total_weight += weights.get("report_quality", 0.15)

        # 引用准确性
        score += self.citation_accuracy * weights.get("citation", 0.10)
        total_weight += weights.get("citation", 0.10)

        # 工作流质量
        score += self.workflow_success_rate * weights.get("workflow", 0.10)
        total_weight += weights.get("workflow", 0.10)

        # 法律合规
        score += self.legal_compliance_rate * weights.get("legal_compliance", 0.05)
        total_weight += weights.get("legal_compliance", 0.05)

        # 反思质量
        score += self.reflection_confidence_accuracy * weights.get("reflection", 0.05)
        total_weight += weights.get("reflection", 0.05)

        if total_weight == 0:
            return 0.0

        return (score / total_weight) * 100


@dataclass
class ContractEvaluationResult:
    """合同审核评估结果数据类。

    包含单个合同的评估结果，以及用于诊断问题的详细信息。
    """

    # 合同标识
    contract_id: str  # 合同 ID
    contract_name: str  # 合同名称
    contract_type: str  # 合同类型

    # 评估维度得分
    metrics: ContractEvaluationMetrics

    # 详细评估结果
    classification_result: ClassificationResult | None = None  # 分类结果
    extraction_results: list[ExtractionResult] | None = None  # 抽取结果列表
    risk_results: list[RiskResult] | None = None  # 风险识别结果列表
    report_result: ReportResult | None = None  # 报告评估结果
    workflow_result: WorkflowResult | None = None  # 工作流评估结果

    # 错误分析
    errors: list[str] = field(default_factory=list)  # 错误列表
    warnings: list[str] = field(default_factory=list)  # 警告列表

    # 综合评分
    overall_score: float = 0.0  # 综合评分（0-100）

    # 评估元数据
    evaluation_time_ms: float = 0.0  # 评估耗时（毫秒）
    model_used: str = ""  # 使用的模型
    judge_type: str = ""  # 评估器类型

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "contract_id": self.contract_id,
            "contract_name": self.contract_name,
            "contract_type": self.contract_type,
            "metrics": self.metrics.to_dict(),
            "overall_score": self.overall_score,
            "classification_result": self.classification_result.to_dict() if self.classification_result else None,
            "extraction_results": [r.to_dict() for r in self.extraction_results] if self.extraction_results else [],
            "risk_results": [r.to_dict() for r in self.risk_results] if self.risk_results else [],
            "report_result": self.report_result.to_dict() if self.report_result else None,
            "workflow_result": self.workflow_result.to_dict() if self.workflow_result else None,
            "errors": self.errors,
            "warnings": self.warnings,
            "evaluation_time_ms": self.evaluation_time_ms,
            "model_used": self.model_used,
            "judge_type": self.judge_type,
        }


@dataclass
class ClassificationResult:
    """分类评估结果。"""

    predicted_class: str  # 预测类别
    ground_truth_class: str  # 标准类别
    is_correct: bool  # 是否正确
    confidence: float  # 置信度
    top_k_predictions: list[tuple[str, float]] = field(default_factory=list)  # Top-K 预测

    def to_dict(self) -> dict[str, Any]:
        return {
            "predicted": self.predicted_class,
            "ground_truth": self.ground_truth_class,
            "correct": self.is_correct,
            "confidence": self.confidence,
            "top_k": self.top_k_predictions,
        }


@dataclass
class ExtractionResult:
    """条款抽取评估结果。"""

    clause_id: str  # 条款 ID
    clause_title: str  # 条款标题
    predicted_content: str  # 预测内容
    ground_truth_content: str  # 标准内容
    is_extracted: bool  # 是否抽取
    content_overlap: float = 0.0  # 内容重叠度（0-1）
    semantic_similarity: float = 0.0  # 语义相似度（0-1）
    position_correct: bool = False  # 位置是否正确

    def to_dict(self) -> dict[str, Any]:
        return {
            "clause_id": self.clause_id,
            "clause_title": self.clause_title,
            "extracted": self.is_extracted,
            "content_overlap": self.content_overlap,
            "semantic_similarity": self.semantic_similarity,
            "position_correct": self.position_correct,
        }


@dataclass
class RiskResult:
    """风险识别评估结果。"""

    risk_id: str  # 风险 ID
    risk_type: str  # 风险类型
    predicted_level: str  # 预测风险等级
    ground_truth_level: str  # 标准风险等级
    is_identified: bool  # 是否识别
    level_correct: bool  # 等级是否正确
    related_clause: str  # 关联条款
    predicted_description: str = ""  # 预测描述
    ground_truth_description: str = ""  # 标准描述
    suggestion_accuracy: float = 0.0  # 建议准确性（0-1）

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_id": self.risk_id,
            "risk_type": self.risk_type,
            "identified": self.is_identified,
            "predicted_level": self.predicted_level,
            "ground_truth_level": self.ground_truth_level,
            "level_correct": self.level_correct,
            "related_clause": self.related_clause,
            "suggestion_accuracy": self.suggestion_accuracy,
        }


@dataclass
class ReportResult:
    """报告评估结果。"""

    quality_score: float  # 质量评分（0-1）
    rouge_l: float  # ROUGE-L
    semantic_similarity: float  # 语义相似度
    completeness_score: float  # 完整性评分
    accuracy_score: float  # 准确性评分
    suggestion_relevance: float  # 建议相关性
    citation_accuracy: float  # 引用准确性
    reasoning_quality: float  # 推理质量
    issues: list[str] = field(default_factory=list)  # 发现的问题

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality_score": self.quality_score,
            "rouge_l": self.rouge_l,
            "semantic_similarity": self.semantic_similarity,
            "completeness_score": self.completeness_score,
            "accuracy_score": self.accuracy_score,
            "suggestion_relevance": self.suggestion_relevance,
            "citation_accuracy": self.citation_accuracy,
            "reasoning_quality": self.reasoning_quality,
            "issues": self.issues,
        }


@dataclass
class WorkflowResult:
    """工作流评估结果。"""

    success: bool  # 是否成功完成
    completed_tools: list[str] = field(default_factory=list)  # 完成的工具列表
    tool_execution_order: list[str] = field(default_factory=list)  # 工具执行顺序
    iterations: int = 0  # 迭代次数
    reflection_triggered: bool = False  # 是否触发反思
    human_review_triggered: bool = False  # 是否触发 Human Review
    tool_errors: list[str] = field(default_factory=list)  # 工具错误
    total_time_ms: float = 0.0  # 总耗时

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "completed_tools": self.completed_tools,
            "tool_execution_order": self.tool_execution_order,
            "iterations": self.iterations,
            "reflection_triggered": self.reflection_triggered,
            "human_review_triggered": self.human_review_triggered,
            "tool_errors": self.tool_errors,
            "total_time_ms": self.total_time_ms,
        }
