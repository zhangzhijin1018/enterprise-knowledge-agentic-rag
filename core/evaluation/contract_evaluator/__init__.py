"""合同审核 Agent 评估器核心模块。

本模块提供：
1. 合同审核评估指标体系
2. LLM-as-Judge 评估器
3. 评估数据集管理
4. 评估报告生成

评估设计原则：
- 基于 2026 年最新的 Agent 评估方法论
- 支持离线批量评估和在线实时评估
- 支持多维度评分和综合评分
- 支持人工标注数据集和合成数据集
- 支持评估结果持久化和可视化

Author: Enterprise Knowledge Agentic RAG Platform
"""

# 注意：避免循环导入，使用延迟导入或直接导入子模块
# 如需导入，请使用：
# from core.evaluation.contract_evaluator.metrics import ContractEvaluationMetrics
# from core.evaluation.contract_evaluator.judge import LLMJudgeEvaluator
# etc.
