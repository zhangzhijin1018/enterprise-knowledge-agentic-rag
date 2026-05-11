"""
纯 LLM 意图检测器

核心理念：
1. 100% 基于 LLM 推理，不再依赖规则
2. Few-shot Learning 提供领域知识
3. Chain-of-Thought 先推理后结论
4. Structured Output 确保格式正确
5. 智能缓存避免重复调用
6. 置信度驱动决定是否澄清

为什么不用规则：
1. 规则无法处理模糊、多义的意图
2. 规则无法理解上下文和隐含意图
3. 规则需要人工维护，无法自适应
4. LLM 的语义理解能力远超规则

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# 意图类型枚举
# ============================================================================

class IntentType(str, Enum):
    """意图类型枚举"""
    RAG_QA = "rag_qa"                    # 知识库问答
    ANALYTICS_QUERY = "analytics_query"  # 经营分析
    CONTRACT_REVIEW = "contract_review"  # 合同审查
    GENERAL_CHAT = "general_chat"        # 通用聊天
    CLARIFICATION = "clarification"       # 需要澄清
    UNSUPPORTED = "unsupported"           # 不支持


class BusinessDomain(str, Enum):
    """业务域枚举"""
    POLICY = "policy"              # 集团制度
    SAFETY = "safety"             # 安全生产
    EQUIPMENT = "equipment"       # 设备检修
    NEW_ENERGY = "new_energy"      # 新能源运维
    PROJECT = "project"           # 项目资料
    CONTRACT = "contract"         # 合同合规
    ANALYTICS = "analytics"       # 经营分析
    UNKNOWN = "unknown"


# ============================================================================
# LLM 输出模型
# ============================================================================

class IntentPrediction(BaseModel):
    """
    LLM 意图预测结果

    由 LLM 直接输出，确保格式正确
    """
    intent_type: IntentType = Field(description="意图类型")
    business_domain: Optional[BusinessDomain] = Field(default=None, description="业务域")
    routing_target: str = Field(description="路由目标")
    confidence: float = Field(ge=0.0, le=1.0, description="置信度 0-1")
    reasoning: str = Field(description="推理过程（为什么这么判断）")

    # 槽位信息
    requires_clarification: bool = Field(default=False, description="是否需要澄清")
    clarification_questions: list[str] = Field(default_factory=list, description="澄清问题")
    extracted_slots: dict[str, Any] = Field(default_factory=dict, description="提取的槽位")

    # 上下文感知
    context_dependency: str = Field(
        default="none",
        description="上下文依赖程度: none/low/medium/high"
    )
    refers_to_previous: bool = Field(default=False, description="是否引用上一轮对话")
    previous_intent_inherited: Optional[str] = Field(default=None, description="继承的上一轮意图")


class ClarificationSlot(BaseModel):
    """澄清槽位定义"""
    slot_name: str
    question: str
    examples: list[str] = Field(default_factory=list)


# ============================================================================
# 提示词工程
# ============================================================================

class IntentPromptEngine:
    """
    LLM 意图检测提示词引擎

    设计原则：
    1. Few-shot Learning - 提供领域特定示例
    2. Chain-of-Thought - 先分析再结论
    3. Structured Thinking - 结构化推理过程
    4. 业务知识注入 - 明确能源集团业务场景
    """

    # 系统提示词
    SYSTEM_PROMPT = """你是一个企业智能问答系统的意图识别专家，服务于新疆能源集团。

你的任务是准确理解用户问题，判断其真实意图，并提取关键槽位信息。

## 核心能力

1. **深度语义理解**：不只是关键词匹配，要理解用户的真实意图
2. **上下文感知**：能识别"继续"、"它"、"这个"等引用
3. **模糊意图处理**：当意图不明确时，选择最可能的意图而非报错
4. **主动澄清**：当信息不足时，生成精准的澄清问题

## 业务背景

新疆能源集团业务涵盖：
- 煤炭开采与销售
- 新能源发电（光伏、风电、储能）
- 电力生产与销售
- 设备检修与运维
- 项目建设与管理
- 安全生产与应急管理

