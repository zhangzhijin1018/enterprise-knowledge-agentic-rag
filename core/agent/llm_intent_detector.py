"""
LLM 意图识别模块

基于 LLM 的用户意图识别，提供比规则更智能的意图理解能力。

设计原则：
1. Few-shot Prompting - 通过示例提升识别准确率
2. Chain-of-Thought - 复杂意图先推理再结论
3. 结构化输出 - 使用 Pydantic 约束输出格式
4. 规则兜底 - LLM 不可用时降级到规则引擎
5. 缓存优化 - 相同 query 直接返回缓存结果

意图类型：
- rag_qa: 通用知识库问答 → rag_agent
- analytics_query: 经营分析查询 → analytics_agent
- contract_review: 合同审查 → contract_agent
- general_chat: 通用聊天 → rag_agent
- clarification: 需要澄清 → supervisor
- unsupported: 不支持的意图 → supervisor

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import hashlib
import logging
import re
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# 意图类型枚举（与 intent_detector.py 保持一致）
# ============================================================================

class IntentType(str, Enum):
    """意图类型枚举"""
    RAG_QA = "rag_qa"
    ANALYTICS_QUERY = "analytics_query"
    CONTRACT_REVIEW = "contract_review"
    GENERAL_CHAT = "general_chat"
    CLARIFICATION = "clarification"
    UNSUPPORTED = "unsupported"


# ============================================================================
# 业务域枚举
# ============================================================================

class BusinessDomain(str, Enum):
    """业务域枚举"""
    POLICY = "policy"          # 集团制度政策
    SAFETY = "safety"         # 安全生产
    EQUIPMENT = "equipment"    # 设备检修
    NEW_ENERGY = "new_energy"  # 新能源运维
    PROJECT = "project"        # 项目资料
    CONTRACT = "contract"      # 合同合规
    UNKNOWN = "unknown"


# ============================================================================
# 输出模型
# ============================================================================

class IntentOutput(BaseModel):
    """LLM 意图识别输出模型"""
    intent_type: IntentType = Field(description="识别的意图类型")
    business_domain: Optional[BusinessDomain] = Field(default=None, description="业务域")
    routing_target: str = Field(description="路由目标 Agent")
    confidence: float = Field(ge=0.0, le=1.0, description="置信度")
    reasoning: str = Field(description="识别理由（Chain-of-Thought）")
    requires_clarification: bool = Field(default=False, description="是否需要澄清")
    clarification_questions: list[str] = Field(default_factory=list, description="澄清问题")
    slot_extraction: dict[str, Any] = Field(default_factory=dict, description="提取的槽位")


# ============================================================================
# 提示词模板
# ============================================================================

class IntentPromptTemplate:
    """
    意图识别提示词模板

    设计特点：
    1. Few-shot Learning - 提供 3-5 个典型示例
    2. Chain-of-Thought - 要求模型先分析再结论
    3. 领域知识注入 - 明确新疆能源集团业务背景
    4. 安全边界 - 明确不支持的高风险场景
    """

    # 系统提示词
    SYSTEM_PROMPT = """你是一个企业智能问答系统的意图识别专家，服务于新疆能源集团。

你的职责是准确识别用户查询的意图，并提取关键槽位信息。

## 业务背景

新疆能源集团主要业务涵盖：
- 煤炭开采与销售
- 新能源发电（光伏、风电）
- 电力生产与销售
- 设备检修与运维
- 项目建设与管理

## 意图类型定义

1. **rag_qa（知识库问答）**：关于制度政策、安全规程、设备操作、新能源运维、项目资料等知识类问题
2. **analytics_query（经营分析）**：查询发电量、收入、利润、成本等经营数据，或需要 SQL 查询
3. **contract_review（合同审查）**：审查合同条款、识别风险、进行合规检查
4. **general_chat（通用聊天）**：问候、寒暄、无明确业务目的的对话

## 业务域分类

- policy：集团制度、报销标准、审批流程
- safety：安全生产规程、应急预案、隐患治理
- equipment：设备检修、维修、故障排查
- new_energy：光伏/风电运维、发电量分析、告警处理
- project：项目可研、环评、施工进度
- contract：合同审查、合规检查

## 输出要求

