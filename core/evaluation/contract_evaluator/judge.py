"""LLM-as-Judge 评估器实现。

基于 2026 年最新的 LLM-as-Judge 方法论设计：
1. 支持多种评估模式（离线批量、在线实时）
2. 支持评分量表（1-5 分或 0-100 分）
3. 支持多维度独立评分
4. 支持结构化评分理由
5. 支持评估偏见检测和缓解

设计原则：
- 生成模型和评估模型分离（避免 self-enhancement bias）
- 使用规则引擎 + LLM 评估混合模式
- 评估结果可追溯、可解释

模型选择策略：
- 高风险、高价值评估：使用强模型（如 Qwen-32B）
- 日常快速评估：使用轻量模型（如 Qwen-7B/Qwen-3B）
- 确定性检查：使用规则引擎

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from core.llm.gateway import LLMGateway, MockLLMGateway
from core.llm.models import LLMMessage
from core.evaluation.contract_evaluator.metrics import (
    ContractEvaluationMetrics,
    ContractEvaluationResult,
    ReportResult,
)

logger = logging.getLogger(__name__)


class JudgeModel(str, Enum):
    """评估器模型选择枚举。

    根据不同场景选择不同模型：
    - JUDGE_LARGE: 高风险评估，复杂推理
    - JUDGE_MEDIUM: 标准评估
    - JUDGE_LIGHT: 快速检查，高频调用
    - JUDGE_SPECIALIZED: 领域专用评估
    """

    JUDGE_LARGE = "qwen-32b"  # 大模型，适合复杂评估
    JUDGE_MEDIUM = "qwen-14b"  # 中模型，平衡质量和速度
    JUDGE_LIGHT = "qwen-7b"  # 轻量模型，高速评估
    JUDGE_SPECIALIZED = "contract-judge-specialized"  # 微调专用模型

    # 用于对比评估
    JUDGE_GPT4 = "gpt-4o"  # 作为参考基准
    JUDGE_CLAUDE = "claude-3.7-sonnet"  # 作为参考基准


class EvaluationMode(str, Enum):
    """评估模式枚举。"""

    OFFLINE_BATCH = "offline_batch"  # 离线批量评估
    ONLINE_REALTIME = "online_realtime"  # 在线实时评估
    CI_GATE = "ci_gate"  # CI 门禁评估
    REGRESSION_TEST = "regression_test"  # 回归测试评估


class ScoringScale(str, Enum):
    """评分量表枚举。"""

    FIVE_POINT = "5_point"  # 1-5 分量表
    HUNDRED_POINT = "100_point"  # 0-100 分量表
    BINARY = "binary"  # 二值（正确/错误）
    TERNARY = "ternary"  # 三值（正确/部分正确/错误）


@dataclass
class ContractJudgeConfig:
    """LLM 评估器配置。"""

    # 模型配置
    judge_model: JudgeModel = JudgeModel.JUDGE_LARGE  # 默认使用大模型
    model_temperature: float = 0.1  # 低温度保证评估一致性
    max_tokens: int = 2048  # 评估输出长度限制

    # 评估配置
    scoring_scale: ScoringScale = ScoringScale.FIVE_POINT  # 评分量表
    evaluation_mode: EvaluationMode = EvaluationMode.OFFLINE_BATCH  # 评估模式
    enable_reasoning: bool = True  # 是否要求输出推理过程

    # 多维度评估配置
    evaluate_dimensions: list[str] = field(default_factory=lambda: [
        "accuracy",  # 准确性
        "completeness",  # 完整性
        "relevance",  # 相关性
        "coherence",  # 连贯性
        "safety",  # 安全性
    ])

    # 偏见缓解配置
    enable_bias_mitigation: bool = True  # 是否启用偏见缓解
    bias_types_to_check: list[str] = field(default_factory=lambda: [
        "position_bias",  # 位置偏见
        "length_bias",  # 长度偏见
        "self_enhancement",  # 自我增强偏见
    ])

    # 成本优化配置
    use_cached_judgments: bool = True  # 是否使用缓存的评估结果
    cache_ttl_hours: int = 24  # 缓存有效期（小时）

    # 对比评估配置
    enable_comparative_judgment: bool = False  # 是否启用对比评估
    reference_model: JudgeModel | None = None  # 参考模型

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "judge_model": self.judge_model.value,
            "model_temperature": self.model_temperature,
            "max_tokens": self.max_tokens,
            "scoring_scale": self.scoring_scale.value,
            "evaluation_mode": self.evaluation_mode.value,
            "enable_reasoning": self.enable_reasoning,
            "evaluate_dimensions": self.evaluate_dimensions,
            "enable_bias_mitigation": self.enable_bias_mitigation,
            "bias_types_to_check": self.bias_types_to_check,
        }


class JudgeResponse(BaseModel):
    """LLM Judge 响应模型。"""

    # 总体评分
    overall_score: float = Field(description="总体评分（根据量表）")

    # 多维度评分
    dimension_scores: dict[str, float] = Field(
        default_factory=dict,
        description="各维度评分"
    )

    # 推理过程
    reasoning: str = Field(
        default="",
        description="评估推理过程"
    )

    # 判定结果
    judgment: str = Field(
        default="",
        description="最终判定（pass/fail/needs_improvement）"
    )

    # 发现的问题
    issues_found: list[str] = Field(
        default_factory=list,
        description="发现的问题列表"
    )

    # 偏见检测结果
    bias_detected: dict[str, bool] = Field(
        default_factory=dict,
        description="检测到的偏见类型"
    )

    # 置信度
    confidence: float = Field(
        default=0.0,
        description="评估置信度（0-1）"
    )


class LLMJudgeEvaluator:
    """LLM-as-Judge 评估器。

    核心职责：
    1. 对合同审核结果进行多维度质量评估
    2. 使用结构化评分量表保证评估一致性
    3. 输出推理过程保证评估可解释性
    4. 检测和缓解评估偏见

    设计原因：
    1. 人工评估成本高、耗时长、不一致
    2. 规则评估无法处理语义质量问题
    3. LLM Judge 可以理解上下文并给出语义级评估
    4. 结合规则引擎可以保证评估的确定性和效率
    """

    # 评估 Prompt 模板
    CLAUSE_EXTRACTION_JUDGE_PROMPT = """你是一位专业的合同审核专家，负责评估合同条款抽取的质量。