## 意图类型

1. **rag_qa（知识库问答）**：制度政策、安全规程、设备操作、新能源运维等知识类问题
2. **analytics_query（经营分析）**：发电量、收入、利润、成本等经营数据查询和分析
3. **contract_review（合同审查）**：合同条款审查、风险识别、合规检查
4. **general_chat（通用聊天）**：问候、寒暄等无明确业务目的的对话

## 业务域分类

- policy: 集团制度、报销标准、审批流程、培训制度
- safety: 安全生产规程、应急预案、隐患治理、作业规范
- equipment: 设备检修、维修、故障排查、点检保养
- new_energy: 光伏/风电运维、发电量分析、告警处理、储能系统
- project: 项目可研、环评安评、施工进度、验收资料
- contract: 合同审查、条款对比、风险识别
- analytics: 经营数据、趋势分析、同比环比

## 置信度指南

- 0.9-1.0: 非常确定，意图非常明确
- 0.7-0.9: 确定，有明确的业务关键词
- 0.5-0.7: 较确定，意图基本清晰但有歧义
- 0.3-0.5: 不确定，模糊但有倾向
- 0.0-0.3: 非常不确定，需要澄清

## 上下文感知

当用户说：
- "继续" → 继承上一轮意图和槽位
- "它"、"这个" → 引用上一轮提到的实体
- "上月" → 继承当前时间上下文
- "同样的" → 继承分析维度

## 槽位要求

经营分析必须提取：
- metric: 指标（如：发电量、收入、利润）
- time_range: 时间范围（如：本月、上季度）
- org_scope: 组织范围（如：北疆区域、哈密）

合同审查必须提取：
- contract_type: 合同类型
- review_focus: 审查重点（如：付款条件、交付条款）

## 输出格式

请以 JSON 格式输出，包含所有字段：
```json
{
    "intent_type": "意图类型",
    "business_domain": "业务域（可选）",
    "routing_target": "路由目标",
    "confidence": 0.0-1.0,
    "reasoning": "推理过程",
    "requires_clarification": false,
    "clarification_questions": [],
    "extracted_slots": {},
    "context_dependency": "none/low/medium/high",
    "refers_to_previous": false,
    "previous_intent_inherited": null
}
```"""

    # Few-shot 示例（领域特定）
    FEW_SHOT_EXAMPLES = """
## 示例 1：直接意图

用户问题：本月光伏电站发电量是多少？

分析：
- 直接询问发电量数据
- 包含明确指标和时间
- 业务域：new_energy + analytics
- 置信度：0.92

输出：
```json
{
    "intent_type": "analytics_query",
    "business_domain": "new_energy",
    "routing_target": "analytics_agent",
    "confidence": 0.92,
    "reasoning": "用户直接询问光伏发电量数据，涉及经营指标查询，路由到分析Agent",
    "requires_clarification": false,
    "clarification_questions": [],
    "extracted_slots": {"metric": "发电量", "time_range": "本月", "energy_type": "光伏"},
    "context_dependency": "none",
    "refers_to_previous": false,
    "previous_intent_inherited": null
}
```

## 示例 2：上下文继承

用户问题：继续

分析：
- "继续"本身没有明确意图
- 需要继承上一轮对话的意图
- 上下文依赖程度：high
- 置信度取决于能否获取历史

输出：
```json
{
    "intent_type": "analytics_query",
    "business_domain": "analytics",
    "routing_target": "analytics_agent",
    "confidence": 0.85,
    "reasoning": "用户说'继续'，应继承上一轮的分析意图",
    "requires_clarification": false,
    "clarification_questions": [],
    "extracted_slots": {},
    "context_dependency": "high",
    "refers_to_previous": true,
    "previous_intent_inherited": "analytics_query"
}
```

## 示例 3：代词引用

用户问题：它的风险点有哪些？

分析：
- "它"是代词，需要消解
- 引用上一轮提到的合同/设备
- 业务域继承上一轮

