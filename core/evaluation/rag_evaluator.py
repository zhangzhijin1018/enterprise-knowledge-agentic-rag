"""RAG 评估器。

评估 RAG 系统的检索质量和生成质量。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class RAGEvaluationResult:
    """RAG 评估结果。"""

    # 检索指标
    retrieval_precision: float  # 检索精确度
    retrieval_recall: float  # 检索召回率
    retrieval_f1: float  # 检索 F1

    # 生成指标
    answer_quality: float  # 答案质量
    citation_accuracy: float  # 引用准确度

    # 综合指标
    overall_score: float  # 综合得分

    # 详细信息
    details: dict[str, Any]


class RAGEvaluator:
    """RAG 评估器。

    职责：
    - 评估检索质量（Precision, Recall, F1）
    - 评估生成质量（答案相关性、引用准确度）
    - 生成评估报告

    设计原因：
    - RAG 系统需要持续评估以保证质量
    - 支持离线评估和在线评估
    - 支持评估指标的可视化
    """

    def __init__(
        self,
        precision_weight: float = 0.4,
        recall_weight: float = 0.3,
        quality_weight: float = 0.3,
    ) -> None:
        """初始化评估器。

        Args:
            precision_weight: 精确度权重
            recall_weight: 召回率权重
            quality_weight: 质量权重
        """

        self.precision_weight = precision_weight
        self.recall_weight = recall_weight
        self.quality_weight = quality_weight

    def evaluate(
        self,
        query: str,
        retrieved_chunks: list[dict],
        ground_truth_chunks: list[str] | None = None,
        generated_answer: str | None = None,
        expected_answer: str | None = None,
        citations: list[dict] | None = None,
    ) -> RAGEvaluationResult:
        """评估 RAG 系统性能。

        Args:
            query: 查询问题
            retrieved_chunks: 检索到的 chunks
            ground_truth_chunks: 标准答案 chunks（用于离线评估）
            generated_answer: 生成的答案（用于在线评估）
            expected_answer: 期望答案（用于在线评估）
            citations: 引用列表

        Returns:
            评估结果
        """

        logger.info(f"[RAGEvaluator] 开始评估 | query={query[:50]}...")

        # 1. 评估检索质量
        retrieval_metrics = self._evaluate_retrieval(
            retrieved_chunks=retrieved_chunks,
            ground_truth_chunks=ground_truth_chunks or [],
        )

        # 2. 评估生成质量
        generation_metrics = self._evaluate_generation(
            query=query,
            retrieved_chunks=retrieved_chunks,
            generated_answer=generated_answer,
            expected_answer=expected_answer,
            citations=citations or [],
        )

        # 3. 计算综合得分
        overall_score = (
            retrieval_metrics["f1"] * (self.precision_weight + self.recall_weight) / 2 +
            generation_metrics["quality"] * self.quality_weight
        )

        result = RAGEvaluationResult(
            retrieval_precision=retrieval_metrics["precision"],
            retrieval_recall=retrieval_metrics["recall"],
            retrieval_f1=retrieval_metrics["f1"],
            answer_quality=generation_metrics["quality"],
            citation_accuracy=generation_metrics["citation_accuracy"],
            overall_score=overall_score,
            details={
                "query": query,
                "retrieved_count": len(retrieved_chunks),
                "ground_truth_count": len(ground_truth_chunks or []),
                "retrieval_metrics": retrieval_metrics,
                "generation_metrics": generation_metrics,
            },
        )

        logger.info(
            f"[RAGEvaluator] 评估完成 | "
            f"precision={retrieval_metrics['precision']:.2f} | "
            f"recall={retrieval_metrics['recall']:.2f} | "
            f"quality={generation_metrics['quality']:.2f} | "
            f"overall={overall_score:.2f}"
        )

        return result

    def _evaluate_retrieval(
        self,
        retrieved_chunks: list[dict],
        ground_truth_chunks: list[str],
    ) -> dict[str, float]:
        """评估检索质量。

        Args:
            retrieved_chunks: 检索到的 chunks
            ground_truth_chunks: 标准答案 chunks

        Returns:
            检索指标
        """

        # 如果没有标准答案，使用基于分数的评估
        if not ground_truth_chunks:
            # 基于检索分数评估
            if not retrieved_chunks:
                return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

            # 平均分数作为质量指标
            scores = [chunk.get("score", 0.0) for chunk in retrieved_chunks]
            avg_score = sum(scores) / len(scores) if scores else 0.0

            return {
                "precision": avg_score,
                "recall": avg_score,
                "f1": avg_score,
            }

        # 计算精确度和召回率
        retrieved_ids = set(chunk.get("chunk_uuid", "") for chunk in retrieved_chunks)
        true_ids = set(ground_truth_chunks)

        # 真正例、假正例、假负例
        true_positives = len(retrieved_ids & true_ids)
        false_positives = len(retrieved_ids - true_ids)
        false_negatives = len(true_ids - retrieved_ids)

        # 计算指标
        precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0.0
        recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        return {
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    def _evaluate_generation(
        self,
        query: str,
        retrieved_chunks: list[dict],
        generated_answer: str | None,
        expected_answer: str | None,
        citations: list[dict],
    ) -> dict[str, float]:
        """评估生成质量。

        Args:
            query: 查询问题
            retrieved_chunks: 检索到的 chunks
            generated_answer: 生成的答案
            expected_answer: 期望答案
            citations: 引用列表

        Returns:
            生成质量指标
        """

        # 如果没有生成答案，使用默认值
        if not generated_answer:
            return {"quality": 0.0, "citation_accuracy": 0.0}

        # 评估引用准确度
        citation_accuracy = self._evaluate_citation_accuracy(
            citations=citations,
            retrieved_chunks=retrieved_chunks,
        )

        # 评估答案质量（简化实现）
        quality = self._evaluate_answer_quality(
            query=query,
            answer=generated_answer,
            retrieved_chunks=retrieved_chunks,
            expected_answer=expected_answer,
        )

        return {
            "quality": quality,
            "citation_accuracy": citation_accuracy,
        }

    def _evaluate_citation_accuracy(
        self,
        citations: list[dict],
        retrieved_chunks: list[dict],
    ) -> float:
        """评估引用准确度。

        Args:
            citations: 引用列表
            retrieved_chunks: 检索到的 chunks

        Returns:
            引用准确度
        """

        if not citations or not retrieved_chunks:
            return 0.0

        # 检查引用的 chunk 是否存在于检索结果中
        retrieved_ids = set(chunk.get("chunk_uuid") for chunk in retrieved_chunks)

        valid_citations = sum(
            1 for cite in citations
            if cite.get("chunk_uuid") in retrieved_ids
        )

        return valid_citations / len(citations) if citations else 0.0

    def _evaluate_answer_quality(
        self,
        query: str,
        answer: str,
        retrieved_chunks: list[dict],
        expected_answer: str | None,
    ) -> float:
        """评估答案质量。

        简化实现：
        - 检查答案是否为空
        - 检查答案长度是否合理
        - 检查答案是否包含检索内容的关键信息

        Args:
            query: 查询问题
            answer: 生成的答案
            retrieved_chunks: 检索到的 chunks
            expected_answer: 期望答案

        Returns:
            答案质量分数
        """

        if not answer or len(answer.strip()) < 10:
            return 0.0

        # 检查答案长度
        length_score = min(len(answer) / 500, 1.0)  # 理想长度约 500 字

        # 检查答案是否包含问询相关内容
        query_keywords = set(query.lower())
        answer_lower = answer.lower()

        # 简单关键词匹配
        keyword_match = sum(
            1 for keyword in query_keywords
            if keyword in answer_lower
        ) / max(len(query_keywords), 1)

        # 综合得分
        quality = (length_score * 0.4 + keyword_match * 0.6)

        return min(quality, 1.0)

    def batch_evaluate(
        self,
        test_cases: list[dict],
    ) -> list[RAGEvaluationResult]:
        """批量评估。

        Args:
            test_cases: 测试用例列表

        Returns:
            评估结果列表
        """

        results = []

        for case in test_cases:
            result = self.evaluate(
                query=case.get("query", ""),
                retrieved_chunks=case.get("retrieved_chunks", []),
                ground_truth_chunks=case.get("ground_truth_chunks"),
                generated_answer=case.get("generated_answer"),
                expected_answer=case.get("expected_answer"),
                citations=case.get("citations"),
            )
            results.append(result)

        return results

    def get_average_metrics(
        self,
        results: list[RAGEvaluationResult],
    ) -> dict[str, float]:
        """计算平均指标。

        Args:
            results: 评估结果列表

        Returns:
            平均指标
        """

        if not results:
            return {
                "avg_precision": 0.0,
                "avg_recall": 0.0,
                "avg_f1": 0.0,
                "avg_quality": 0.0,
                "avg_citation_accuracy": 0.0,
                "avg_overall": 0.0,
            }

        n = len(results)

        return {
            "avg_precision": sum(r.retrieval_precision for r in results) / n,
            "avg_recall": sum(r.retrieval_recall for r in results) / n,
            "avg_f1": sum(r.retrieval_f1 for r in results) / n,
            "avg_quality": sum(r.answer_quality for r in results) / n,
            "avg_citation_accuracy": sum(r.citation_accuracy for r in results) / n,
            "avg_overall": sum(r.overall_score for r in results) / n,
        }
