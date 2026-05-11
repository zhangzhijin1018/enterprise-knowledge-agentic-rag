"""
纯 LLM 意图检测器测试

测试 LLM 意图检测的核心功能
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
import json


class TestLLMIntentDetector:
    """测试纯 LLM 意图检测器"""

    @pytest.fixture
    def mock_llm_gateway(self):
        """创建模拟 LLM 网关"""
        gateway = MagicMock()

        # 预定义的响应映射
        responses = {
            "本月光伏发电量是多少？": {
                "intent_type": "analytics_query",
                "business_domain": "new_energy",
                "routing_target": "analytics_agent",
                "confidence": 0.92,
                "reasoning": "用户询问发电量数据，涉及经营指标查询",
                "requires_clarification": False,
                "clarification_questions": [],
                "extracted_slots": {"metric": "发电量", "time_range": "本月"},
                "context_dependency": "none",
                "refers_to_previous": False,
                "previous_intent_inherited": None
            },
            "还有呢": {
                "intent_type": "analytics_query",
                "business_domain": "analytics",
                "routing_target": "analytics_agent",
                "confidence": 0.85,
                "reasoning": "用户说继续，应继承上一轮的分析意图",
                "requires_clarification": False,
                "clarification_questions": [],
                "extracted_slots": {},
                "context_dependency": "high",
                "refers_to_previous": True,
                "previous_intent_inherited": "analytics_query"
            },
            "请帮我审查这份采购合同的风险条款": {
                "intent_type": "contract_review",
                "business_domain": "contract",
                "routing_target": "contract_agent",
                "confidence": 0.88,
                "reasoning": "用户要求审查合同，属于合同审查范畴",
                "requires_clarification": False,
                "clarification_questions": [],
                "extracted_slots": {"contract_type": "采购合同"},
                "context_dependency": "none",
                "refers_to_previous": False,
                "previous_intent_inherited": None
            },
            "请告诉我动火作业的安全操作规程": {
                "intent_type": "rag_qa",
                "business_domain": "safety",
                "routing_target": "rag_agent",
                "confidence": 0.95,
                "reasoning": "用户询问安全操作规程，属于安全生产知识问答",
                "requires_clarification": False,
                "clarification_questions": [],
                "extracted_slots": {"topic": "动火作业"},
                "context_dependency": "none",
                "refers_to_previous": False,
                "previous_intent_inherited": None
            },
            "请问斗轮机故障怎么排查": {
                "intent_type": "rag_qa",
                "business_domain": "equipment",
                "routing_target": "rag_agent",
                "confidence": 0.90,
                "reasoning": "用户询问设备故障排查，属于设备检修知识问答",
                "requires_clarification": False,
                "clarification_questions": [],
                "extracted_slots": {},
                "context_dependency": "none",
                "refers_to_previous": False,
                "previous_intent_inherited": None
            },
        }

        async def mock_chat(messages, temperature=0.1, metadata=None):
            # 从消息中提取用户查询
            user_query = ""
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    # 找到 "## 当前用户问题" 后面的内容
                    content = msg.get("content", "")
                    if "## 当前用户问题" in content:
                        parts = content.split("## 当前用户问题")
                        if len(parts) > 1:
                            next_part = parts[1].split("##")[0].strip()
                            user_query = next_part
                    else:
                        user_query = content[:50]
                    break

            # 查找匹配的响应
            response_data = responses.get(user_query, responses.get("本月光伏发电量是多少？"))

            # 包装成响应对象
            class MockResponse:
                content = f"```json\n{json.dumps(response_data, ensure_ascii=False)}\n```"

            return MockResponse()

        gateway.chat = AsyncMock(side_effect=mock_chat)
        return gateway

    @pytest.mark.asyncio
    async def test_basic_analytics_query(self, mock_llm_gateway):
        """测试基础经营分析查询"""
        from core.agent.llm_only_intent_detector import LLMIntentDetector

        detector = LLMIntentDetector(llm_gateway=mock_llm_gateway)
        result = await detector.detect("本月光伏发电量是多少？")

        assert result.intent_type.value == "analytics_query"
        assert result.business_domain.value == "new_energy"
        assert result.routing_target == "analytics_agent"
        assert result.confidence >= 0.8
        assert "metric" in result.extracted_slots

    @pytest.mark.asyncio
    async def test_context_inheritance(self, mock_llm_gateway):
        """测试上下文继承"""
        from core.agent.llm_only_intent_detector import LLMIntentDetector

        detector = LLMIntentDetector(llm_gateway=mock_llm_gateway)
        result = await detector.detect(
            query="还有呢",
            previous_intent="analytics_query",
            previous_slots={"metric": "发电量", "time_range": "本月"},
        )

        # LLM 应该能识别这是继承意图
        assert result.refers_to_previous is True or result.context_dependency in ["medium", "high"]

    @pytest.mark.asyncio
    async def test_contract_review(self, mock_llm_gateway):
        """测试合同审查"""
        from core.agent.llm_only_intent_detector import LLMIntentDetector

        detector = LLMIntentDetector(llm_gateway=mock_llm_gateway)
        result = await detector.detect("请帮我审查这份采购合同的风险条款")

        assert result.intent_type.value == "contract_review"
        assert result.business_domain.value == "contract"
        assert result.routing_target == "contract_agent"

    @pytest.mark.asyncio
    async def test_safety_qa(self, mock_llm_gateway):
        """测试安全知识问答"""
        from core.agent.llm_only_intent_detector import LLMIntentDetector

        detector = LLMIntentDetector(llm_gateway=mock_llm_gateway)
        result = await detector.detect("请告诉我动火作业的安全操作规程")

        assert result.intent_type.value == "rag_qa"
        assert result.business_domain.value == "safety"
        assert result.routing_target == "rag_agent"

    @pytest.mark.asyncio
    async def test_equipment_qa(self, mock_llm_gateway):
        """测试设备问答"""
        from core.agent.llm_only_intent_detector import LLMIntentDetector

        detector = LLMIntentDetector(llm_gateway=mock_llm_gateway)
        result = await detector.detect("请问斗轮机故障怎么排查")

        assert result.intent_type.value == "rag_qa"
        assert result.business_domain.value == "equipment"

    @pytest.mark.asyncio
    async def test_conversation_history(self, mock_llm_gateway):
        """测试带历史记录的意图检测"""
        from core.agent.llm_only_intent_detector import LLMIntentDetector

        history = [
            {"role": "user", "content": "本月光伏发电量是多少？"},
            {"role": "assistant", "content": "本月光伏发电量为 1234 万千瓦时。"},
        ]

        detector = LLMIntentDetector(llm_gateway=mock_llm_gateway)
        result = await detector.detect(
            query="和上月相比呢？",
            conversation_history=history,
        )

        # 应该有上下文感知
        assert result.context_dependency in ["none", "low", "medium", "high"]

    @pytest.mark.asyncio
    async def test_fallback_on_llm_error(self):
        """测试 LLM 失败时的兜底"""
        from core.agent.llm_only_intent_detector import LLMIntentDetector

        # 创建会失败的 LLM 网关
        gateway = MagicMock()
        gateway.chat = AsyncMock(side_effect=Exception("LLM Error"))

        detector = LLMIntentDetector(llm_gateway=gateway)
        result = await detector.detect("本月光伏发电量是多少？")

        # 应该返回兜底结果
        assert result.intent_type.value == "rag_qa"  # 默认
        assert result.confidence == 0.3  # 低置信度


class TestIntentPromptEngine:
    """测试提示词引擎"""

    def test_build_prompt_basic(self):
        """测试基础提示词构建"""
        from core.agent.llm_only_intent_detector import IntentPromptEngine

        prompt = IntentPromptEngine.build_prompt(
            query="本月光伏发电量是多少？"
        )

        assert "新疆能源集团" in prompt
        assert "意图类型" in prompt
        assert "本月光伏发电量是多少？" in prompt

    def test_build_prompt_with_context(self):
        """测试带上下文的提示词构建"""
        from core.agent.llm_only_intent_detector import IntentPromptEngine

        prompt = IntentPromptEngine.build_prompt(
            query="继续",
            previous_intent="analytics_query",
            previous_slots={"metric": "发电量"},
            conversation_history=[
                {"role": "user", "content": "本月光伏发电量是多少？"},
                {"role": "assistant", "content": "1234万千瓦时"},
            ]
        )

        assert "上一轮意图" in prompt
        assert "对话历史" in prompt
        assert "继续" in prompt


class TestConfidenceThreshold:
    """测试置信度阈值"""

    def test_confidence_levels(self):
        """测试置信度级别"""
        from core.agent.llm_only_intent_detector import LLMIntentDetector

        assert LLMIntentDetector.HIGH_CONFIDENCE == 0.80
        assert LLMIntentDetector.MEDIUM_CONFIDENCE == 0.50
        assert LLMIntentDetector.LOW_CONFIDENCE == 0.30


class TestIntentPredictionModel:
    """测试意图预测模型"""

    def test_model_creation(self):
        """测试模型创建"""
        from core.agent.llm_only_intent_detector import IntentPrediction, IntentType, BusinessDomain

        prediction = IntentPrediction(
            intent_type=IntentType.RAG_QA,
            business_domain=BusinessDomain.SAFETY,
            routing_target="rag_agent",
            confidence=0.95,
            reasoning="测试推理",
            requires_clarification=False,
            clarification_questions=[],
            extracted_slots={"topic": "安全"},
            context_dependency="none",
            refers_to_previous=False,
            previous_intent_inherited=None,
        )

        assert prediction.intent_type == IntentType.RAG_QA
        assert prediction.business_domain == BusinessDomain.SAFETY
        assert prediction.confidence == 0.95


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