输出：
```json
{
    "intent_type": "contract_review",
    "business_domain": "contract",
    "routing_target": "contract_agent",
    "confidence": 0.78,
    "reasoning": "'它'指代上一轮提到的合同，需进行风险分析",
    "requires_clarification": false,
    "clarification_questions": [],
    "extracted_slots": {},
    "context_dependency": "high",
    "refers_to_previous": true,
    "previous_intent_inherited": "contract_review"
}
```

## 示例 4：模糊意图需要澄清

用户问题：帮我分析一下

分析：
- "分析"但没有明确分析什么
- 缺少必需槽位：metric
- 需要澄清

输出：
```json
{
    "intent_type": "analytics_query",
    "business_domain": "analytics",
    "routing_target": "analytics_agent",
    "confidence": 0.45,
    "reasoning": "用户要求分析但未指定分析什么，缺少关键槽位",
    "requires_clarification": true,
    "clarification_questions": [
        "请问您想分析什么指标？例如：发电量、收入、成本等",
        "请问分析哪个时间范围？例如：本月、上季度、本年"
    ],
    "extracted_slots": {},
    "context_dependency": "low",
    "refers_to_previous": false,
    "previous_intent_inherited": null
}
```

## 示例 5：安全知识问答

用户问题：动火作业的安全操作规程是什么？

分析：
- 询问安全操作规程
- 业务域：safety
- 明确的 RAG 问答场景

输出：
```json
{
    "intent_type": "rag_qa",
    "business_domain": "safety",
    "routing_target": "rag_agent",
    "confidence": 0.96,
    "reasoning": "询问动火作业安全规程，属于安全生产知识问答",
    "requires_clarification": false,
    "clarification_questions": [],
    "extracted_slots": {"topic": "动火作业", "type": "安全规程"},
    "context_dependency": "none",
    "refers_to_previous": false,
    "previous_intent_inherited": null
}
```

## 示例 6：设备故障

用户问题：风机振动异常怎么处理？

分析：
- 设备故障咨询
- 业务域：equipment
- 可能需要进一步定位具体设备