请以 JSON 格式输出，包含以下字段：
- intent_type: 意图类型
- business_domain: 业务域（可选）
- routing_target: 路由目标（rag_agent/analytics_agent/contract_agent/supervisor）
- confidence: 置信度（0-1）
- reasoning: 识别理由
- requires_clarification: 是否需要澄清
- clarification_questions: 澄清问题列表（如需澄清）
- slot_extraction: 槽位提取结果

## 注意事项

1. 当意图模糊时，优先选择更具体的意图
2. 涉及数据查询的分析类问题，优先识别为 analytics_query
3. 合同相关问题，优先识别为 contract_review
4. 只有当问题明显属于闲聊时，才识别为 general_chat"""

    # Few-shot 示例
    FEW_SHOT_EXAMPLES = """
## 示例 1

用户问题：请问集团差旅费报销标准是多少？

分析：
- 询问集团制度/报销标准
- 属于知识库问答
- 业务域：policy

输出：
```json
{
    "intent_type": "rag_qa",
    "business_domain": "policy",
    "routing_target": "rag_agent",
    "confidence": 0.95,
    "reasoning": "用户询问集团差旅费报销标准，属于集团制度政策类问题，应由RAG Agent处理",
    "requires_clarification": false,
    "clarification_questions": [],
    "slot_extraction": {}
}
```

## 示例 2

用户问题：本月光伏电站发电量是多少？和上月相比增长了多少？

分析：
- 询问发电量数据
- 涉及环比分析
- 需要 SQL 查询经营数据

输出：
```json
{
    "intent_type": "analytics_query",
    "business_domain": "new_energy",
    "routing_target": "analytics_agent",
    "confidence": 0.92,
    "reasoning": "用户询问发电量数据并要求环比分析，涉及经营数据查询，应由Analytics Agent处理",
    "requires_clarification": false,
    "clarification_questions": [],
    "slot_extraction": {
        "metric": "发电量",
        "time_range": "本月",
        "comparison": "上月"
    }
}
```

## 示例 3

用户问题：帮我审查一下这份采购合同的风险条款

分析：
- 审查合同风险条款
- 属于合同审查

输出：
```json
{
    "intent_type": "contract_review",
    "business_domain": "contract",
    "routing_target": "contract_agent",
    "confidence": 0.94,
    "reasoning": "用户明确要求审查合同风险条款，属于合同审查范畴，应由Contract Agent处理",
    "requires_clarification": true,
    "clarification_questions": ["请提供要审查的合同文件或合同ID"],
    "slot_extraction": {
        "contract_type": "采购合同"
    }
}
```

## 示例 4

用户问题：动火作业的安全操作规程是什么？

分析：
- 询问安全操作规程
- 属于安全生产知识

输出：
```json
{
    "intent_type": "rag_qa",
    "business_domain": "safety",
    "routing_target": "rag_agent",
    "confidence": 0.96,
    "reasoning": "用户询问动火作业安全操作规程，属于安全生产知识问答，应由RAG Agent处理",
    "requires_clarification": false,
    "clarification_questions": [],
    "slot_extraction": {}
}
```

## 示例 5

用户问题：你好

分析：
- 简单问候
- 无明确业务目的

输出：
```json
{
    "intent_type": "general_chat",
    "business_domain": null,
    "routing_target": "rag_agent",
    "confidence": 0.98,
    "reasoning": "用户发送问候语，属于通用聊天，应由RAG Agent处理",
    "requires_clarification": false,
    "clarification_questions": [],
    "slot_extraction": {}
}
```

## 示例 6

用户问题：设备故障了怎么办

分析：
- 询问设备故障处理
- 属于设备检修问答

输出：
```json
{
    "intent_type": "rag_qa",
    "business_domain": "equipment",
    "routing_target": "rag_agent",
    "confidence": 0.88,
    "reasoning": "用户询问设备故障处理方法，属于设备检修知识问答，应由RAG Agent处理",
    "requires_clarification": false,
    "clarification_questions": [],
    "slot_extraction": {
        "fault_type": "设备故障"
    }
}
```

## 示例 7

用户问题：各分公司一季度营收情况怎么样？

分析：
- 询问营收数据
- 涉及多维度经营分析
- 需要 SQL 查询

