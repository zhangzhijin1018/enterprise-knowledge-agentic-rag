"""合同审核 Agent 核心评估器。

整合所有评估组件，提供统一的评估接口。

评估流程：
1. 加载测试套件
2. 对每个测试用例运行合同审核 Agent
3. 收集 Agent 输出
4. 使用 LLM Judge 和 Deterministic Judge 进行评估
5. 汇总评估结果
6. 生成评估报告

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core.evaluation.contract_evaluator.metrics import (
    ContractEvaluationMetrics,
    ContractEvaluationResult,
)
from core.evaluation.contract_evaluator.dataset import (
    ContractTestCase,
    ContractTestSuite,
)
from core.evaluation.contract_evaluator.judge import (
    ContractJudgeConfig,
    DeterministicJudgeEvaluator,
    LLMJudgeEvaluator,
)
from core.evaluation.contract_evaluator.report import ReportGenerator

logger = logging.getLogger(__name__)


class ContractEvaluator:
    """合同审核 Agent 核心评估器。

    核心职责：
    1. 编排评估流程
    2. 运行合同审核 Agent
    3. 收集和汇总评估结果
    4. 生成评估报告

    设计原因：
    1. 统一评估接口，简化调用
    2. 支持多种评估模式
    3. 支持评估结果持久化
    4. 支持评估结果可视化
    """

    def __init__(
        self,
        llm_judge_config: ContractJudgeConfig | None = None,
        agent_executor: Callable | None = None,
    ) -> None:
        """初始化评估器。

        Args:
            llm_judge_config: LLM Judge 配置
            agent_executor: Agent 执行器（异步函数）
        """
        self._llm_judge_config = llm_judge_config or ContractJudgeConfig()
        self._agent_executor = agent_executor

        # 初始化评估器
        self._llm_judge = LLMJudgeEvaluator(config=self._llm_judge_config)
        self._deterministic_judge = DeterministicJudgeEvaluator()
        self._report_generator = ReportGenerator()

        # 评估结果存储
        self._evaluation_results: list[ContractEvaluationResult] = []

        logger.info(
            f"ContractEvaluator 初始化完成 | "
            f"judge_model={self._llm_judge_config.judge_model.value}"
        )

    async def evaluate_single(
        self,
        test_case: ContractTestCase,
        agent_output: dict[str, Any] | None = None,
    ) -> ContractEvaluationResult:
        """评估单个测试用例。

        Args:
            test_case: 测试用例
            agent_output: Agent 输出（如果已有）

        Returns:
            评估结果
        """
        start_time = time.time()
        case_id = test_case.case_id

        logger.info(f"[{case_id}] 开始评估...")

        try:
            # 如果没有 Agent 输出，执行 Agent
            if agent_output is None:
                if self._agent_executor is None:
                    raise ValueError("需要提供 agent_executor 或 agent_output")
                agent_output = await self._agent_executor(test_case)

            # ===== 评估合同分类 =====
            classification_result = self._evaluate_classification(
                test_case=test_case,
                agent_output=agent_output,
            )

            # ===== 评估条款抽取 =====
            extraction_results = self._evaluate_clause_extraction(
                test_case=test_case,
                agent_output=agent_output,
            )

            # ===== 评估风险识别 =====
            risk_results = self._evaluate_risk_identification(
                test_case=test_case,
                agent_output=agent_output,
            )

            # ===== 评估报告质量 =====
            report_result = await self._evaluate_report_quality(
                test_case=test_case,
                agent_output=agent_output,
            )

            # ===== 评估工作流 =====
            workflow_result = self._evaluate_workflow(
                test_case=test_case,
                agent_output=agent_output,
            )

            # ===== 计算综合指标 =====
            metrics = self._calculate_metrics(
                classification_result=classification_result,
                extraction_results=extraction_results,
                risk_results=risk_results,
                report_result=report_result,
                workflow_result=workflow_result,
                test_case=test_case,
            )

            # ===== 计算综合评分 =====
            overall_score = metrics.get_weighted_overall_score()

            # 构建评估结果
            result = ContractEvaluationResult(
                contract_id=case_id,
                contract_name=test_case.contract_name,
                contract_type=test_case.contract_type,
                metrics=metrics,
                classification_result=classification_result,
                extraction_results=extraction_results,
                risk_results=risk_results,
                report_result=report_result,
                workflow_result=workflow_result,
                overall_score=overall_score,
                evaluation_time_ms=(time.time() - start_time) * 1000,
                model_used=self._llm_judge_config.judge_model.value,
                judge_type="llm_judge",
            )

            logger.info(
                f"[{case_id}] 评估完成 | "
                f"overall_score={overall_score:.2f} | "
                f"time={result.evaluation_time_ms:.0f}ms"
            )

            return result

        except Exception as e:
            logger.error(f"[{case_id}] 评估失败: {e}", exc_info=True)
            return ContractEvaluationResult(
                contract_id=case_id,
                contract_name=test_case.contract_name,
                contract_type=test_case.contract_type,
                metrics=ContractEvaluationMetrics(),
                errors=[str(e)],
                evaluation_time_ms=(time.time() - start_time) * 1000,
                model_used=self._llm_judge_config.judge_model.value,
                judge_type="llm_judge",
            )

    async def evaluate_batch(
        self,
        test_suite: ContractTestSuite,
        max_concurrent: int = 5,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[ContractEvaluationResult]:
        """批量评估测试套件。

        Args:
            test_suite: 测试套件
            max_concurrent: 最大并发数
            progress_callback: 进度回调

        Returns:
            评估结果列表
        """
        logger.info(
            f"开始批量评估 | "
            f"total_cases={test_suite.total_cases} | "
            f"max_concurrent={max_concurrent}"
        )

        results = []
        total = test_suite.total_cases

        # 使用信号量控制并发
        import asyncio
        semaphore = asyncio.Semaphore(max_concurrent)

        async def evaluate_with_semaphore(case: ContractTestCase) -> ContractEvaluationResult:
            async with semaphore:
                result = await self.evaluate_single(case)
                if progress_callback:
                    progress_callback(len(results) + 1, total)
                return result

        # 并发执行
        tasks = [
            evaluate_with_semaphore(case)
            for case in test_suite.test_cases
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常结果
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"测试用例 {i} 评估异常: {result}")
                # 创建错误结果
                error_result = ContractEvaluationResult(
                    contract_id=test_suite.test_cases[i].case_id,
                    contract_name=test_suite.test_cases[i].contract_name,
                    contract_type=test_suite.test_cases[i].contract_type,
                    metrics=ContractEvaluationMetrics(),
                    errors=[str(result)],
                    model_used=self._llm_judge_config.judge_model.value,
                    judge_type="llm_judge",
                )
                final_results.append(error_result)
            else:
                final_results.append(result)

        self._evaluation_results = final_results

        logger.info(f"批量评估完成 | success={len(final_results)}/{total}")

        return final_results

    def _evaluate_classification(
        self,
        test_case: ContractTestCase,
        agent_output: dict[str, Any],
    ) -> Any:
        """评估合同分类。"""
        ground_truth = test_case.ground_truth.correct_contract_type
        prediction = agent_output.get("contract_type", "")

        # 使用确定性评估器
        match_result = self._deterministic_judge.evaluate_enum_match(
            ground_truth=ground_truth,
            prediction=prediction,
            valid_values=["procurement", "service", "construction", "lease", "labor", "sales"],
        )

        # 构建结果
        from core.evaluation.contract_evaluator.metrics import ClassificationResult

        return ClassificationResult(
            predicted_class=prediction,
            ground_truth_class=ground_truth,
            is_correct=match_result["exact_match"],
            confidence=agent_output.get("contract_type_confidence", 0.0),
        )

    def _evaluate_clause_extraction(
        self,
        test_case: ContractTestCase,
        agent_output: dict[str, Any],
    ) -> list[Any]:
        """评估条款抽取。"""
        from core.evaluation.contract_evaluator.metrics import ExtractionResult

        ground_truth_clauses = test_case.ground_truth.clauses
        predicted_clauses = agent_output.get("clauses", [])

        results = []

        # 构建标准条款文本集合
        gt_clause_set = {
            (c.clause_type, self._deterministic_judge._normalize_text(c.clause_content))
            for c in ground_truth_clauses
        }

        # 构建预测条款集合
        pred_clause_set = {
            (c.get("clause_type", ""), self._deterministic_judge._normalize_text(c.get("clause_content", "")))
            for c in predicted_clauses
        }

        # 计算重叠度
        overlap = len(gt_clause_set & pred_clause_set)
        total_gt = len(gt_clause_set)
        total_pred = len(pred_clause_set)

        # 对每个标准条款评估
        for gt_clause in ground_truth_clauses:
            gt_text = self._deterministic_judge._normalize_text(gt_clause.clause_content)

            # 查找最匹配的预测条款
            best_match = None
            best_similarity = 0.0

            for pred_clause in predicted_clauses:
                pred_text = self._deterministic_judge._normalize_text(
                    pred_clause.get("clause_content", "")
                )

                # 计算重叠度
                gt_tokens = set(gt_text.split())
                pred_tokens = set(pred_text.split())
                if gt_tokens and pred_tokens:
                    similarity = len(gt_tokens & pred_tokens) / len(gt_tokens | pred_tokens)
                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_match = pred_clause

            results.append(ExtractionResult(
                clause_id=gt_clause.clause_id,
                clause_title=gt_clause.clause_title,
                predicted_content=best_match.get("clause_content", "") if best_match else "",
                ground_truth_content=gt_clause.clause_content,
                is_extracted=best_similarity > 0.5,
                content_overlap=best_similarity,
                semantic_similarity=best_similarity,
            ))

        return results

    def _evaluate_risk_identification(
        self,
        test_case: ContractTestCase,
        agent_output: dict[str, Any],
    ) -> list[Any]:
        """评估风险识别。"""
        from core.evaluation.contract_evaluator.metrics import RiskResult

        ground_truth_risks = test_case.ground_truth.risks
        predicted_risks = agent_output.get("risks", [])

        results = []

        for gt_risk in ground_truth_risks:
            # 查找最匹配的风险
            best_match = None
            best_similarity = 0.0

            gt_desc = self._deterministic_judge._normalize_text(gt_risk.risk_description)

            for pred_risk in predicted_risks:
                pred_desc = self._deterministic_judge._normalize_text(
                    pred_risk.get("risk_description", "")
                )

                # 计算相似度
                gt_tokens = set(gt_desc.split())
                pred_tokens = set(pred_desc.split())
                if gt_tokens and pred_tokens:
                    similarity = len(gt_tokens & pred_tokens) / len(gt_tokens | pred_tokens)
                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_match = pred_risk

            # 评估风险等级
            level_match = False
            if best_match:
                pred_level = self._deterministic_judge._normalize_risk_level(
                    best_match.get("risk_level", "")
                )
                gt_level = self._deterministic_judge._normalize_risk_level(
                    gt_risk.risk_level
                )
                level_match = pred_level == gt_level

            results.append(RiskResult(
                risk_id=gt_risk.risk_id,
                risk_type=gt_risk.risk_type,
                predicted_level=best_match.get("risk_level", "") if best_match else "",
                ground_truth_level=gt_risk.risk_level,
                is_identified=best_similarity > 0.3,
                level_correct=level_match,
                related_clause=gt_risk.related_clause_id,
                predicted_description=best_match.get("risk_description", "") if best_match else "",
                ground_truth_description=gt_risk.risk_description,
            ))

        return results

    async def _evaluate_report_quality(
        self,
        test_case: ContractTestCase,
        agent_output: dict[str, Any],
    ) -> Any:
        """评估报告质量。"""
        from core.evaluation.contract_evaluator.metrics import ReportResult

        ground_truth_summary = test_case.ground_truth.expected_report_summary
        predicted_report = agent_output.get("review_report", {})
        predicted_summary = predicted_report.get("review_summary", "")

        # 使用 LLM Judge 评估
        judge_response = await self._llm_judge.judge_report_quality(
            ground_truth=ground_truth_summary,
            prediction=predicted_summary,
            contract_text=test_case.contract_text,
            use_cache=self._llm_judge_config.use_cached_judgments,
        )

        # 评估引用准确性
        citation_metrics = self._evaluate_citation_accuracy(
            test_case=test_case,
            agent_output=agent_output,
        )

        return ReportResult(
            quality_score=judge_response.overall_score / 5.0,  # 转换为 0-1
            rouge_l=self._calculate_rouge_l(
                ground_truth_summary,
                predicted_summary
            ),
            semantic_similarity=judge_response.dimension_scores.get("completeness", 3.0) / 5.0,
            completeness_score=judge_response.dimension_scores.get("completeness", 3.0) / 5.0,
            accuracy_score=judge_response.dimension_scores.get("citation", 3.0) / 5.0,
            suggestion_relevance=judge_response.dimension_scores.get("suggestion", 3.0) / 5.0,
            citation_accuracy=citation_metrics["accuracy"],
            reasoning_quality=judge_response.dimension_scores.get("reasoning", 3.0) / 5.0,
            issues=judge_response.issues_found,
        )

    def _evaluate_workflow(
        self,
        test_case: ContractTestCase,
        agent_output: dict[str, Any],
    ) -> Any:
        """评估工作流。"""
        from core.evaluation.contract_evaluator.metrics import WorkflowResult

        expected_tools = set(test_case.expected_tools)
        completed_tools = set(agent_output.get("completed_tools", []))
        tool_execution_order = agent_output.get("tool_execution_order", [])

        # 评估工具调用准确性
        tool_accuracy = len(completed_tools & expected_tools) / len(expected_tools) if expected_tools else 1.0

        # 评估工具调用完整性
        required_tools = {"parse_contract", "search_laws", "extract_clauses", "analyze_risk"}
        tool_completeness = len(completed_tools & required_tools) / len(required_tools)

        # 评估 Human Review 触发
        expected_hr = test_case.expected_human_review
        actual_hr = agent_output.get("need_human_review", False)
        hr_trigger_match = expected_hr == actual_hr

        return WorkflowResult(
            success=agent_output.get("outcome") == "finish",
            completed_tools=list(completed_tools),
            tool_execution_order=tool_execution_order,
            iterations=agent_output.get("react_iterations", 0),
            reflection_triggered=agent_output.get("reflection_result") is not None,
            human_review_triggered=actual_hr,
            tool_errors=agent_output.get("errors", []),
            total_time_ms=agent_output.get("total_time_ms", 0.0),
        )

    def _evaluate_citation_accuracy(
        self,
        test_case: ContractTestCase,
        agent_output: dict[str, Any],
    ) -> dict[str, float]:
        """评估引用准确性。"""
        citations = agent_output.get("citations", [])
        gt_risks = test_case.ground_truth.risks

        if not citations:
            return {"accuracy": 0.0, "recall": 0.0, "precision": 0.0}

        # 构建标准风险 ID 集合
        gt_risk_ids = {r.risk_id for r in gt_risks}

        # 构建引用风险 ID 集合
        cited_risk_ids = {c.get("risk_id") for c in citations if c.get("risk_id")}

        # 计算召回率（引用的风险在标准答案中）
        recall = len(cited_risk_ids & gt_risk_ids) / len(gt_risk_ids) if gt_risk_ids else 1.0

        # 计算精确率（引用的风险是准确的）
        precision = len(cited_risk_ids & gt_risk_ids) / len(cited_risk_ids) if cited_risk_ids else 0.0

        # 计算准确率
        accuracy = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        return {
            "accuracy": accuracy,
            "recall": recall,
            "precision": precision,
        }

    def _calculate_metrics(
        self,
        classification_result: Any,
        extraction_results: list[Any],
        risk_results: list[Any],
        report_result: Any,
        workflow_result: Any,
        test_case: ContractTestCase,
    ) -> ContractEvaluationMetrics:
        """计算评估指标。"""
        metrics = ContractEvaluationMetrics()

        # ===== 合同分类指标 =====
        if classification_result:
            metrics.contract_classification_accuracy = 1.0 if classification_result.is_correct else 0.0

        # ===== 条款抽取指标 =====
        if extraction_results:
            extracted = [r for r in extraction_results if r.is_extracted]
            metrics.clause_extraction_recall = len(extracted) / len(extraction_results) if extraction_results else 0.0
            avg_overlap = sum(r.content_overlap for r in extraction_results) / len(extraction_results) if extraction_results else 0.0
            metrics.clause_extraction_precision = avg_overlap
            metrics.clause_extraction_f1 = 2 * metrics.clause_extraction_precision * metrics.clause_extraction_recall / (metrics.clause_extraction_precision + metrics.clause_extraction_recall) if (metrics.clause_extraction_precision + metrics.clause_extraction_recall) > 0 else 0.0

        # ===== 风险识别指标 =====
        if risk_results:
            identified = [r for r in risk_results if r.is_identified]
            metrics.risk_identification_recall = len(identified) / len(risk_results) if risk_results else 0.0
            level_correct = [r for r in risk_results if r.level_correct]
            metrics.risk_level_accuracy = len(level_correct) / len(risk_results) if risk_results else 0.0
            avg_precision = sum(1.0 if r.is_identified else r.content_overlap for r in risk_results) / len(risk_results) if risk_results else 0.0
            metrics.risk_identification_precision = avg_precision
            metrics.risk_identification_f1 = 2 * metrics.risk_identification_precision * metrics.risk_identification_recall / (metrics.risk_identification_precision + metrics.risk_identification_recall) if (metrics.risk_identification_precision + metrics.risk_identification_recall) > 0 else 0.0

        # ===== 报告质量指标 =====
        if report_result:
            metrics.report_quality_score = report_result.quality_score
            metrics.report_rouge_l = report_result.rouge_l
            metrics.report_semantic_similarity = report_result.semantic_similarity
            metrics.suggestion_quality_score = report_result.suggestion_relevance
            metrics.citation_accuracy = report_result.citation_accuracy

        # ===== 工作流指标 =====
        if workflow_result:
            metrics.workflow_success_rate = 1.0 if workflow_result.success else 0.0
            metrics.average_iterations = workflow_result.iterations
            metrics.human_review_trigger_rate = 1.0 if workflow_result.human_review_triggered else 0.0

        return metrics

    def _calculate_rouge_l(self, reference: str, hypothesis: str) -> float:
        """计算 ROUGE-L。"""
        if not reference or not hypothesis:
            return 0.0

        ref_tokens = reference.split()
        hyp_tokens = hypothesis.split()

        # LCS 长度
        m, n = len(ref_tokens), len(hyp_tokens)
        dp = [[0] * (n + 1) for _ in range(m + 1)]

        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if ref_tokens[i - 1] == hyp_tokens[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1] + 1
                else:
                    dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

        lcs_length = dp[m][n]

        # ROUGE-L = LCS / max(len(ref), len(hyp))
        return lcs_length / max(m, n) if max(m, n) > 0 else 0.0

    def get_summary_statistics(self) -> dict[str, Any]:
        """获取汇总统计信息。"""
        if not self._evaluation_results:
            return {}

        results = self._evaluation_results
        total = len(results)

        # 计算各维度平均分
        avg_scores = {
            "overall": sum(r.overall_score for r in results) / total,
            "classification": sum(r.metrics.contract_classification_accuracy for r in results) / total,
            "clause_extraction": sum(r.metrics.clause_extraction_f1 for r in results) / total,
            "risk_identification": sum(r.metrics.risk_identification_f1 for r in results) / total,
            "report_quality": sum(r.metrics.report_quality_score for r in results) / total,
            "workflow": sum(r.metrics.workflow_success_rate for r in results) / total,
        }

        # 通过率
        pass_rate = sum(1 for r in results if r.overall_score >= 70) / total

        return {
            "total_cases": total,
            "average_scores": avg_scores,
            "pass_rate": pass_rate,
            "min_score": min(r.overall_score for r in results),
            "max_score": max(r.overall_score for r in results),
        }