输出：
```json
{
    "intent_type": "rag_qa",
    "business_domain": "equipment",
    "routing_target": "rag_agent",
    "confidence": 0.91,
    "reasoning": "询问风机振动异常处理方法，属于设备故障知识问答",
    "requires_clarification": false,
    "clarification_questions": [],
    "extracted_slots": {"equipment_type": "风机", "fault_symptom": "振动异常"},
    "context_dependency": "none",
    "refers_to_previous": false,
    "previous_intent_inherited": null
}
```"""

    @classmethod
    def build_prompt(
        cls,
        query: str,
        conversation_history: Optional[list[dict]] = None,
        previous_intent: Optional[str] = None,
        previous_slots: Optional[dict] = None,
    ) -> str:
        """
        构建完整的提示词

        Args:
            query: 当前查询
            conversation_history: 对话历史
            previous_intent: 上一轮意图
            previous_slots: 上一轮槽位
        """
        parts = [cls.SYSTEM_PROMPT, cls.FEW_SHOT_EXAMPLES]

        # 添加上下文
        context_parts = ["## 当前上下文\n\n"]

        if previous_intent:
            context_parts.append(f"- 上一轮意图：{previous_intent}\n")
        if previous_slots:
            slots_str = json.dumps(previous_slots, ensure_ascii=False)
            context_parts.append(f"- 上一轮槽位：{slots_str}\n")

        if conversation_history and len(conversation_history) > 0:
            context_parts.append("\n## 对话历史\n\n")
            for i, msg in enumerate(conversation_history[-4:]):  # 最近4轮
                role = msg.get("role", "user")
                content = msg.get("content", "")[:200]  # 限制长度
                context_parts.append(f"{i+1}. {role}: {content}\n")

        parts.extend(context_parts)

        parts.append(f"\n## 当前用户问题\n\n{query}\n\n")
        parts.append("## 分析与输出\n\n请按照上述格式进行推理并输出 JSON：")

        return "\n".join(parts)


# ============================================================================
# LLM 意图检测器
# ============================================================================

class LLMIntentDetector:
    """
    纯 LLM 意图检测器

    特点：
    1. 100% LLM 驱动，无规则依赖
    2. Few-shot + Chain-of-Thought
    3. 智能缓存避免重复调用
    4. 置信度驱动的澄清策略
    5. 上下文感知
    """

    # 置信度阈值
    HIGH_CONFIDENCE = 0.80   # 高置信度，直接执行
    MEDIUM_CONFIDENCE = 0.50  # 中置信度，可执行但有风险
    LOW_CONFIDENCE = 0.30    # 低置信度，强制澄清

    # 缓存配置
    CACHE_ENABLED = True
    CACHE_TTL = 3600  # 1小时

    def __init__(
        self,
        llm_gateway: Any,
        cache: Any = None,
    ):
        """
        初始化 LLM 意图检测器

        Args:
            llm_gateway: LLM 网关实例（需要实现 chat 方法）
            cache: 缓存客户端（Redis 等）
        """
        self.llm_gateway = llm_gateway
        self.cache = cache
        self.prompt_engine = IntentPromptEngine()

    def _get_cache_key(self, query: str, history_hash: str = "") -> str:
        """生成缓存 key"""
        content = query + history_hash
        hash_key = hashlib.md5(content.encode()).hexdigest()[:16]
        return f"llm_intent:{hash_key}"

    def _hash_history(self, history: list[dict]) -> str:
        """生成历史摘要的 hash"""
        if not history:
            return ""
        # 只取最近2轮的 content
        recent = [h.get("content", "")[:100] for h in history[-2:]]
        content = "|".join(recent)
        return hashlib.md5(content.encode()).hexdigest()[:8]

    async def detect(
        self,
        query: str,
        conversation_history: Optional[list[dict]] = None,
        previous_intent: Optional[str] = None,
        previous_slots: Optional[dict] = None,
        user_context: Optional[dict] = None,
    ) -> IntentPrediction:
        """
        LLM 意图检测（异步）

        Args:
            query: 当前查询
            conversation_history: 对话历史
            previous_intent: 上一轮意图
            previous_slots: 上一轮槽位
            user_context: 用户上下文

        Returns:
            IntentPrediction: 意图预测结果
        """
        # 1. 检查缓存
        if self.CACHE_ENABLED and self.cache:
            cache_key = self._get_cache_key(query, self._hash_history(conversation_history or []))
            cached = await self._get_from_cache(cache_key)
            if cached:
                logger.debug(f"Intent cache hit: {query[:30]}...")
                return cached

        # 2. 构建消息
        messages = self._build_messages(
            query=query,
            conversation_history=conversation_history,
            previous_intent=previous_intent,
            previous_slots=previous_slots,
        )

        # 3. 调用 LLM
        try:
            response = await self._call_llm(messages)
            prediction = self._parse_response(response)
        except Exception as e:
            logger.error(f"LLM intent detection failed: {e}")
            # LLM 失败，返回默认结果
            prediction = self._fallback_prediction(query)

        # 4. 保存缓存
        if self.CACHE_ENABLED and self.cache:
            await self._save_to_cache(cache_key, prediction)

        return prediction

    def _build_messages(
        self,
        query: str,
        conversation_history: Optional[list[dict]] = None,
        previous_intent: Optional[str] = None,
        previous_slots: Optional[dict] = None,
    ) -> list[dict]:
        """构建 LLM 消息列表"""
        prompt = self.prompt_engine.build_prompt(
            query=query,
            conversation_history=conversation_history,
            previous_intent=previous_intent,
            previous_slots=previous_slots,
        )

        return [
            {"role": "system", "content": "你是一个意图识别专家。"},
            {"role": "user", "content": prompt},
        ]

    async def _call_llm(self, messages: list[dict]) -> str:
        """调用 LLM"""
        # 支持不同的 LLM 网关格式
        if hasattr(self.llm_gateway, "chat"):
            # 标准格式
            response = await self.llm_gateway.chat(
                messages=messages,
                temperature=0.1,  # 低温度保证稳定性
            )
            if hasattr(response, "content"):
                return response.content
            return str(response)
        elif hasattr(self.llm_gateway, "invoke"):
            # LangChain 格式
            response = await self.llm_gateway.invoke(messages)
            if hasattr(response, "content"):
                return response.content
            return str(response)
        else:
            raise ValueError("LLM gateway must implement chat() or invoke() method")

    def _parse_response(self, content: str) -> IntentPrediction:
        """解析 LLM 响应"""
        # 提取 JSON
        json_match = re.search(
            r"```(?:json)?\s*(\{[\s\S]*?\})\s*```|"  # 代码块
            r"(\{[\s\S]*\})",  # 裸 JSON
            content
        )

        if json_match:
            json_str = json_match.group(1) or json_match.group(2)
            try:
                data = json.loads(json_str)
                return IntentPrediction(
                    intent_type=IntentType(data.get("intent_type", "rag_qa")),
                    business_domain=BusinessDomain(data.get("business_domain", "unknown"))
                        if data.get("business_domain") else None,
                    routing_target=data.get("routing_target", "rag_agent"),
                    confidence=float(data.get("confidence", 0.5)),
                    reasoning=data.get("reasoning", ""),
                    requires_clarification=data.get("requires_clarification", False),
                    clarification_questions=data.get("clarification_questions", []),
                    extracted_slots=data.get("extracted_slots", {}),
                    context_dependency=data.get("context_dependency", "none"),
                    refers_to_previous=data.get("refers_to_previous", False),
                    previous_intent_inherited=data.get("previous_intent_inherited"),
                )
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to parse LLM response: {e}")
                raise

        raise ValueError(f"Cannot extract JSON from LLM response: {content[:200]}")

    def _fallback_prediction(self, query: str) -> IntentPrediction:
        """LLM 失败时的兜底预测"""
        return IntentPrediction(
            intent_type=IntentType.RAG_QA,
            business_domain=BusinessDomain.UNKNOWN,
            routing_target="rag_agent",
            confidence=0.3,
            reasoning="LLM调用失败，使用默认预测",
            requires_clarification=False,
            clarification_questions=[],
            extracted_slots={},
            context_dependency="none",
            refers_to_previous=False,
            previous_intent_inherited=None,
        )

    async def _get_from_cache(self, key: str) -> Optional[IntentPrediction]:
        """从缓存获取"""
        try:
            cached = await self.cache.get(key)
            if cached:
                data = json.loads(cached)
                return IntentPrediction(**data)
        except Exception as e:
            logger.warning(f"Cache get error: {e}")
        return None

    async def _save_to_cache(self, key: str, prediction: IntentPrediction) -> None:
        """保存到缓存"""
        try:
            await self.cache.setex(
                key,
                self.CACHE_TTL,
                prediction.model_dump_json(),
            )
        except Exception as e:
            logger.warning(f"Cache set error: {e}")


# ============================================================================
# 便捷函数
# ============================================================================

async def detect_intent_llm(
    query: str,
    llm_gateway: Any,
    cache: Any = None,
    conversation_history: Optional[list[dict]] = None,
    previous_intent: Optional[str] = None,
    previous_slots: Optional[dict] = None,
) -> IntentPrediction:
    """
    纯 LLM 意图检测便捷函数

    使用示例：
    ```python
    # 初始化
    detector = LLMIntentDetector(llm_gateway=llm_gateway, cache=redis_client)

    # 检测意图
    result = await detect_intent_llm(
        query="本月光伏发电量是多少？",
        llm_gateway=llm_gateway,
        conversation_history=history,
        previous_intent="analytics_query",
        previous_slots={"metric": "发电量"},
    )

    print(f"意图: {result.intent_type}")
    print(f"置信度: {result.confidence}")
    print(f"路由: {result.routing_target}")
    print(f"推理: {result.reasoning}")
    ```
    """
    detector = LLMIntentDetector(
        llm_gateway=llm_gateway,
        cache=cache,
    )
    return await detector.detect(
        query=query,
        conversation_history=conversation_history,
        previous_intent=previous_intent,
        previous_slots=previous_slots,
    )