输出：
```json
{
    "intent_type": "analytics_query",
    "business_domain": null,
    "routing_target": "analytics_agent",
    "confidence": 0.91,
    "reasoning": "用户询问各分公司营收情况，涉及经营数据汇总分析，应由Analytics Agent处理",
    "requires_clarification": false,
    "clarification_questions": [],
    "slot_extraction": {
        "metric": "营收",
        "time_range": "一季度",
        "org_scope": "各分公司"
    }
}
```"""

    @classmethod
    def build_prompt(cls, query: str, history: Optional[list[dict]] = None) -> str:
        """构建完整的提示词"""
        parts = [
            cls.SYSTEM_PROMPT,
            cls.FEW_SHOT_EXAMPLES,
            "## 当前用户问题\n\n",
        ]

        # 添加历史上下文
        if history and len(history) > 0:
            history_context = "\n## 对话历史\n\n"
            for i, h in enumerate(history[-3:], 1):  # 最多取最近3轮
                role = h.get("role", "user")
                content = h.get("content", "")
                history_context += f"{i}. {role}: {content}\n"
            parts.append(history_context)

        parts.append(f"用户问题：{query}\n\n")
        parts.append("## 分析与输出\n\n请按照上述示例格式进行分析并输出 JSON 结果：")

        return "\n".join(parts)


# ============================================================================
# LLM 意图检测器
# ============================================================================

class LLMIntentDetector:
    """
    基于 LLM 的意图检测器

    设计特点：
    1. Few-shot Prompting - 通过示例提升准确率
    2. Chain-of-Thought - 要求模型先推理再结论
    3. 结构化输出 - Pydantic 验证输出格式
    4. 缓存优化 - 避免重复调用 LLM
    5. 规则兜底 - LLM 不可用时降级
    """

    # 缓存配置
    CACHE_TTL = 3600  # 缓存 1 小时
    CACHE_MAX_SIZE = 10000

    def __init__(
        self,
        llm_gateway: Any,
        cache: Any | None = None,
        enable_few_shot: bool = True,
        enable_cot: bool = True,
        enable_cache: bool = True,
        fallback_to_rules: bool = True,
    ) -> None:
        """
        初始化 LLM 意图检测器

        Args:
            llm_gateway: LLM 网关实例
            cache: 缓存客户端（Redis 等）
            enable_few_shot: 是否启用 Few-shot
            enable_cot: 是否启用 Chain-of-Thought
            enable_cache: 是否启用缓存
            fallback_to_rules: LLM 失败时是否降级到规则
        """
        self.llm_gateway = llm_gateway
        self.cache = cache
        self.enable_few_shot = enable_few_shot
        self.enable_cot = enable_cot
        self.enable_cache = enable_cache and cache is not None
        self.fallback_to_rules = fallback_to_rules

        # 规则兜底检测器
        self._rule_detector: Optional[RuleBasedIntentDetector] = None

    @property
    def rule_detector(self) -> "RuleBasedIntentDetector":
        """懒加载规则检测器"""
        if self._rule_detector is None:
            from core.agent.intent_detector import IntentDetector
            self._rule_detector = IntentDetector()
        return self._rule_detector

    def _get_cache_key(self, query: str, history: Optional[list[dict]] = None) -> str:
        """生成缓存 key"""
        content = query + ("|".join([h.get("content", "") for h in (history or [])]))
        hash_key = hashlib.md5(content.encode()).hexdigest()[:16]
        return f"intent_detect:{hash_key}"

    async def _get_from_cache(self, cache_key: str) -> Optional[IntentOutput]:
        """从缓存获取结果"""
        if not self.enable_cache or self.cache is None:
            return None

        try:
            cached = await self.cache.get(cache_key)
            if cached:
                logger.debug(f"Intent cache hit: {cache_key}")
                return IntentOutput.model_validate_json(cached)
        except Exception as e:
            logger.warning(f"Cache get error: {e}")

        return None

    async def _save_to_cache(self, cache_key: str, result: IntentOutput) -> None:
        """保存结果到缓存"""
        if not self.enable_cache or self.cache is None:
            return

        try:
            await self.cache.setex(
                cache_key,
                self.CACHE_TTL,
                result.model_dump_json()
            )
        except Exception as e:
            logger.warning(f"Cache set error: {e}")

    def _build_messages(self, query: str, history: Optional[list[dict]] = None) -> list[dict]:
        """构建 LLM 消息列表"""
        prompt = IntentPromptTemplate.build_prompt(query, history)

        messages = [
            {"role": "system", "content": "你是一个企业智能问答系统的意图识别专家。"},
            {"role": "user", "content": prompt},
        ]

        return messages

    def _parse_llm_response(self, content: str) -> IntentOutput:
        """解析 LLM 响应"""
        # 尝试提取 JSON
        json_match = re.search(
            r"\{[\s\S]*\}" if "```json" not in content else r"(?:```json)?\s*(\{[\s\S]*?\})\s*(?:```)?",
            content
        )

        if json_match:
            json_str = json_match.group(1) if "```json" not in content else json_match.group(0)
            try:
                data = __import__("json").loads(json_str)
                return IntentOutput.model_validate(data)
            except Exception as e:
                logger.warning(f"JSON parse error: {e}, content: {content[:200]}")

        # 解析失败，抛出异常触发降级
        raise ValueError(f"无法解析 LLM 输出: {content[:200]}")

    def _fallback_to_rules(self, query: str) -> IntentOutput:
        """降级到规则检测"""
        logger.info(f"LLM 意图识别失败，降级到规则检测")

        result = self.rule_detector.detect(query)

        # 转换为 IntentOutput
        from core.agent.intent_detector import IntentResult

        intent_output = IntentOutput(
            intent_type=IntentType(result.intent_type.value),
            business_domain=BusinessDomain(result.business_domain or "unknown"),
            routing_target=result.routing_target,
            confidence=result.confidence,
            reasoning=f"[规则兜底] {result.message or '基于关键词规则识别'}",
            requires_clarification=result.requires_clarification,
            clarification_questions=result.clarification_questions,
            slot_extraction={k: v.value for k, v in result.slots.slots.items()} if result.slots.slots else {},
        )

        return intent_output

    async def detect(
        self,
        query: str,
        conversation_history: Optional[list[dict]] = None,
    ) -> IntentOutput:
        """
        检测用户意图

        Args:
            query: 用户查询
            conversation_history: 对话历史

        Returns:
            IntentOutput: 意图识别结果
        """
        # 1. 缓存查询
        if self.enable_cache:
            cache_key = self._get_cache_key(query, conversation_history)
            cached = await self._get_from_cache(cache_key)
            if cached:
                return cached

        try:
            # 2. 构建消息
            messages = self._build_messages(query, conversation_history)

            # 3. 调用 LLM
            from core.llm.models import LLMMessage

            llm_messages = [LLMMessage(role=m["role"], content=m["content"]) for m in messages]

            response = self.llm_gateway.chat(
                messages=llm_messages,
                temperature=0.1,  # 低温度保证稳定性
                metadata={
                    "component": "intent_detector",
                    "prompt_name": "intent_classification",
                },
            )

            # 4. 解析响应
            result = self._parse_llm_response(response.content)

            # 5. 保存缓存
            if self.enable_cache:
                await self._save_to_cache(cache_key, result)

            return result

        except Exception as e:
            logger.error(f"LLM 意图识别异常: {e}")

            if self.fallback_to_rules:
                return self._fallback_to_rules(query)
            else:
                # 返回默认结果
                return IntentOutput(
                    intent_type=IntentType.RAG_QA,
                    business_domain=None,
                    routing_target="rag_agent",
                    confidence=0.0,
                    reasoning=f"意图识别失败: {str(e)}",
                    requires_clarification=False,
                    clarification_questions=[],
                    slot_extraction={},
                )


# ============================================================================
# 规则兜底检测器（复用现有 intent_detector）
# ============================================================================

class RuleBasedIntentDetector:
    """
    基于规则的意图检测器

    作为 LLM 检测器的兜底方案。
    """

    def __init__(self) -> None:
        from core.agent.intent_detector import IntentDetector
        self._detector = IntentDetector()

    def detect(
        self,
        query: str,
        conversation_history: Optional[list[dict]] = None,
    ):
        """检测意图"""
        return self._detector.detect(query, conversation_history)


# ============================================================================
# 混合意图检测器（生产推荐）
# ============================================================================

class HybridIntentDetector:
    """
    混合意图检测器

    结合 LLM 和规则的优点：
    1. 优先使用 LLM 进行意图识别
    2. LLM 不可用或置信度低时降级到规则
    3. 支持缓存加速
    4. 支持异步调用

    使用示例：
    ```python
    detector = HybridIntentDetector(
        llm_gateway=llm_gateway,
        cache=redis_client,
    )

    result = await detector.detect("本月光伏发电量是多少？")
    ```
    """

    # 低置信度阈值，低于此值触发规则兜底
    LOW_CONFIDENCE_THRESHOLD = 0.6

    def __init__(
        self,
        llm_gateway: Any,
        cache: Any | None = None,
        llm_confidence_threshold: float = 0.0,
        enable_cache: bool = True,
        enable_rule_fallback: bool = True,
    ) -> None:
        """
        初始化混合意图检测器

        Args:
            llm_gateway: LLM 网关实例
            cache: 缓存客户端
            llm_confidence_threshold: LLM 置信度阈值，低于此值触发规则兜底
            enable_cache: 是否启用缓存
            enable_rule_fallback: 是否启用规则兜底
        """
        self.llm_detector = LLMIntentDetector(
            llm_gateway=llm_gateway,
            cache=cache,
            enable_cache=enable_cache,
            fallback_to_rules=False,  # 我们自己处理兜底
        )

        self.llm_confidence_threshold = llm_confidence_threshold
        self.enable_rule_fallback = enable_rule_fallback

        # 规则兜底检测器
        self._rule_detector: Optional[RuleBasedIntentDetector] = None

    @property
    def rule_detector(self) -> RuleBasedIntentDetector:
        """懒加载规则检测器"""
        if self._rule_detector is None:
            self._rule_detector = RuleBasedIntentDetector()
        return self._rule_detector

    async def detect(
        self,
        query: str,
        conversation_history: Optional[list[dict]] = None,
    ) -> IntentOutput:
        """
        检测用户意图

        Args:
            query: 用户查询
            conversation_history: 对话历史

        Returns:
            IntentOutput: 意图识别结果
        """
        try:
            # 1. 优先使用 LLM 检测
            result = await self.llm_detector.detect(query, conversation_history)

            # 2. 检查置信度
            if (result.confidence < self.LOW_CONFIDENCE_THRESHOLD and
                self.enable_rule_fallback):
                logger.info(
                    f"LLM 置信度过低 ({result.confidence:.2f})，"
                    f"触发规则兜底: {query[:50]}"
                )

                rule_result = self.rule_detector.detect(query, conversation_history)

                # 如果规则结果置信度更高，使用规则结果
                if rule_result.confidence > result.confidence:
                    from core.agent.intent_detector import IntentResult

                    result = IntentOutput(
                        intent_type=IntentType(rule_result.intent_type.value),
                        business_domain=BusinessDomain(
                            rule_result.business_domain or "unknown"
                        ),
                        routing_target=rule_result.routing_target,
                        confidence=rule_result.confidence,
                        reasoning=f"[规则兜底] {result.reasoning}",
                        requires_clarification=rule_result.requires_clarification,
                        clarification_questions=rule_result.clarification_questions,
                        slot_extraction={
                            k: v.value
                            for k, v in rule_result.slots.slots.items()
                        } if rule_result.slots.slots else {},
                    )

            return result

        except Exception as e:
            logger.error(f"混合意图识别异常: {e}")

            if self.enable_rule_fallback:
                return self.llm_detector._fallback_to_rules(query)
            else:
                return IntentOutput(
                    intent_type=IntentType.RAG_QA,
                    business_domain=None,
                    routing_target="rag_agent",
                    confidence=0.0,
                    reasoning=f"意图识别异常: {str(e)}",
                    requires_clarification=False,
                    clarification_questions=[],
                    slot_extraction={},
                )


# ============================================================================
# 便捷函数
# ============================================================================

async def detect_intent_with_llm(
    query: str,
    llm_gateway: Any,
    cache: Any | None = None,
    conversation_history: Optional[list[dict]] = None,
) -> IntentOutput:
    """
    使用 LLM 检测意图的便捷函数

    Args:
        query: 用户查询
        llm_gateway: LLM 网关
        cache: 缓存客户端
        conversation_history: 对话历史

    Returns:
        IntentOutput: 意图识别结果
    """
    detector = HybridIntentDetector(
        llm_gateway=llm_gateway,
        cache=cache,
    )
    return await detector.detect(query, conversation_history)
