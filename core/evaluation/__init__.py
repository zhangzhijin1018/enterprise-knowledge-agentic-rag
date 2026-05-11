"""Evaluation 评估模块包。

提供 RAG、Agent、SQL、合同审核等评估功能。
"""

from core.evaluation.rag_evaluator import RAGEvaluator

# 合同审核评估指标
from core.evaluation.contract_evaluator.metrics import (
    ContractEvaluationMetrics,
    ContractEvaluationResult,
    EvaluationDimension,
    MetricType,
)
# 合同审核 Judge 评估器
from core.evaluation.contract_evaluator.judge import (
    ContractJudgeConfig,
    LLMJudgeEvaluator,
    DeterministicJudgeEvaluator,
    JudgeModel,
    EvaluationMode,
    ScoringScale,
    JudgeResponse,
)
# 合同审核数据集
from core.evaluation.contract_evaluator.dataset import (
    ContractTestCase,
    ContractTestSuite,
    ContractGroundTruth,
    ClauseGroundTruth,
    RiskGroundTruth,
    ContractTestDataGenerator,
    ContractType,
    RiskCategory,
    RiskLevel,
    DataSource,
)
# 合同审核报告
from core.evaluation.contract_evaluator.report import (
    ContractEvaluationReport,
    ReportGenerator,
)
# 合同审核核心评估器
from core.evaluation.contract_evaluator.evaluator import ContractEvaluator

__all__ = [
    # RAG 评估
    "RAGEvaluator",
    # 合同审核评估指标
    "ContractEvaluationMetrics",
    "ContractEvaluationResult",
    "ContractJudgeConfig",
    "EvaluationDimension",
    "MetricType",
    # 合同审核评估器
    "LLMJudgeEvaluator",
    "DeterministicJudgeEvaluator",
    "JudgeModel",
    "EvaluationMode",
    "ScoringScale",
    "JudgeResponse",
    # 合同审核数据集
    "ContractTestCase",
    "ContractTestSuite",
    "ContractGroundTruth",
    "ClauseGroundTruth",
    "RiskGroundTruth",
    "ContractTestDataGenerator",
    "ContractType",
    "RiskCategory",
    "RiskLevel",
    "DataSource",
    # 报告
    "ContractEvaluationReport",
    "ReportGenerator",
    # 核心评估器
    "ContractEvaluator",
]