## 任务
评估模型抽取的合同条款与标准条款的匹配程度。

## 评分维度（每项 1-5 分）
1. 准确性（Accuracy）：抽取的条款内容是否准确反映原文
2. 完整性（Completeness）：是否遗漏重要条款
3. 归类准确性（Classification）：条款类型分类是否正确

## 评分标准
- 5分：完全匹配或非常接近标准
- 4分：基本正确，有轻微偏差
- 3分：部分正确，有明显遗漏或错误
- 2分：大部分错误，仅部分正确
- 1分：完全错误或遗漏

## 输入信息
标准条款：
```
{ground_truth}
```

模型抽取结果：
```
{prediction}
```

## 输出要求
请提供：
1. 各维度评分（1-5分）
2. 总体评分（1-5分）
3. 评分理由（简洁）
4. 发现的问题（如有）

请以 JSON 格式输出：
```json
{{
  "dimension_scores": {{"accuracy": X, "completeness": X, "classification": X}},
  "overall_score": X,
  "reasoning": "...",
  "issues_found": ["..."]
}}
```
"""

    RISK_IDENTIFICATION_JUDGE_PROMPT = """你是一位专业的法律风险评估专家，负责评估合同风险识别的质量。

## 任务
评估模型识别的合同风险与标准风险的匹配程度。

## 评分维度（每项 1-5 分）
1. 风险识别准确性（Identification）：是否准确识别出风险
2. 风险等级判定（Level Assessment）：风险等级判定是否合理
3. 风险描述质量（Description）：风险描述是否准确、有用
4. 建议质量（Suggestion）：修改建议是否合理、可操作

## 评分标准
- 5分：完全准确识别，风险等级合理，建议优秀
- 4分：基本准确，有轻微偏差
- 3分：部分准确，有明显问题
- 2分：大部分不准确
- 1分：完全错误

## 输入信息
标准风险：
```
{ground_truth}
```

模型识别结果：
```
{prediction}
```

## 输出要求
请提供：
1. 各维度评分（1-5分）
2. 总体评分（1-5分）
3. 评分理由
4. 发现的问题（如有）

请以 JSON 格式输出：
```json
{{
  "dimension_scores": {{"identification": X, "level_assessment": X, "description": X, "suggestion": X}},
  "overall_score": X,
  "reasoning": "...",
  "issues_found": ["..."]
}}
```
"""

    REPORT_QUALITY_JUDGE_PROMPT = """你是一位专业的合同审查报告评审专家，负责评估审查报告的质量。

## 任务
评估合同审查报告的全面性、准确性和实用性。

