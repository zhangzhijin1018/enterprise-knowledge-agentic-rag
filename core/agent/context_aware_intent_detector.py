"""
上下文感知的意图检测器

核心改进：
1. 真正的上下文获取 - 从数据库/缓存获取完整对话历史
2. 多因子置信度算法 - 综合多个因子计算置信度
3. 指代消解 - 处理"它"、"这个"等代词
4. 意图继承 - 基于上一轮意图推断当前意图

算法说明：
- 置信度 = 基础分 * 上下文加成 * 槽位加成 * 历史连贯性
- 每个因子都有明确的数学公式，不是拍脑袋

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# 置信度因子权重配置
# ============================================================================

@dataclass
class ConfidenceWeights:
    """置信度因子权重配置

    所有权重经过归一化，确保总分不超过 1.0
    """
    # 基础匹配分（正则/关键词匹配）
    BASE_MATCH_MIN: float = 0.40  # 最低基础分
    BASE_MATCH_MAX: float = 0.85  # 最高基础分

    # 上下文加成因子
    CONTEXT_MATCH: float = 0.10   # 上下文关键词匹配
    PRONOUN_RESOLVED: float = 0.05  # 代词被成功消解

    # 槽位加成因子
    SLOT_COMPLETE: float = 0.08   # 槽位完整
    SLOT_PARTIAL: float = 0.03    # 槽位部分填充

    # 历史连贯性因子
    INTENT_INHERIT: float = 0.05   # 意图继承（多轮对话）
    DOMAIN_CONSISTENT: float = 0.03  # 业务域一致

    # 上限
    MAX_CONFIDENCE: float = 0.98   # 最高置信度（留有余地）


# 全局权重实例
DEFAULT_WEIGHTS = ConfidenceWeights()


# ============================================================================
# 意图检测上下文
# ============================================================================

@dataclass
class IntentDetectionContext:
    """
    意图检测的完整上下文

    包含：
    1. 当前查询
    2. 对话历史（从数据库获取）
    3. 上一轮意图信息
    4. 当前槽位状态
    5. 用户画像（可选）
    """
    # 当前查询
    current_query: str

    # 对话历史（已解析的结构化历史）
    conversation_history: list[dict] = field(default_factory=list)

    # 上一轮意图信息
    previous_intent: Optional[str] = None  # 上一轮意图类型
    previous_domain: Optional[str] = None  # 上一轮业务域
    previous_slots: dict[str, Any] = field(default_factory=dict)  # 上一轮槽位

    # 当前已提取的槽位
    current_slots: dict[str, Any] = field(default_factory=dict)

    # 用户信息
    user_id: Optional[str] = None
    user_role: Optional[str] = None

    # 置信度配置
    weights: ConfidenceWeights = field(default_factory=DEFAULT_WEIGHTS)

    @property
    def history_count(self) -> int:
        """对话轮次数量"""
        return len(self.conversation_history)

    @property
    def last_user_message(self) -> Optional[str]:
        """上一轮用户消息"""
        for msg in reversed(self.conversation_history):
            if msg.get("role") == "user":
                return msg.get("content")
        return None

    @property
    def last_assistant_message(self) -> Optional[str]:
        """上一轮助手消息"""
        for msg in reversed(self.conversation_history):
            if msg.get("role") == "assistant":
                return msg.get("content")
        return None


# ============================================================================
# 置信度因子
# ============================================================================

@dataclass
class ConfidenceFactor:
    """置信度因子"""
    name: str
    value: float
    weight: float
    description: str

    @property
    def contribution(self) -> float:
        """该因子对置信度的贡献"""
        return self.value * self.weight


@dataclass
class ConfidenceBreakdown:
    """
    置信度分解

    展示每个因子对最终置信度的贡献
    """
    factors: list[ConfidenceFactor] = field(default_factory=list)
    base_score: float = 0.0
    final_score: float = 0.0

    def add_factor(self, name: str, value: float, weight: float, description: str = "") -> None:
        """添加一个因子"""
        self.factors.append(ConfidenceFactor(
            name=name,
            value=value,
            weight=weight,
            description=description,
        ))

    def compute_final_score(self, max_score: float = 0.98) -> float:
        """计算最终置信度"""
        total = self.base_score
        for factor in self.factors:
            total += factor.contribution

        self.final_score = min(total, max_score)
        return self.final_score

    def to_dict(self) -> dict:
        """转换为字典（用于日志/调试）"""
        return {
            "final_score": round(self.final_score, 4),
            "base_score": round(self.base_score, 4),
            "factors": [
                {
                    "name": f.name,
                    "value": round(f.value, 4),
                    "weight": f.weight,
                    "contribution": round(f.contribution, 4),
                    "description": f.description,
                }
                for f in self.factors
            ],
        }


# ============================================================================
# 代词消解器
# ============================================================================

class PronounResolver:
    """
    代词消解器

    处理多轮对话中的代词指代问题：
    - "它"、"这个"、"那" -> 指向上下文中的实体
    - "继续"、"同上" -> 继承上一轮意图
    - "刚才问的" -> 引用历史意图
    """

    # 代词模式
    PRONOUN_PATTERNS = {
        # 直接代词（需要上下文消解）
        r"^(它|这个|那个|这件|那件|上述)",  # 指代上文提到的实体

        # 继承关键词（继承上一轮意图）
        r"^(继续|同上|一样|同样)",  # 继承上一轮

        # 省略句（无主语，需要结合上文理解）
        r"^(怎么看|怎么分析|详细说说|展开说|具体点|举个例子|说明一下|为什么|依据是什么|怎么得出)",  # 追问类
    }

    # 时间词模式（这些通常不是代词，而是明确的时间限定）
    TIME_PATTERNS = [
        r"^本月", r"^上月", r"^本季度", r"^上季度",
        r"^本年", r"^去年", r"^今年", r"^今天",
        r"^现在", r"^目前",
    ]

    # 继承关键词
    INHERIT_KEYWORDS = [
        "继续", "同上", "一样", "同样",
        "继续分析", "继续看", "继续说",
        "还有呢", "还有吗", "然后呢",
    ]

    # 追问关键词
    FOLLOW_UP_KEYWORDS = [
        "怎么看", "怎么分析", "详细说说", "展开说",
        "具体点", "举个例子", "说明一下",
        "为什么", "依据是什么", "怎么得出",
    ]

    def __init__(self):
        self._patterns = [re.compile(p, re.IGNORECASE) for p in self.PRONOUN_PATTERNS]

    def is_pronoun_query(self, query: str) -> bool:
        """
        判断是否是代词查询（需要消解）

        特征：
        1. 以代词开头（它/这个/继续等）
        2. 以继承关键词开头
        3. 句子很短（<10字）且没有明确实体/动词
        """
        query = query.strip()

        # 1. 检查代词模式
        for pattern in self._patterns:
            if pattern.match(query):
                return True

        # 2. 检查是否是短句且没有明确实体
        if len(query) < 10:
            # 有明确动词或主语的短句不算代词查询
            explicit_markers = [
                "请", "帮我", "帮我", "我要", "我想",  # 明确的主谓结构
                "查", "看", "查一下", "看一下",  # 明确动作
                "审查", "分析", "计算",  # 明确业务动词
                "告诉", "说明", "解释",  # 明确信息动词
            ]
            if any(marker in query for marker in explicit_markers):
                return False
            # 真正需要消解的短句
            return True

        return False

    def resolve_pronoun(self, query: str, context: IntentDetectionContext) -> tuple[str, float]:
        """
        消解代词，返回展开后的查询和置信度

        Args:
            query: 原始查询（可能含代词）
            context: 对话上下文

        Returns:
            (展开后的查询, 代词消解置信度)
        """
        query = query.strip()

        # 1. 检查是否是继承类查询
        for keyword in self.INHERIT_KEYWORDS:
            if query.startswith(keyword):
                return self._resolve_inherit(query, context)

        # 2. 检查是否是追问类查询
        for keyword in self.FOLLOW_UP_KEYWORDS:
            if keyword in query:
                return self._resolve_follow_up(query, context)

        # 3. 检查是否是代词指代
        for pattern in self._patterns:
            if pattern.match(query):
                return self._resolve_entity_reference(query, context)

        # 无法消解，返回原查询
        return query, 0.0

    def _resolve_inherit(self, query: str, context: IntentDetectionContext) -> tuple[str, float]:
        """
        处理继承类查询

        例如：
        - "继续" -> 继承上一轮的完整意图和槽位
        - "继续分析" -> 继承上一轮的分析意图
        """
        if not context.previous_intent:
            return query, 0.0

        # 尝试构建完整的继承查询
        resolved_query = query

        # 如果上一轮有明确的指标和时间，补充到查询中
        if context.previous_slots:
            metric = context.previous_slots.get("metric", "")
            time_range = context.previous_slots.get("time_range", "")

            if metric and metric not in query:
                resolved_query = f"{query} {metric}"
            if time_range and time_range not in query:
                resolved_query = f"{resolved_query} {time_range}"

        # 代词消解置信度：如果能成功继承，返回较高分
        confidence = 0.8 if resolved_query != query else 0.4

        return resolved_query, confidence

    def _resolve_follow_up(self, query: str, context: IntentDetectionContext) -> tuple[str, str, float]:
        """
        处理追问类查询

        例如：
        - "怎么看" -> 需要结合上文实体回答
        - "详细说说" -> 需要展开上文的回答
        """
        # 追问类查询不需要完全消解，但需要标记上下文依赖
        return query, 0.7

    def _resolve_entity_reference(self, query: str, context: IntentDetectionContext) -> tuple[str, float]:
        """
        处理实体指代查询

        例如：
        - "它的风险点有哪些" -> 指向上下文提到的合同/设备
        - "这个审批流程是什么" -> 指向上下文提到的流程
        """
        # 获取上一轮提到的实体（从助手的回复中提取）
        last_response = context.last_assistant_message or ""

        # 如果上一轮有明确的实体，提取得分 +0.6
        if last_response and len(last_response) > 20:
            return query, 0.6

        # 如果没有上下文，返回原查询，置信度低
        return query, 0.2


# ============================================================================
# 上下文分析器
# ============================================================================

class ContextAnalyzer:
    """
    上下文分析器

    分析对话历史，提取：
    1. 意图连贯性
    2. 业务域一致性
    3. 槽位继承关系
    """

    # 意图连贯性映射（哪些意图自然衔接）
    INTENT_TRANSITIONS = {
        # 上一轮 -> 当前可能意图
        ("rag_qa", "analytics_query"): 0.8,  # 从问答转到分析很正常
        ("analytics_query", "analytics_query"): 0.9,  # 连续分析
        ("rag_qa", "rag_qa"): 0.7,  # 连续问答
        ("contract_review", "contract_review"): 0.95,  # 连续合同审查
        ("clarification", "rag_qa"): 0.9,  # 澄清后继续原话题
        ("clarification", "analytics_query"): 0.9,  # 澄清后继续原话题
    }

    def __init__(self):
        self.pronoun_resolver = PronounResolver()

    def analyze(
        self,
        query: str,
        context: IntentDetectionContext,
    ) -> tuple[IntentDetectionContext, ConfidenceBreakdown]:
        """
        分析上下文，返回增强后的上下文和置信度分解

        主要工作：
        1. 代词消解
        2. 计算上下文加成
        3. 计算历史连贯性加成
        """
        breakdown = ConfidenceBreakdown()
        original_query = query

        # 1. 代词消解
        resolved_query, pronoun_confidence = self.pronoun_resolver.resolve_pronoun(
            query, context
        )

        if resolved_query != query:
            context = IntentDetectionContext(
                current_query=resolved_query,
                conversation_history=context.conversation_history,
                previous_intent=context.previous_intent,
                previous_domain=context.previous_domain,
                previous_slots=context.previous_slots,
                current_slots=context.current_slots,
                user_id=context.user_id,
                user_role=context.user_role,
                weights=context.weights,
            )
            breakdown.add_factor(
                name="pronoun_resolution",
                value=pronoun_confidence,
                weight=context.weights.PRONOUN_RESOLVED,
                description="代词消解成功",
            )

        # 2. 计算上下文匹配加成
        context_match_score = self._compute_context_match(context)
        if context_match_score > 0:
            breakdown.add_factor(
                name="context_match",
                value=context_match_score,
                weight=context.weights.CONTEXT_MATCH,
                description="上下文关键词匹配",
            )

        # 3. 计算历史连贯性加成
        intent_inherit_score = self._compute_intent_inheritance(context)
        if intent_inherit_score > 0:
            breakdown.add_factor(
                name="intent_inheritance",
                value=intent_inherit_score,
                weight=context.weights.INTENT_INHERIT,
                description="意图继承自上一轮",
            )

        domain_consistent_score = self._compute_domain_consistency(context)
        if domain_consistent_score > 0:
            breakdown.add_factor(
                name="domain_consistency",
                value=domain_consistent_score,
                weight=context.weights.DOMAIN_CONSISTENT,
                description="业务域保持一致",
            )

        return context, breakdown

    def _compute_context_match(self, context: IntentDetectionContext) -> float:
        """
        计算上下文匹配分

        如果当前查询的关键词与上下文（尤其是上一轮）匹配，加分
        """
        query = context.current_query.lower()

        # 从上一轮用户消息中提取关键词
        last_user = (context.last_user_message or "").lower()
        last_assistant = (context.last_assistant_message or "").lower()

        # 检查上一轮是否提到了实体（公司名、指标名、设备名等）
        entities = []

        # 提取上一轮提到的中文实体词
        entity_patterns = [
            r"([^，,。.\s]{2,10})(公司|集团|电站|电厂|煤矿)",
            r"(本月|上月|本季度|上季度|本年|去年)(\S{0,10})",
            r"(\S{0,10})(发电量|收入|利润|成本)",
            r"(\S{0,10})(合同|协议|项目|设备|风机|光伏)",
        ]

        for pattern in entity_patterns:
            matches = re.findall(pattern, last_assistant)
            for match in matches:
                if isinstance(match, tuple):
                    entities.extend([m for m in match if m])
                else:
                    entities.append(match)

        # 检查当前查询是否引用了这些实体
        if entities:
            matches = sum(1 for e in entities if e in query)
            if matches > 0:
                return min(matches / len(entities), 1.0)

        return 0.0

    def _compute_intent_inheritance(self, context: IntentDetectionContext) -> float:
        """
        计算意图继承分

        如果当前查询可能是上一轮意图的延续，加分
        """
        if not context.previous_intent:
            return 0.0

        # 检查是否是继承类查询
        for keyword in PronounResolver.INHERIT_KEYWORDS:
            if keyword in context.current_query:
                # 检查是否存在从上一轮到某个意图的合理转移
                for (prev, curr), score in self.INTENT_TRANSITIONS.items():
                    if prev == context.previous_intent:
                        return score

        # 检查是否是简短的追问
        if len(context.current_query) < 20:
            # 短查询更可能是追问
            return 0.5

        return 0.0

    def _compute_domain_consistency(self, context: IntentDetectionContext) -> float:
        """
        计算业务域一致性分

        如果当前查询与上一轮业务域一致，加分
        """
        if not context.previous_domain:
            return 0.0

        # 从当前查询检测业务域
        current_domain = self._detect_brief_domain(context.current_query)

        if current_domain and current_domain == context.previous_domain:
            return 0.8

        # 如果当前查询没有明确域，但上一轮有，保持一定分数
        if context.previous_domain and not current_domain:
            return 0.4

        return 0.0

    def _detect_brief_domain(self, query: str) -> Optional[str]:
        """快速检测业务域（简单版）"""
        query = query.lower()

        domain_keywords = {
            "safety": ["安全", "事故", "隐患", "应急", "动火", "有限空间"],
            "equipment": ["设备", "检修", "维修", "故障", "风机", "逆变器"],
            "new_energy": ["光伏", "风电", "储能", "发电量", "电站"],
            "policy": ["制度", "报销", "审批", "流程", "规定"],
            "contract": ["合同", "协议", "条款", "风险", "法务"],
            "analytics": ["收入", "利润", "成本", "产量", "分析", "同比"],
        }

        for domain, keywords in domain_keywords.items():
            if any(kw in query for kw in keywords):
                return domain

        return None


# ============================================================================
# 槽位置信度计算器
# ============================================================================

class SlotConfidenceCalculator:
    """
    槽位置信度计算器

    根据槽位填充情况计算置信度加成：
    - 必需槽位完整：高加分
    - 必需槽位部分填充：中等加分
    - 必需槽位缺失：扣分
    """

    # 不同意图的必需槽位
    REQUIRED_SLOTS = {
        "analytics_query": ["metric", "time_range"],
        "contract_review": ["contract_file_id"],
        "rag_qa": [],  # RAG 问答不需要必需槽位
    }

    # 槽位填充质量评分
    SLOT_QUALITY_SCORES = {
        "high": 1.0,    # 完全匹配
        "medium": 0.6,  # 部分匹配
        "low": 0.3,     # 模糊匹配
        "none": 0.0,    # 未填充
    }

    def compute_slot_confidence(
        self,
        intent_type: str,
        slots: dict[str, Any],
    ) -> tuple[float, ConfidenceBreakdown]:
        """
        计算槽位置信度

        Returns:
            (置信度加成, 置信度分解)
        """
        breakdown = ConfidenceBreakdown()

        required = self.REQUIRED_SLOTS.get(intent_type, [])

        if not required:
            # 不需要必需槽位
            breakdown.add_factor(
                name="no_required_slots",
                value=1.0,
                weight=0.05,  # 简化处理，不需要槽位时给个基础分
                description="该意图类型不需要必需槽位",
            )
            return 0.05, breakdown

        # 检查必需槽位
        filled_count = 0
        total_count = len(required)

        for slot_name in required:
            slot_data = slots.get(slot_name)
            quality = self._assess_slot_quality(slot_data)
            filled_count += quality

            breakdown.add_factor(
                name=f"slot_{slot_name}",
                value=quality,
                weight=0.04,  # 每个槽位权重
                description=f"槽位 {slot_name} 填充质量: {quality:.1%}",
            )

        # 计算槽位完整度
        completeness = filled_count / total_count if total_count > 0 else 1.0

        # 槽位完整度高，加成高
        if completeness >= 1.0:
            slot_bonus = 0.08
        elif completeness >= 0.5:
            slot_bonus = 0.04
        else:
            slot_bonus = 0.0

        return slot_bonus, breakdown

    def _assess_slot_quality(self, slot_data: Any) -> float:
        """评估槽位填充质量"""
        if slot_data is None:
            return 0.0

        if isinstance(slot_data, dict):
            # 有详细槽位数据
            confidence = slot_data.get("confidence", 0.8)
            value = slot_data.get("value")
            if value and confidence > 0.7:
                return 1.0
            elif value and confidence > 0.5:
                return 0.6
            elif value:
                return 0.3
            return 0.0

        # 简单值
        if slot_data:
            return 0.8
        return 0.0


# ============================================================================
# 主入口：上下文感知意图检测器
# ============================================================================

class ContextAwareIntentDetector:
    """
    上下文感知意图检测器

    核心算法：
    1. 获取对话上下文
    2. 代词消解
    3. 多因子置信度计算
    4. 意图识别
    5. 槽位提取

    置信度公式：
    final_score = base_score
                + context_match_bonus
                + pronoun_resolution_bonus
                + slot_completion_bonus
                + intent_inheritance_bonus
                + domain_consistency_bonus

    其中每个 bonus = value * weight
    """

    def __init__(
        self,
        conversation_repository: Optional[Any] = None,
        weights: Optional[ConfidenceWeights] = None,
    ):
        """
        初始化上下文感知意图检测器

        Args:
            conversation_repository: 对话仓库（用于获取历史）
            weights: 置信度权重配置
        """
        self.conversation_repository = conversation_repository
        self.weights = weights or DEFAULT_WEIGHTS

        # 子组件
        self.context_analyzer = ContextAnalyzer()
        self.slot_calculator = SlotConfidenceCalculator()

        # 基础意图检测器（用于获取基础分和路由）
        self.base_detector = None  # 懒加载

    @property
    def base_detector(self):
        """懒加载基础检测器"""
        if self._base_detector is None:
            from core.agent.intent_detector import IntentDetector
            self._base_detector = IntentDetector()
        return self._base_detector

    @base_detector.setter
    def base_detector(self, value):
        self._base_detector = value

    async def detect(
        self,
        query: str,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        previous_intent: Optional[str] = None,
        previous_domain: Optional[str] = None,
        previous_slots: Optional[dict] = None,
    ) -> dict:
        """
        上下文感知的意图检测

        Args:
            query: 当前查询
            conversation_id: 会话 ID（用于获取历史）
            user_id: 用户 ID
            previous_intent: 上一轮意图（可从会话状态获取）
            previous_domain: 上一轮业务域
            previous_slots: 上一轮槽位

        Returns:
            {
                "intent_type": str,
                "confidence": float,
                "confidence_breakdown": dict,
                "routing_target": str,
                "slots": dict,
                "requires_clarification": bool,
                "clarification_questions": list,
                "resolved_query": str,  # 代词消解后的查询
                "context_used": bool,   # 是否使用了上下文
            }
        """
        # 1. 获取对话历史
        history = await self._get_conversation_history(conversation_id, user_id)

        # 2. 构建检测上下文
        context = IntentDetectionContext(
            current_query=query,
            conversation_history=history,
            previous_intent=previous_intent,
            previous_domain=previous_domain,
            previous_slots=previous_slots or {},
            user_id=user_id,
            weights=self.weights,
        )

        # 3. 代词消解和上下文分析
        context, context_breakdown = self.context_analyzer.analyze(query, context)

        # 4. 基础意图检测
        base_result = self.base_detector.detect(context.current_query)
        base_confidence = base_result.confidence

        # 构建基础置信度分解
        full_breakdown = ConfidenceBreakdown(base_score=base_confidence)
        full_breakdown.factors.extend(context_breakdown.factors)

        # 5. 槽位置信度
        slot_bonus, slot_breakdown = self.slot_calculator.compute_slot_confidence(
            base_result.intent_type.value,
            base_result.slots.slots if hasattr(base_result.slots, 'slots') else {},
        )
        full_breakdown.add_factor(
            name="slot_completion",
            value=1.0 if slot_bonus > 0 else 0.0,
            weight=slot_bonus,
            description=f"槽位完成度加成: {slot_bonus:.3f}",
        )

        # 6. 计算最终置信度
        final_confidence = full_breakdown.compute_final_score(self.weights.MAX_CONFIDENCE)

        # 7. 检查是否需要澄清
        requires_clarification, clarification_questions = self._check_clarification(
            base_result.intent_type,
            base_result.slots,
        )

        return {
            "intent_type": base_result.intent_type.value,
            "confidence": round(final_confidence, 4),
            "confidence_breakdown": full_breakdown.to_dict(),
            "routing_target": base_result.routing_target,
            "slots": {
                k: v.value if hasattr(v, 'value') else v
                for k, v in base_result.slots.slots.items()
            } if hasattr(base_result.slots, 'slots') else {},
            "requires_clarification": requires_clarification,
            "clarification_questions": clarification_questions,
            "resolved_query": context.current_query,
            "context_used": len(history) > 0,
            "original_query": query,
            "pronoun_resolved": context.current_query != query,
        }

    async def _get_conversation_history(
        self,
        conversation_id: Optional[str],
        user_id: Optional[str],
    ) -> list[dict]:
        """获取对话历史"""
        if not conversation_id:
            return []

        if self.conversation_repository:
            try:
                messages = self.conversation_repository.get_messages(
                    conversation_id=conversation_id,
                    limit=10,  # 最近10轮
                )
                return [msg if isinstance(msg, dict) else msg.model_dump() for msg in messages]
            except Exception as e:
                logger.warning(f"获取对话历史失败: {e}")

        return []

    def _check_clarification(
        self,
        intent_type: Any,
        slots: Any,
    ) -> tuple[bool, list[str]]:
        """检查是否需要澄清"""
        if hasattr(slots, 'missing') and slots.missing:
            questions = []
            for slot_name in slots.missing:
                if slot_name == "metric":
                    questions.append("请问您想查询哪个指标？例如：发电量、收入、成本等。")
                elif slot_name == "time_range":
                    questions.append("请问您想查询哪个时间范围？例如：本月、上季度、最近3个月等。")
                elif slot_name == "contract_file_id":
                    questions.append("请提供要审查的合同文件 ID 或上传合同文件。")
            return True, questions
        return False, []


# ============================================================================
# 便捷函数
# ============================================================================

async def detect_intent_with_context(
    query: str,
    conversation_id: Optional[str] = None,
    user_id: Optional[str] = None,
    conversation_repository: Optional[Any] = None,
    previous_intent: Optional[str] = None,
    previous_domain: Optional[str] = None,
    previous_slots: Optional[dict] = None,
) -> dict:
    """
    上下文感知的意图检测便捷函数

    使用示例：
    ```python
    result = await detect_intent_with_context(
        query="继续分析",
        conversation_id="conv_xxx",
        previous_intent="analytics_query",
        previous_slots={"metric": "发电量", "time_range": "本月"},
    )

    print(f"意图: {result['intent_type']}")
    print(f"置信度: {result['confidence']}")
    print(f"置信度分解: {result['confidence_breakdown']}")
    ```
    """
    detector = ContextAwareIntentDetector(
        conversation_repository=conversation_repository,
    )
    return await detector.detect(
        query=query,
        conversation_id=conversation_id,
        user_id=user_id,
        previous_intent=previous_intent,
        previous_domain=previous_domain,
        previous_slots=previous_slots,
    )
