"""
置信度自适应处理策略

当 LLM 返回低置信度时，系统会自动选择最优处理策略：

1. 澄清策略 (Clarification) - 主动向用户提问
2. 多意图候选策略 (Multi-Intent) - 返回多个可能意图
3. 默认路由策略 (Default Route) - 选择最可能意图继续
4. 降级策略 (Fallback) - 回退到规则检测
5. 增量信息策略 (Incremental) - 请求更多上下文

核心原则：
- 宁可多问一次，也不要错误执行
- 高风险场景（合同/安全）低置信度必须澄清
- 低风险场景可以尝试执行

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# 置信度阈值配置
# ============================================================================

@dataclass
class ConfidenceThresholds:
    """
    置信度阈值配置

    不同业务域可以设置不同的阈值：
    - 高风险场景（合同、安全）需要更高的置信度
    - 低风险场景（RAG 问答）可以接受较低置信度
    """
    # 全局阈值
    EXECUTE_IMMEDIATELY: float = 0.80   # >= 此值立即执行
    EXECUTE_WITH_CAUTION: float = 0.60  # >= 此值可执行但需记录
    NEEDS_CLARIFICATION: float = 0.40   # < 此值必须澄清
    NEEDS_FALLBACK: float = 0.25        # < 此值降级到规则

    # 业务域特定阈值
    HIGH_RISK_DOMAINS: list[str] = field(default_factory=lambda: [
        "contract", "safety", "analytics"
    ])

    def get_threshold_for_domain(self, domain: str, risk_level: str = "medium") -> float:
        """
        获取特定业务域的阈值

        高风险域需要更高置信度
        """
        if domain in self.HIGH_RISK_DOMAINS or risk_level == "high":
            return max(self.EXECUTE_IMMEDIATELY, 0.85)
        return self.EXECUTE_IMMEDIATELY


# 全局默认阈值
DEFAULT_THRESHOLDS = ConfidenceThresholds()


# ============================================================================
# 处理策略枚举
# ============================================================================

class HandlingStrategy(str, Enum):
    """置信度处理策略"""
    EXECUTE_IMMEDIATELY = "execute_immediately"     # 立即执行
    EXECUTE_WITH_CAUTION = "execute_with_caution"   # 谨慎执行
    REQUEST_CLARIFICATION = "request_clarification"  # 请求澄清
    MULTI_INTENT_CANDIDATES = "multi_intent_candidates"  # 多意图候选
    FALLBACK_TO_RULES = "fallback_to_rules"         # 降级到规则
    INCREMENTAL_CONTEXT = "incremental_context"     # 请求更多上下文


# ============================================================================
# 处理决策
# ============================================================================

@dataclass
class HandlingDecision:
    """
    置信度处理决策

    包含：
    - 选定的策略
    - 置信度分数
    - 执行建议
    - 澄清问题（如果需要）
    - 多意图候选（如果有）
    """
    strategy: HandlingStrategy
    confidence: float
    threshold_used: float

    # 执行建议
    can_execute: bool = True
    risk_warning: Optional[str] = None

    # 澄清信息
    clarification_questions: list[str] = field(default_factory=list)
    missing_slots: list[str] = field(default_factory=list)

    # 多意图候选
    alternative_intents: list[dict] = field(default_factory=list)

    # 备选方案
    fallback_reasoning: Optional[str] = None

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "strategy": self.strategy.value,
            "confidence": round(self.confidence, 3),
            "threshold_used": self.threshold_used,
            "can_execute": self.can_execute,
            "risk_warning": self.risk_warning,
            "clarification_questions": self.clarification_questions,
            "missing_slots": self.missing_slots,
            "alternative_intents": self.alternative_intents,
            "fallback_reasoning": self.fallback_reasoning,
        }


# ============================================================================
# 意图候选
# ============================================================================

@dataclass
class IntentCandidate:
    """意图候选"""
    intent_type: str
    confidence: float
    reasoning: str
    slots: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# 置信度处理器
# ============================================================================

class ConfidenceHandler:
    """
    置信度自适应处理器

    核心职责：
    1. 根据置信度选择最优处理策略
    2. 生成合适的澄清问题
    3. 提供多意图候选
    4. 决定是否需要降级

    设计原则：
    - 高风险场景宁可不执行也要澄清
    - 低风险场景可以尝试执行
    - 始终保证用户有选择权
    """

    def __init__(
        self,
        thresholds: Optional[ConfidenceThresholds] = None,
        fallback_detector: Any = None,
    ):
        """
        初始化处理器

        Args:
            thresholds: 置信度阈值配置
            fallback_detector: 降级用的规则检测器
        """
        self.thresholds = thresholds or DEFAULT_THRESHOLDS
        self.fallback_detector = fallback_detector

    def handle(
        self,
        intent_prediction: Any,
        user_query: str,
        business_domain: Optional[str] = None,
        risk_level: str = "medium",
    ) -> HandlingDecision:
        """
        处理意图预测，决定下一步行动

        Args:
            intent_prediction: LLM 返回的意图预测
            user_query: 用户原始查询
            business_domain: 业务域
            risk_level: 风险等级 (low/medium/high)

        Returns:
            HandlingDecision: 处理决策
        """
        confidence = intent_prediction.confidence
        threshold = self.thresholds.get_threshold_for_domain(
            business_domain or "unknown",
            risk_level
        )

        logger.info(
            f"置信度处理: confidence={confidence:.3f}, "
            f"threshold={threshold:.3f}, domain={business_domain}, "
            f"risk={risk_level}"
        )

        # 策略选择
        if confidence >= threshold:
            return self._execute_immediately(
                confidence, threshold, intent_prediction
            )

        elif confidence >= self.thresholds.EXECUTE_WITH_CAUTION:
            return self._execute_with_caution(
                confidence, threshold, intent_prediction, business_domain, risk_level
            )

        elif confidence >= self.thresholds.NEEDS_CLARIFICATION:
            return self._request_clarification(
                confidence, threshold, intent_prediction, user_query
            )

        elif confidence >= self.thresholds.NEEDS_FALLBACK:
            return self._multi_intent_candidates(
                confidence, threshold, intent_prediction
            )

        else:
            return self._fallback_to_rules(
                confidence, threshold, intent_prediction, user_query
            )

    def _execute_immediately(
        self,
        confidence: float,
        threshold: float,
        prediction: Any,
    ) -> HandlingDecision:
        """高置信度：立即执行"""
        logger.info(f"置信度 {confidence:.3f} >= 阈值 {threshold:.3f}，立即执行")

        return HandlingDecision(
            strategy=HandlingStrategy.EXECUTE_IMMEDIATELY,
            confidence=confidence,
            threshold_used=threshold,
            can_execute=True,
        )

    def _execute_with_caution(
        self,
        confidence: float,
        threshold: float,
        prediction: Any,
        domain: Optional[str],
        risk_level: str,
    ) -> HandlingDecision:
        """中等置信度：谨慎执行"""
        logger.info(f"置信度 {confidence:.3f} 在可执行范围，谨慎执行")

        # 高风险域需要警告
        risk_warning = None
        if domain in self.thresholds.HIGH_RISK_DOMAINS or risk_level == "high":
            risk_warning = (
                f"当前置信度为 {confidence:.0%}，低于推荐阈值。"
                "建议谨慎对待分析结果，必要时可要求人工复核。"
            )

        return HandlingDecision(
            strategy=HandlingStrategy.EXECUTE_WITH_CAUTION,
            confidence=confidence,
            threshold_used=threshold,
            can_execute=True,
            risk_warning=risk_warning,
        )

    def _request_clarification(
        self,
        confidence: float,
        threshold: float,
        prediction: Any,
        user_query: str,
    ) -> HandlingDecision:
        """低置信度：请求澄清"""
        logger.info(f"置信度 {confidence:.3f} < {threshold:.3f}，请求澄清")

        # 使用 LLM 已经生成的澄清问题
        clarification_questions = list(prediction.clarification_questions or [])

        # 如果 LLM 没有生成，使用默认问题
        if not clarification_questions:
            clarification_questions = self._generate_default_questions(
                user_query, prediction
            )

        # 识别缺失槽位
        missing_slots = self._identify_missing_slots(prediction)

        return HandlingDecision(
            strategy=HandlingStrategy.REQUEST_CLARIFICATION,
            confidence=confidence,
            threshold_used=threshold,
            can_execute=False,
            clarification_questions=clarification_questions,
            missing_slots=missing_slots,
            risk_warning=(
                f"意图置信度为 {confidence:.0%}，信息不足。"
                "为确保准确回答，请补充以下信息。"
            ),
        )

    def _multi_intent_candidates(
        self,
        confidence: float,
        threshold: float,
        prediction: Any,
    ) -> HandlingDecision:
        """很低置信度：返回多意图候选"""
        logger.info(f"置信度 {confidence:.3f} 很低，返回多意图候选")

        # 生成意图候选列表
        alternatives = self._generate_alternatives(prediction)

        return HandlingDecision(
            strategy=HandlingStrategy.MULTI_INTENT_CANDIDATES,
            confidence=confidence,
            threshold_used=threshold,
            can_execute=False,
            alternative_intents=alternatives,
            clarification_questions=[
                "您的问题可能有多种理解，请选择或确认您的意图：",
                *[f"{i+1}. {alt['reasoning']}" for i, alt in enumerate(alternatives[:3])],
            ],
        )

    def _fallback_to_rules(
        self,
        confidence: float,
        threshold: float,
        prediction: Any,
        user_query: str,
    ) -> HandlingDecision:
        """极低置信度：降级到规则"""
        logger.warning(
            f"置信度 {confidence:.3f} 极低，降级到规则检测"
        )

        rule_result = None
        if self.fallback_detector:
            try:
                rule_result = self.fallback_detector.detect(user_query)
            except Exception as e:
                logger.error(f"规则检测失败: {e}")

        if rule_result and rule_result.confidence > confidence:
            return HandlingDecision(
                strategy=HandlingStrategy.FALLBACK_TO_RULES,
                confidence=rule_result.confidence,
                threshold_used=threshold,
                can_execute=True,
                fallback_reasoning=(
                    f"LLM 置信度 ({confidence:.0%}) 过低，"
                    f"规则检测置信度 ({rule_result.confidence:.0%}) 更高，采用规则结果。"
                ),
            )

        # 规则也不够好，返回澄清
        return HandlingDecision(
            strategy=HandlingStrategy.REQUEST_CLARIFICATION,
            confidence=confidence,
            threshold_used=threshold,
            can_execute=False,
            clarification_questions=[
                "系统无法准确理解您的问题，请尝试：",
                "1. 换一种更具体的表述",
                "2. 提供更多关键词",
                "3. 分步骤提问",
            ],
            fallback_reasoning=(
                "LLM 和规则检测置信度均较低，需要用户澄清。"
            ),
        )

    def _generate_default_questions(
        self,
        user_query: str,
        prediction: Any,
    ) -> list[str]:
        """生成默认澄清问题"""
        questions = []

        intent_type = prediction.intent_type.value if hasattr(prediction.intent_type, 'value') else prediction.intent_type

        if intent_type == "analytics_query":
            if not prediction.extracted_slots.get("metric"):
                questions.append("请问您想查询什么指标？例如：发电量、收入、利润、成本等。")
            if not prediction.extracted_slots.get("time_range"):
                questions.append("请问您想查询哪个时间范围？例如：本月、上季度、本年等。")

        elif intent_type == "contract_review":
            questions.append("请问您想审查什么类型的合同？例如：采购合同、施工合同、服务合同等。")

        elif intent_type == "rag_qa":
            questions.append("请问您想了解哪方面的内容？例如：集团制度、安全规程、设备操作等。")

        if not questions:
            questions.append("请您更具体地描述您的问题，以便系统更好地帮助您。")

        return questions

    def _identify_missing_slots(self, prediction: Any) -> list[str]:
        """识别缺失的槽位"""
        slots = prediction.extracted_slots or {}
        missing = []

        intent_type = prediction.intent_type.value if hasattr(prediction.intent_type, 'value') else prediction.intent_type

        if intent_type == "analytics_query":
            if not slots.get("metric"):
                missing.append("metric")
            if not slots.get("time_range"):
                missing.append("time_range")

        elif intent_type == "contract_review":
            if not slots.get("contract_type"):
                missing.append("contract_type")

        return missing

    def _generate_alternatives(self, prediction: Any) -> list[dict]:
        """生成意图候选列表"""
        intent_type = prediction.intent_type.value if hasattr(prediction.intent_type, 'value') else prediction.intent_type

        # 基于当前预测生成候选
        alternatives = [
            {
                "intent_type": intent_type,
                "confidence": prediction.confidence,
                "reasoning": prediction.reasoning,
            }
        ]

        # 添加其他可能的意图
        if intent_type == "rag_qa":
            alternatives.extend([
                {
                    "intent_type": "analytics_query",
                    "confidence": max(prediction.confidence - 0.15, 0.2),
                    "reasoning": "可能是经营数据查询",
                },
                {
                    "intent_type": "general_chat",
                    "confidence": max(prediction.confidence - 0.25, 0.1),
                    "reasoning": "可能是通用聊天",
                },
            ])

        elif intent_type == "analytics_query":
            alternatives.extend([
                {
                    "intent_type": "rag_qa",
                    "confidence": max(prediction.confidence - 0.15, 0.2),
                    "reasoning": "可能是知识库问答",
                },
            ])

        # 按置信度排序
        alternatives.sort(key=lambda x: x["confidence"], reverse=True)

        return alternatives


# ============================================================================
# 增量信息请求
# ============================================================================

class IncrementalContextRequester:
    """
    增量信息请求器

    当置信度较低时，智能请求更多信息：
    1. 分析当前查询的模糊点
    2. 生成针对性的追问
    3. 保持对话上下文连贯
    """

    # 模糊点识别模式（使用简单字符串匹配）
    FUZZY_PATTERNS = [
        # (关键词, 对应槽位)
        ("本月", "time_range"),
        ("上月", "time_range"),
        ("今年", "time_range"),
        ("多少", "metric"),
        ("几个", "quantity"),
        ("多大", "quantity"),
        ("哪个", "entity_type"),
        ("什么", "entity_type"),
        ("哪类", "scope"),
        ("怎么", "action"),
        ("如何", "action"),
        ("为什么", "reason"),
    ]

    def generate_incremental_questions(
        self,
        user_query: str,
        prediction: Any,
    ) -> list[str]:
        """
        生成增量追问

        Args:
            user_query: 用户查询
            prediction: 意图预测

        Returns:
            追问列表
        """
        questions = []

        # 分析模糊点
        fuzzy_slots = self._identify_fuzzy_slots(user_query)

        for slot_type in fuzzy_slots:
            question = self._generate_question_for_slot(slot_type, prediction)
            if question:
                questions.append(question)

        # 如果没有模糊点，检查槽位完整性
        if not questions:
            missing = self._identify_missing_slots_static(prediction)
            for slot in missing[:2]:  # 最多问2个
                questions.append(self._generate_question_for_slot(slot, prediction))

        return questions

    def _identify_fuzzy_slots(self, query: str) -> list[str]:
        """识别查询中的模糊槽位"""
        fuzzy = []

        for keyword, slot in self.FUZZY_PATTERNS:
            if keyword in query:
                fuzzy.append(slot)

        return list(set(fuzzy))  # 去重

    def _generate_question_for_slot(self, slot_type: str, prediction: Any) -> Optional[str]:
        """为槽位生成追问"""
        questions = {
            "time_range": "请问您想查询哪个时间段？例如：本月、上季度、最近3个月等。",
            "metric": "请问您想了解什么指标？例如：发电量、收入、利润、成本等。",
            "quantity": "请问具体数量是多少？",
            "entity_type": "请问具体是哪类？例如：哪个区域、哪个设备、哪个项目等。",
            "scope": "请问范围是什么？例如：全集团、北疆区域、南疆区域等。",
            "action": "请问具体想做什么操作？例如：查询、分析、对比等。",
            "reason": "请问您是基于什么背景提出这个问题？",
        }

        return questions.get(slot_type)

    def _identify_missing_slots_static(self, prediction: Any) -> list[str]:
        """识别缺失的槽位（静态分析）"""
        slots = prediction.extracted_slots or {}
        missing = []

        intent_type = prediction.intent_type.value if hasattr(prediction.intent_type, 'value') else prediction.intent_type

        if intent_type == "analytics_query":
            if not slots.get("metric"):
                missing.append("metric")
            if not slots.get("time_range"):
                missing.append("time_range")

        return missing


# ============================================================================
# 便捷函数
# ============================================================================

def handle_low_confidence(
    intent_prediction: Any,
    user_query: str,
    business_domain: Optional[str] = None,
    risk_level: str = "medium",
) -> HandlingDecision:
    """
    处理低置信度意图预测的便捷函数

    使用示例：
    ```python
    # LLM 返回了置信度较低的预测
    prediction = await detector.detect("帮我分析一下")

    # 系统自动选择最优处理策略
    decision = handle_low_confidence(
        prediction,
        user_query="帮我分析一下",
        domain="analytics",
        risk_level="medium",
    )

    if decision.can_execute:
        # 置信度足够，可以执行
        pass
    else:
        # 需要澄清或多意图选择
        if decision.strategy == HandlingStrategy.REQUEST_CLARIFICATION:
            return {"clarification_questions": decision.clarification_questions}
        elif decision.strategy == HandlingStrategy.MULTI_INTENT_CANDIDATES:
            return {"alternatives": decision.alternative_intents}
    ```
    """
    handler = ConfidenceHandler()
    return handler.handle(
        intent_prediction=intent_prediction,
        user_query=user_query,
        business_domain=business_domain,
        risk_level=risk_level,
    )