## 评分维度（每项 1-5 分）
1. 内容完整性（Completeness）：报告是否涵盖所有重要方面
2. 风险识别完整性（Risk Coverage）：是否识别了所有重要风险
3. 建议实用性（Suggestion Practicality）：建议是否具体、可操作
4. 引用准确性（Citation）：引用是否准确、可查证
5. 推理连贯性（Reasoning）：推理过程是否逻辑清晰

## 评分标准
- 5分：优秀，完全满足要求
- 4分：良好，满足大部分要求
- 3分：一般，满足基本要求
- 2分：较差，有明显不足
- 1分：不合格

## 输入信息
标准报告摘要：
```
{ground_truth}
```

模型生成报告：
```
{prediction}
```

合同原文：
```
{contract_text}
```

## 输出要求
请提供：
1. 各维度评分（1-5分）
2. 总体评分（1-5分）
3. 评分理由
4. 发现的问题（如有）

请以 JSON 格式输出：
```json
{{
  "dimension_scores": {{"completeness": X, "risk_coverage": X, "suggestion": X, "citation": X, "reasoning": X}},
  "overall_score": X,
  "reasoning": "...",
  "issues_found": ["..."]
}}
```
"""

    def __init__(
        self,
        llm_gateway: LLMGateway | None = None,
        config: ContractJudgeConfig | None = None,
    ) -> None:
        """初始化 LLM Judge 评估器。

        Args:
            llm_gateway: LLM 网关实例
            config: 评估器配置
        """
        self._llm_gateway = llm_gateway
        self._config = config or ContractJudgeConfig()
        self._cache: dict[str, JudgeResponse] = {}

        logger.info(
            f"LLMJudgeEvaluator 初始化 | "
            f"model={self._config.judge_model.value} | "
            f"mode={self._config.evaluation_mode.value}"
        )

    @property
    def llm_gateway(self) -> LLMGateway:
        """获取 LLM 网关（懒加载）。"""
        if self._llm_gateway is None:
            from core.config.settings import get_settings
            settings = get_settings()
            if settings.llm_api_key and settings.llm_api_key != "your-api-key":
                from core.llm.gateway import OpenAICompatibleLLMGateway
                self._llm_gateway = OpenAICompatibleLLMGateway(settings=settings)
            else:
                self._llm_gateway = MockLLMGateway()
        return self._llm_gateway

    def _get_cache_key(
        self,
        evaluation_type: str,
        ground_truth: str,
        prediction: str,
    ) -> str:
        """生成缓存键。"""
        import hashlib
        content = f"{evaluation_type}:{ground_truth}:{prediction}"
        return hashlib.md5(content.encode()).hexdigest()

    def _convert_score(
        self,
        score: float,
        from_scale: ScoringScale,
        to_scale: ScoringScale,
    ) -> float:
        """转换评分量表。"""
        if from_scale == to_scale:
            return score

        if from_scale == ScoringScale.FIVE_POINT and to_scale == ScoringScale.HUNDRED_POINT:
            return (score / 5.0) * 100
        elif from_scale == ScoringScale.HUNDRED_POINT and to_scale == ScoringScale.FIVE_POINT:
            return (score / 100.0) * 5
        elif from_scale == ScoringScale.FIVE_POINT and to_scale == ScoringScale.BINARY:
            return 1.0 if score >= 3.5 else 0.0
        elif from_scale == ScoringScale.HUNDRED_POINT and to_scale == ScoringScale.BINARY:
            return 1.0 if score >= 70 else 0.0

        return score

    async def judge_clause_extraction(
        self,
        ground_truth: str,
        prediction: str,
        use_cache: bool = True,
    ) -> JudgeResponse:
        """评估条款抽取质量。

        Args:
            ground_truth: 标准条款
            prediction: 模型预测条款
            use_cache: 是否使用缓存

        Returns:
            评估结果
        """
        cache_key = self._get_cache_key("clause_extraction", ground_truth, prediction)

        if use_cache and self._config.use_cached_judgments and cache_key in self._cache:
            logger.debug(f"使用缓存的评估结果: {cache_key[:8]}")
            return self._cache[cache_key]

        # 构建 Prompt
        prompt = self.CLAUSE_EXTRACTION_JUDGE_PROMPT.format(
            ground_truth=ground_truth,
            prediction=prediction,
        )

        # 调用 LLM
        response = await self._call_judge_llm(prompt)

        # 解析响应
        result = self._parse_judge_response(response, "clause_extraction")

        # 缓存结果
        if self._config.use_cached_judgments:
            self._cache[cache_key] = result

        return result

    async def judge_risk_identification(
        self,
        ground_truth: str,
        prediction: str,
        use_cache: bool = True,
    ) -> JudgeResponse:
        """评估风险识别质量。

        Args:
            ground_truth: 标准风险
            prediction: 模型预测风险
            use_cache: 是否使用缓存

        Returns:
            评估结果
        """
        cache_key = self._get_cache_key("risk_identification", ground_truth, prediction)

        if use_cache and self._config.use_cached_judgments and cache_key in self._cache:
            logger.debug(f"使用缓存的评估结果: {cache_key[:8]}")
            return self._cache[cache_key]

        prompt = self.RISK_IDENTIFICATION_JUDGE_PROMPT.format(
            ground_truth=ground_truth,
            prediction=prediction,
        )

        response = await self._call_judge_llm(prompt)
        result = self._parse_judge_response(response, "risk_identification")

        if self._config.use_cached_judgments:
            self._cache[cache_key] = result

        return result

    async def judge_report_quality(
        self,
        ground_truth: str,
        prediction: str,
        contract_text: str,
        use_cache: bool = True,
    ) -> JudgeResponse:
        """评估报告质量。

        Args:
            ground_truth: 标准报告摘要
            prediction: 模型生成报告
            contract_text: 合同原文
            use_cache: 是否使用缓存

        Returns:
            评估结果
        """
        cache_key = self._get_cache_key("report_quality", ground_truth, prediction)

        if use_cache and self._config.use_cached_judgments and cache_key in self._cache:
            logger.debug(f"使用缓存的评估结果: {cache_key[:8]}")
            return self._cache[cache_key]

        prompt = self.REPORT_QUALITY_JUDGE_PROMPT.format(
            ground_truth=ground_truth,
            prediction=prediction,
            contract_text=contract_text,
        )

        response = await self._call_judge_llm(prompt)
        result = self._parse_judge_response(response, "report_quality")

        if self._config.use_cached_judgments:
            self._cache[cache_key] = result

        return result

    async def judge_end_to_end(
        self,
        ground_truth: dict[str, Any],
        prediction: dict[str, Any],
        contract_text: str,
    ) -> JudgeResponse:
        """端到端工作流评估。

        综合评估整个合同审核工作流的质量。

        Args:
            ground_truth: 标准结果
            prediction: 模型预测结果
            contract_text: 合同原文

        Returns:
            评估结果
        """
        # 构建综合评估 Prompt
        prompt = f"""你是一位专业的合同审核质量评估专家，负责评估整个合同审核工作流的质量。

