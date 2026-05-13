"""基于 RAGAS 框架的合同审查评估器。

使用 RAGAS 官方指标评估四个核心 Tool 的输出质量：

【检索类 Tool】→ 使用 Context 相关指标
  - search_laws: 法规检索
  - search_templates: 模板检索

【生成类 Tool】→ 使用 Generation 相关指标
  - extract_clauses: 条款抽取
  - analyze_risk: 风险分析

RAGAS 指标映射：
| Tool 类型 | Tool 名称 | RAGAS 指标 |
|-----------|-----------|------------|
| 检索类 | search_laws | Context Precision, Context Recall |
| 检索类 | search_templates | Context Precision, Context Recall |
| 生成类 | extract_clauses | Faithfulness, Answer Relevance, Answer Correctness |
| 生成类 | analyze_risk | Faithfulness, Answer Relevance, Answer Correctness |

设计原因：
1. RAGAS 是经过社区验证的 RAG 评估框架
2. 复用成熟指标，避免重复造轮子
3. 支持离线批量评估和在线实时评估
4. 生成类指标说明：
   - Faithfulness: 检测幻觉（答案是否有依据）
   - Answer Relevance: 检测切题（答案是否回答问题）
   - Answer Correctness: 检测正确性（与 ground_truth 的匹配程度）
   - 注意：Answer Correctness 需要 ground_truth，适用于需要与标准答案对比的场景

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ==================== 数据集 Schema ====================


class RetrievalDatasetItem(BaseModel):
    """检索类数据集项（用于 search_laws, search_templates）。

    RAGAS 检索评估需要的数据结构：
    - user_input: 查询问题
    - retrieved_contexts: 检索返回的上下文
    - ground_truth_contexts: 标准相关的上下文

    数据来源与清洗：
    1. 从合同审查历史案例中提取
    2. 人工标注检索 query 和相关文档
    3. 过滤噪音数据，保留有效 query
    """

    question: str = Field(description="检索 query，如：'采购合同违约金相关法规'")
    retrieval_result: list[str] = Field(
        description="Tool 返回的检索结果列表（已解析为纯文本）"
    )
    ground_truth: list[str] = Field(
        description="标准相关文档列表（人工标注的相关法规/模板）"
    )
    tool_name: str = Field(description="调用的工具名称：search_laws / search_templates")
    case_id: str = Field(description="关联的测试用例 ID")


class GenerationDatasetItem(BaseModel):
    """生成类数据集项（用于 extract_clauses, analyze_risk）。

    RAGAS 生成评估需要的数据结构：
    - user_input: 输入内容（合同文本/条款）
    - retrieved_contexts: 使用的上下文（法规、模板等）
    - response: 模型生成的答案
    - ground_truth: 标准答案

    数据来源与清洗：
    1. 从历史审查报告中提取条款和风险
    2. 人工标注条款类型、风险等级
    3. 清洗异常数据，确保 ground_truth 准确
    """

    question: str = Field(
        description="任务描述，如：'从以下合同中抽取所有条款并识别风险'"
    )
    input_content: str = Field(description="输入内容（合同文本/条款列表）")
    retrieved_contexts: list[str] = Field(
        description="使用的检索上下文（法规、模板等）"
    )
    response: str = Field(description="Tool 返回的生成结果")
    ground_truth: str = Field(description="标准答案（人工标注）")
    tool_name: str = Field(description="调用的工具名称：extract_clauses / analyze_risk")
    case_id: str = Field(description="关联的测试用例 ID")


# ==================== RAGAS 评估结果 ====================


@dataclass
class RetrievalEvaluationResult:
    """检索类 Tool 评估结果。"""

    tool_name: str  # search_laws / search_templates
    case_id: str

    # RAGAS 核心指标
    context_precision: float  # 上下文精确率
    context_recall: float  # 上下文召回率

    # 辅助信息
    question: str
    retrieved_count: int
    ground_truth_count: int
    evaluation_details: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationEvaluationResult:
    """生成类 Tool 评估结果。"""

    tool_name: str  # extract_clauses / analyze_risk
    case_id: str

    # RAGAS 核心指标
    faithfulness: float = 0.0  # 忠实率（生成内容是否忠实于上下文，无幻觉）
    answer_relevance: float = 0.0  # 答案相关性（答案是否回答了问题）
    answer_correctness: float = 0.0  # 答案正确性（与 ground_truth 的匹配程度）

    # 辅助信息
    question: str
    response_length: int
    ground_truth_length: int
    evaluation_details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolEvaluationResult:
    """单个 Tool 的完整评估结果。"""

    tool_name: str
    tool_type: str  # retrieval / generation
    case_id: str

    # RAGAS 指标
    context_precision: float = 0.0  # 仅检索类
    context_recall: float = 0.0  # 仅检索类
    faithfulness: float = 0.0  # 仅生成类
    answer_relevance: float = 0.0  # 仅生成类
    answer_correctness: float = 0.0  # 仅生成类，需要 ground_truth

    # 综合评分
    overall_score: float = 0.0

    # 详细信息
    question: str = ""
    evaluation_details: dict[str, Any] = field(default_factory=dict)


# ==================== RAGAS 评估器实现 ====================


class RAGASEvaluator:
    """基于 RAGAS 框架的合同审查 Tool 评估器。

    核心职责：
    1. 评估检索类 Tool（search_laws, search_templates）
    2. 评估生成类 Tool（extract_clauses, analyze_risk）
    3. 生成评估报告

    设计原因：
    - 检索类 Tool 使用 Context Precision/Recall 评估检索质量
    - 生成类 Tool 使用 Faithfulness/Answer Relevance/Answer Correctness 评估生成质量
    - Answer Correctness 需要 ground_truth，用于检测与标准答案的匹配程度
    - RAGAS 提供了经过验证的评估方法论
    """

    def __init__(
        self,
        embedder_model: str = "bge-m3",
        judge_model: str = "qwen-32b",
    ) -> None:
        """初始化 RAGAS 评估器。

        Args:
            embedder_model: Embedding 模型名称（用于语义相似度计算）
            judge_model: Judge 模型名称（用于 LLM 评估）
        """
        self._embedder_model = embedder_model
        self._judge_model = judge_model
        self._ragas_available = self._check_ragas()

        logger.info(
            f"RAGASEvaluator 初始化完成 | "
            f"embedder={embedder_model} | judge={judge_model} | "
            f"ragas_available={self._ragas_available}"
        )

    def _check_ragas(self) -> bool:
        """检查 RAGAS 是否可用。"""
        try:
            import ragas
            logger.info(f"RAGAS 版本: {ragas.__version__}")
            return True
        except ImportError:
            logger.warning("RAGAS 未安装，将使用简化评估方法")
            return False

    # ==================== 检索类 Tool 评估 ====================

    def evaluate_retrieval_tool(
        self,
        dataset: list[RetrievalDatasetItem],
    ) -> list[RetrievalEvaluationResult]:
        """评估检索类 Tool。

        评估指标：
        - Context Precision: Top-K 结果中有多少是相关的
        - Context Recall: 相关文档被召回的比例

        Args:
            dataset: 检索类数据集

        Returns:
            评估结果列表
        """
        logger.info(f"[RAGASEvaluator] 开始评估检索类 Tool | 数据量: {len(dataset)}")

        results = []
        for item in dataset:
            result = self._evaluate_single_retrieval(item)
            results.append(result)

        # 计算平均指标
        avg_precision = sum(r.context_precision for r in results) / len(results)
        avg_recall = sum(r.context_recall for r in results) / len(results)

        logger.info(
            f"[RAGASEvaluator] 检索类 Tool 评估完成 | "
            f"avg_precision={avg_precision:.3f} | avg_recall={avg_recall:.3f}"
        )

        return results

    def _evaluate_single_retrieval(
        self,
        item: RetrievalDatasetItem,
    ) -> RetrievalEvaluationResult:
        """评估单条检索数据。

        Args:
            item: 检索数据集项

        Returns:
            评估结果
        """
        retrieved = item.retrieval_result
        ground_truth = item.ground_truth

        if self._ragas_available:
            # 使用 RAGAS 评估
            context_precision, context_recall = self._ragas_evaluate_retrieval(item)
        else:
            # 使用简化评估方法
            context_precision, context_recall = self._simple_evaluate_retrieval(item)

        return RetrievalEvaluationResult(
            tool_name=item.tool_name,
            case_id=item.case_id,
            context_precision=context_precision,
            context_recall=context_recall,
            question=item.question,
            retrieved_count=len(retrieved),
            ground_truth_count=len(ground_truth),
        )

    def _ragas_evaluate_retrieval(
        self,
        item: RetrievalDatasetItem,
    ) -> tuple[float, float]:
        """使用 RAGAS 评估检索质量。

        Args:
            item: 检索数据集项

        Returns:
            (context_precision, context_recall)
        """
        try:
            from ragas import evaluate
            from ragas.metrics import context_precision, context_recall

            # 构建 RAGAS 数据集格式
            from ragas.dataset_schema import SingleTurnSample

            sample = SingleTurnSample(
                user_input=item.question,
                retrieved_contexts=item.retrieval_result,
                reference=item.ground_truth,
            )

            # 执行评估
            result = evaluate(
                dataset=[sample],
                metrics=[context_precision, context_recall],
            )

            return (
                result["context_precision"] / 100.0,
                result["context_recall"] / 100.0,
            )

        except Exception as e:
            logger.warning(f"RAGAS 评估失败，降级到简化方法: {e}")
            return self._simple_evaluate_retrieval(item)

    def _simple_evaluate_retrieval(
        self,
        item: RetrievalDatasetItem,
    ) -> tuple[float, float]:
        """简化评估方法（当 RAGAS 不可用时）。

        实现逻辑：
        - Context Precision: 检索结果中有多少与 ground_truth 重叠
        - Context Recall: ground_truth 中有多少被检索到

        Args:
            item: 检索数据集项

        Returns:
            (context_precision, context_recall)
        """
        retrieved = item.retrieval_result
        ground_truth = item.ground_truth

        if not retrieved or not ground_truth:
            return (0.0, 0.0)

        # 标准化比较：将文本转为集合
        retrieved_set = set(self._normalize_text(r) for r in retrieved)
        gt_set = set(self._normalize_text(g) for g in ground_truth)

        # 计算重叠
        overlap = retrieved_set & gt_set

        # Context Precision: 检索到的相关内容 / 总检索数
        precision = len(overlap) / len(retrieved_set) if retrieved_set else 0.0

        # Context Recall: 检索到的相关内容 / 全部相关
        recall = len(overlap) / len(gt_set) if gt_set else 0.0

        return (precision, recall)

    # ==================== 生成类 Tool 评估 ====================

    def evaluate_generation_tool(
        self,
        dataset: list[GenerationDatasetItem],
    ) -> list[GenerationEvaluationResult]:
        """评估生成类 Tool。

        评估指标：
        - Faithfulness: 生成内容是否忠实于检索上下文（幻觉检测）
        - Answer Relevance: 答案与问题的相关程度（切题检测）
        - Answer Correctness: 答案与 ground_truth 的匹配程度（正确性检测）

        注意：Answer Correctness 需要 ground_truth，适用于需要与标准答案对比的场景。

        Args:
            dataset: 生成类数据集

        Returns:
            评估结果列表
        """
        logger.info(f"[RAGASEvaluator] 开始评估生成类 Tool | 数据量: {len(dataset)}")

        results = []
        for item in dataset:
            result = self._evaluate_single_generation(item)
            results.append(result)

        # 计算平均指标
        avg_faithfulness = sum(r.faithfulness for r in results) / len(results)
        avg_relevance = sum(r.answer_relevance for r in results) / len(results)
        avg_correctness = sum(r.answer_correctness for r in results) / len(results)

        logger.info(
            f"[RAGASEvaluator] 生成类 Tool 评估完成 | "
            f"avg_faithfulness={avg_faithfulness:.3f} | "
            f"avg_relevance={avg_relevance:.3f} | "
            f"avg_correctness={avg_correctness:.3f}"
        )

        return results

    def _evaluate_single_generation(
        self,
        item: GenerationDatasetItem,
    ) -> GenerationEvaluationResult:
        """评估单条生成数据。

        Args:
            item: 生成数据集项

        Returns:
            评估结果
        """
        if self._ragas_available:
            faithfulness, relevance, correctness = self._ragas_evaluate_generation(item)
        else:
            faithfulness, relevance, correctness = self._simple_evaluate_generation(item)

        return GenerationEvaluationResult(
            tool_name=item.tool_name,
            case_id=item.case_id,
            faithfulness=faithfulness,
            answer_relevance=relevance,
            answer_correctness=correctness,
            question=item.question,
            response_length=len(item.response),
            ground_truth_length=len(item.ground_truth),
        )

    def _ragas_evaluate_generation(
        self,
        item: GenerationDatasetItem,
    ) -> tuple[float, float, float]:
        """使用 RAGAS 评估生成质量。

        评估指标：
        - Faithfulness: 幻觉检测（答案是否有依据）
        - Answer Relevance: 切题检测（答案是否回答了问题）
        - Answer Correctness: 正确性检测（与 ground_truth 的匹配程度）

        注意：Answer Correctness 需要 ground_truth，适用于需要与标准答案对比的场景。

        Args:
            item: 生成数据集项

        Returns:
            (faithfulness, answer_relevance, answer_correctness)
        """
        try:
            from ragas import evaluate
            from ragas.metrics import faithfulness, answer_relevance, answer_correctness

            # 构建 RAGAS 数据集格式
            from ragas.dataset_schema import SingleTurnSample

            sample = SingleTurnSample(
                user_input=item.question,
                retrieved_contexts=item.retrieved_contexts,
                response=item.response,
                reference=item.ground_truth,  # answer_correctness 需要 reference
            )

            # 执行评估（三个指标都需要 ground_truth）
            result = evaluate(
                dataset=[sample],
                metrics=[faithfulness, answer_relevance, answer_correctness],
            )

            return (
                result["faithfulness"] / 100.0,
                result["answer_relevance"] / 100.0,
                result["answer_correctness"] / 100.0,
            )

        except Exception as e:
            logger.warning(f"RAGAS 评估失败，降级到简化方法: {e}")
            return self._simple_evaluate_generation(item)

    def _simple_evaluate_generation(
        self,
        item: GenerationDatasetItem,
    ) -> tuple[float, float, float]:
        """简化评估方法（当 RAGAS 不可用时）。

        实现逻辑：
        - Faithfulness: 生成内容中的关键实体有多少在上下文中出现
        - Answer Relevance: 生成内容与问题的语义相似度
        - Answer Correctness: 生成内容与 ground_truth 的语义相似度

        Args:
            item: 生成数据集项

        Returns:
            (faithfulness, answer_relevance, answer_correctness)
        """
        response = item.response
        contexts = item.retrieved_contexts
        ground_truth = item.ground_truth
        question = item.question

        if not response or not contexts:
            return (0.0, 0.0, 0.0)

        # 合并上下文
        combined_context = " ".join(contexts)

        # ===== Faithfulness =====
        # 检查 response 中的关键信息是否在上下文中
        response_entities = self._extract_key_entities(response)
        context_entities = set(self._normalize_text(combined_context).split())

        # 统计在上下文中存在的实体
        found_entities = sum(
            1 for entity in response_entities
            if any(entity in self._normalize_text(ctx) for ctx in contexts)
        )

        faithfulness = found_entities / len(response_entities) if response_entities else 0.0

        # ===== Answer Relevance =====
        # 使用 token overlap 作为简化指标（与问题的相关性）
        response_tokens = set(self._normalize_text(response).split())
        question_tokens = set(self._normalize_text(question).split())

        if not response_tokens or not question_tokens:
            relevance = 0.0
        else:
            overlap = len(response_tokens & question_tokens)
            union = len(response_tokens | question_tokens)
            relevance = overlap / union if union > 0 else 0.0

        # ===== Answer Correctness =====
        # 使用 token overlap 作为简化指标（与 ground_truth 的匹配程度）
        gt_tokens = set(self._normalize_text(ground_truth).split())

        if not response_tokens or not gt_tokens:
            correctness = 0.0
        else:
            overlap = len(response_tokens & gt_tokens)
            union = len(response_tokens | gt_tokens)
            correctness = overlap / union if union > 0 else 0.0

        return (faithfulness, relevance, correctness)

    # ==================== 统一评估接口 ====================

    def evaluate_tool(
        self,
        retrieval_dataset: list[RetrievalDatasetItem] | None = None,
        generation_dataset: list[GenerationDatasetItem] | None = None,
    ) -> list[ToolEvaluationResult]:
        """统一评估接口。

        同时支持检索类和生成类 Tool 的评估。

        Args:
            retrieval_dataset: 检索类数据集
            generation_dataset: 生成类数据集

        Returns:
            所有 Tool 的评估结果
        """
        all_results: list[ToolEvaluationResult] = []

        # 评估检索类 Tool
        if retrieval_dataset:
            retrieval_results = self.evaluate_retrieval_tool(retrieval_dataset)
            for r in retrieval_results:
                all_results.append(ToolEvaluationResult(
                    tool_name=r.tool_name,
                    tool_type="retrieval",
                    case_id=r.case_id,
                    context_precision=r.context_precision,
                    context_recall=r.context_recall,
                    overall_score=(r.context_precision + r.context_recall) / 2,
                    question=r.question,
                ))

        # 评估生成类 Tool
        if generation_dataset:
            generation_results = self.evaluate_generation_tool(generation_dataset)
            for r in generation_results:
                all_results.append(ToolEvaluationResult(
                    tool_name=r.tool_name,
                    tool_type="generation",
                    case_id=r.case_id,
                    faithfulness=r.faithfulness,
                    answer_relevance=r.answer_relevance,
                    answer_correctness=r.answer_correctness,
                    # 综合分数 = (Faithfulness + Answer Relevance + Answer Correctness) / 3
                    overall_score=(r.faithfulness + r.answer_relevance + r.answer_correctness) / 3,
                    question=r.question,
                ))

        return all_results

    def generate_report(
        self,
        results: list[ToolEvaluationResult],
    ) -> dict[str, Any]:
        """生成评估报告。

        Args:
            results: 评估结果列表

        Returns:
            评估报告
        """
        if not results:
            return {"message": "没有评估结果"}

        # 按 tool 分组
        by_tool: dict[str, list[ToolEvaluationResult]] = {}
        for r in results:
            by_tool.setdefault(r.tool_name, []).append(r)

        # 计算每个 Tool 的平均指标
        tool_summary = {}
        for tool_name, tool_results in by_tool.items():
            n = len(tool_results)
            tool_type = tool_results[0].tool_type

            if tool_type == "retrieval":
                avg_precision = sum(r.context_precision for r in tool_results) / n
                avg_recall = sum(r.context_recall for r in tool_results) / n
                tool_summary[tool_name] = {
                    "tool_type": "retrieval",
                    "case_count": n,
                    "context_precision": avg_precision,
                    "context_recall": avg_recall,
                    "avg_score": (avg_precision + avg_recall) / 2,
                }
            else:
                avg_faithfulness = sum(r.faithfulness for r in tool_results) / n
                avg_relevance = sum(r.answer_relevance for r in tool_results) / n
                avg_correctness = sum(r.answer_correctness for r in tool_results) / n
                tool_summary[tool_name] = {
                    "tool_type": "generation",
                    "case_count": n,
                    "faithfulness": avg_faithfulness,
                    "answer_relevance": avg_relevance,
                    "answer_correctness": avg_correctness,
                    "avg_score": (avg_faithfulness + avg_relevance + avg_correctness) / 3,
                }

        # 计算总体平均
        overall_score = sum(r.overall_score for r in results) / len(results)

        return {
            "total_cases": len(results),
            "overall_score": overall_score,
            "tool_summary": tool_summary,
            "results": [r.evaluation_details for r in results],
        }

    # ==================== 辅助方法 ====================

    @staticmethod
    def _normalize_text(text: str) -> str:
        """标准化文本用于比较。"""
        if not text:
            return ""
        # 转小写、去除空白、去除标点
        import re
        text = text.lower().strip()
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[^\w\s]", "", text)
        return text

    @staticmethod
    def _extract_key_entities(text: str) -> list[str]:
        """提取文本中的关键实体（简化实现）。

        简化逻辑：提取长度 > 3 的连续中文字符序列
        实际生产中应使用 NER 模型或关键词提取

        Args:
            text: 输入文本

        Returns:
            关键实体列表
        """
        import re

        # 提取中文词组
        chinese_phrases = re.findall(r"[\u4e00-\u9fa5]{4,}", text)
        return chinese_phrases


# ==================== 便捷函数 ====================


def get_ragas_evaluator(
    embedder_model: str = "bge-m3",
    judge_model: str = "qwen-32b",
) -> RAGASEvaluator:
    """获取 RAGAS 评估器实例（单例模式）。

    Args:
        embedder_model: Embedding 模型
        judge_model: Judge 模型

    Returns:
        RAGASEvaluator 实例
    """
    global _ragas_evaluator_instance

    if _ragas_evaluator_instance is None:
        _ragas_evaluator_instance = RAGASEvaluator(
            embedder_model=embedder_model,
            judge_model=judge_model,
        )

    return _ragas_evaluator_instance


_ragas_evaluator_instance: RAGASEvaluator | None = None