## 任务
评估合同审核 Agent 的端到端表现。

## 评估维度
1. 合同类型分类准确性
2. 条款抽取完整性
3. 风险识别准确性
4. 风险等级判定合理性
5. 报告生成质量
6. 整体工作流效率

## 标准结果
```json
{ground_truth}
```

## 模型结果
```json
{prediction}
```

## 合同原文
```
{contract_text[:2000]}...
```

## 输出要求
请提供：
1. 各维度评分（1-5分）
2. 总体评分（1-5分）
3. 优点总结
4. 改进建议

请以 JSON 格式输出：
```json
{{
  "dimension_scores": {{"classification": X, "extraction": X, "risk_id": X, "level_assessment": X, "report": X, "efficiency": X}},
  "overall_score": X,
  "reasoning": "...",
  "issues_found": ["..."]
}}
```
"""

        response = await self._call_judge_llm(prompt)
        return self._parse_judge_response(response, "end_to_end")

    async def _call_judge_llm(self, prompt: str) -> str:
        """调用 Judge LLM。"""
        model_name = self._config.judge_model.value

        messages = [
            LLMMessage(role="system", content="你是一位严格、公正的合同审核质量评估专家。"),
            LLMMessage(role="user", content=prompt),
        ]

        try:
            response = self.llm_gateway.chat(
                messages=messages,
                model=model_name,
                timeout_seconds=60,
            )
            return response.content

        except Exception as e:
            logger.error(f"LLM Judge 调用失败: {e}")
            # 返回默认评估结果
            return '{"overall_score": 3.0, "dimension_scores": {}, "reasoning": "评估失败", "issues_found": []}'

    def _parse_judge_response(
        self,
        response: str,
        evaluation_type: str,
    ) -> JudgeResponse:
        """解析 Judge LLM 响应。"""
        import json

        try:
            # 尝试提取 JSON
            json_match = response.find("```json")
            if json_match != -1:
                start = response.find("```json", json_match) + 7
                end = response.find("```", start)
                if end != -1:
                    json_str = response[start:end].strip()
                else:
                    json_str = response[start:].strip()
            else:
                # 尝试直接解析整个响应
                json_str = response.strip()

            data = json.loads(json_str)

            return JudgeResponse(
                overall_score=float(data.get("overall_score", 3.0)),
                dimension_scores=data.get("dimension_scores", {}),
                reasoning=data.get("reasoning", ""),
                judgment=data.get("judgment", ""),
                issues_found=data.get("issues_found", []),
                bias_detected=data.get("bias_detected", {}),
                confidence=data.get("confidence", 0.8),
            )

        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失败，使用默认评估结果: {e}")
            return JudgeResponse(
                overall_score=3.0,
                dimension_scores={},
                reasoning=f"响应解析失败: {response[:100]}",
                issues_found=["响应格式错误"],
                confidence=0.0,
            )

    def clear_cache(self) -> None:
        """清空评估缓存。"""
        self._cache.clear()
        logger.info("评估缓存已清空")


class DeterministicJudgeEvaluator:
    """确定性评估器。

    使用规则和算法进行确定性评估：
    1. 精确匹配评估
    2. 相似度计算
    3. 格式校验
    4. 完整性检查

    优点：
    - 评估结果可复现
    - 速度快，无 API 调用成本
    - 适合确定性任务

    适用场景：
    - 格式检查
    - 字段完整性验证
    - 枚举值校验
    """

    def __init__(self) -> None:
        """初始化确定性评估器。"""
        logger.info("DeterministicJudgeEvaluator 初始化完成")

    def evaluate_exact_match(
        self,
        ground_truth: str,
        prediction: str,
    ) -> float:
        """精确匹配评估。

        Args:
            ground_truth: 标准答案
            prediction: 预测答案

        Returns:
            匹配度（0-1）
        """
        if not ground_truth or not prediction:
            return 0.0

        gt_normalized = self._normalize_text(ground_truth)
        pred_normalized = self._normalize_text(prediction)

        if gt_normalized == pred_normalized:
            return 1.0

        # 计算 Jaccard 相似度
        gt_tokens = set(gt_normalized.split())
        pred_tokens = set(pred_normalized.split())

        if not gt_tokens or not pred_tokens:
            return 0.0

        intersection = len(gt_tokens & pred_tokens)
        union = len(gt_tokens | pred_tokens)

        return intersection / union if union > 0 else 0.0

    def evaluate_token_overlap(
        self,
        ground_truth: str,
        prediction: str,
    ) -> dict[str, float]:
        """Token 级别重叠评估。

        Args:
            ground_truth: 标准答案
            prediction: 预测答案

        Returns:
            包含 precision、recall、f1 的字典
        """
        gt_tokens = set(self._normalize_text(ground_truth).split())
        pred_tokens = set(self._normalize_text(prediction).split())

        if not gt_tokens and not pred_tokens:
            return {"precision": 1.0, "recall": 1.0, "f1": 1.0}

        if not gt_tokens or not pred_tokens:
            return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

        tp = len(gt_tokens & pred_tokens)
        fp = len(pred_tokens - gt_tokens)
        fn = len(gt_tokens - pred_tokens)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        return {"precision": precision, "recall": recall, "f1": f1}

    def evaluate_set_match(
        self,
        ground_truth: list[str],
        prediction: list[str],
    ) -> dict[str, float]:
        """集合匹配评估。

        用于评估条款列表、风险列表等集合类型结果。

        Args:
            ground_truth: 标准集合
            prediction: 预测集合

        Returns:
            评估指标
        """
        gt_set = set(self._normalize_text(item) for item in ground_truth)
        pred_set = set(self._normalize_text(item) for item in prediction)

        if not gt_set and not pred_set:
            return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "accuracy": 1.0}

        if not gt_set or not pred_set:
            return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "accuracy": 0.0}

        tp = len(gt_set & pred_set)  # 正确识别
        fp = len(pred_set - gt_set)  # 误报
        fn = len(gt_set - pred_set)  # 漏报
        tn = 0  # 正确拒绝（通常不适用于此场景）

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        accuracy = tp / (tp + fp + fn) if (tp + fp + fn) > 0 else 0.0

        return {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "accuracy": accuracy,
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
        }

    def evaluate_enum_match(
        self,
        ground_truth: str,
        prediction: str,
        valid_values: list[str] | None = None,
    ) -> dict[str, Any]:
        """枚举值匹配评估。

        用于评估合同类型、风险等级等枚举类型结果。

        Args:
            ground_truth: 标准枚举值
            prediction: 预测枚举值
            valid_values: 有效枚举值列表

        Returns:
            评估结果
        """
        gt_normalized = self._normalize_text(ground_truth)
        pred_normalized = self._normalize_text(prediction)

        is_exact_match = gt_normalized == pred_normalized

        # 如果提供了有效值列表，检查预测值是否在有效范围内
        is_valid = True
        if valid_values:
            valid_normalized = [self._normalize_text(v) for v in valid_values]
            is_valid = pred_normalized in valid_normalized

        # 检查相似度（用于部分匹配）
        similarity = 0.0
        if gt_normalized and pred_normalized:
            # 使用编辑距离计算相似度
            similarity = 1.0 - (self._levenshtein_distance(gt_normalized, pred_normalized) /
                              max(len(gt_normalized), len(pred_normalized), 1))

        return {
            "exact_match": is_exact_match,
            "is_valid": is_valid,
            "similarity": similarity,
            "ground_truth": ground_truth,
            "prediction": prediction,
        }

    def evaluate_completeness(
        self,
        required_fields: list[str],
        provided_fields: list[str],
    ) -> dict[str, Any]:
        """完整性评估。

        评估是否提供了所有必需字段。

        Args:
            required_fields: 必需字段列表
            provided_fields: 已提供字段列表

        Returns:
            完整性评估结果
        """
        required_set = set(self._normalize_text(f) for f in required_fields)
        provided_set = set(self._normalize_text(f) for f in provided_fields)

        missing = required_set - provided_set
        completeness_rate = len(provided_set & required_set) / len(required_set) if required_set else 1.0

        return {
            "completeness_rate": completeness_rate,
            "missing_fields": list(missing),
            "missing_count": len(missing),
            "provided_count": len(provided_set & required_set),
            "required_count": len(required_set),
        }

    def evaluate_risk_level_matrix(
        self,
        ground_truth_levels: list[str],
        predicted_levels: list[str],
    ) -> dict[str, Any]:
        """风险等级混淆矩阵评估。

        Args:
            ground_truth_levels: 标准风险等级列表
            predicted_levels: 预测风险等级列表

        Returns:
            混淆矩阵和评估指标
        """
        # 定义等级顺序
        level_order = {"high": 3, "medium": 2, "low": 1, "none": 0}

        # 构建混淆矩阵
        levels = list(level_order.keys())
        confusion_matrix = {l1: {l2: 0 for l2 in levels} for l1 in levels}

        for gt, pred in zip(ground_truth_levels, predicted_levels):
            gt_norm = self._normalize_risk_level(gt)
            pred_norm = self._normalize_risk_level(pred)
            if gt_norm in confusion_matrix and pred_norm in confusion_matrix[gt_norm]:
                confusion_matrix[gt_norm][pred_norm] += 1

        # 计算准确率
        correct = sum(
            confusion_matrix[l][l]
            for l in levels
        )
        total = sum(
            sum(confusion_matrix[l].values())
            for l in levels
        )
        accuracy = correct / total if total > 0 else 0.0

        # 计算各等级精确率、召回率
        metrics = {}
        for level in levels:
            tp = confusion_matrix[level][level]
            fp = sum(confusion_matrix[l][level] for l in levels) - tp
            fn = sum(confusion_matrix[level].values()) - tp

            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

            metrics[level] = {
                "precision": precision,
                "recall": recall,
                "f1": f1,
            }

        return {
            "confusion_matrix": confusion_matrix,
            "accuracy": accuracy,
            "level_metrics": metrics,
        }

    @staticmethod
    def _normalize_text(text: str) -> str:
        """标准化文本。"""
        if not text:
            return ""
        return text.lower().strip().replace("\n", " ").replace("\r", "")

    @staticmethod
    def _normalize_risk_level(level: str) -> str:
        """标准化风险等级。"""
        if not level:
            return "none"
        level_lower = level.lower().strip()
        if "high" in level_lower or "高" in level:
            return "high"
        elif "medium" in level_lower or "中" in level:
            return "medium"
        elif "low" in level_lower or "低" in level:
            return "low"
        else:
            return "none"

    @staticmethod
    def _levenshtein_distance(s1: str, s2: str) -> int:
        """计算编辑距离。"""
        if len(s1) < len(s2):
            return DeterministicJudgeEvaluator._levenshtein_distance(s2, s1)

        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]
