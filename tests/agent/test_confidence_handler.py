"""
置信度自适应处理器测试
"""

import pytest
from dataclasses import dataclass, field
from enum import Enum


class TestConfidenceThresholds:
    """测试置信度阈值"""

    def test_default_thresholds(self):
        """测试默认阈值"""
        from core.agent.confidence_handler import ConfidenceThresholds

        thresholds = ConfidenceThresholds()

        assert thresholds.EXECUTE_IMMEDIATELY == 0.80
        assert thresholds.EXECUTE_WITH_CAUTION == 0.60
        assert thresholds.NEEDS_CLARIFICATION == 0.40
        assert thresholds.NEEDS_FALLBACK == 0.25

    def test_high_risk_domains(self):
        """测试高风险域"""
        from core.agent.confidence_handler import ConfidenceThresholds

        thresholds = ConfidenceThresholds()

        assert "contract" in thresholds.HIGH_RISK_DOMAINS
        assert "safety" in thresholds.HIGH_RISK_DOMAINS
        assert "analytics" in thresholds.HIGH_RISK_DOMAINS

    def test_domain_specific_threshold(self):
        """测试业务域特定阈值"""
        from core.agent.confidence_handler import ConfidenceThresholds

        thresholds = ConfidenceThresholds()

        # 高风险域应该要求更高置信度
        contract_threshold = thresholds.get_threshold_for_domain("contract")
        normal_threshold = thresholds.get_threshold_for_domain("policy")

        assert contract_threshold > normal_threshold


class TestHandlingStrategy:
    """测试处理策略"""

    def test_strategy_values(self):
        """测试策略枚举值"""
        from core.agent.confidence_handler import HandlingStrategy

        assert HandlingStrategy.EXECUTE_IMMEDIATELY.value == "execute_immediately"
        assert HandlingStrategy.EXECUTE_WITH_CAUTION.value == "execute_with_caution"
        assert HandlingStrategy.REQUEST_CLARIFICATION.value == "request_clarification"
        assert HandlingStrategy.MULTI_INTENT_CANDIDATES.value == "multi_intent_candidates"
        assert HandlingStrategy.FALLBACK_TO_RULES.value == "fallback_to_rules"


class MockIntentPrediction:
    """模拟意图预测"""
    def __init__(
        self,
        intent_type: str = "rag_qa",
        confidence: float = 0.8,
        reasoning: str = "测试推理",
        slots: dict = None,
        clarification_questions: list = None,
    ):
        self.intent_type = intent_type if hasattr(intent_type, 'value') else type('obj', (object,), {'value': intent_type})()
        self.confidence = confidence
        self.reasoning = reasoning
        self.extracted_slots = slots or {}
        self.clarification_questions = clarification_questions or []


class TestConfidenceHandler:
    """测试置信度处理器"""

    def setup_method(self):
        from core.agent.confidence_handler import ConfidenceHandler
        self.handler = ConfidenceHandler()

    def test_high_confidence_execute_immediately(self):
        """测试高置信度立即执行"""
        prediction = MockIntentPrediction(
            intent_type="rag_qa",
            confidence=0.90,
        )

        decision = self.handler.handle(
            intent_prediction=prediction,
            user_query="本月光伏发电量是多少？",
        )

        assert decision.can_execute is True
        assert decision.strategy.value == "execute_immediately"
        assert decision.confidence == 0.90

    def test_medium_confidence_execute_with_caution(self):
        """测试中等置信度谨慎执行"""
        prediction = MockIntentPrediction(
            intent_type="analytics_query",
            confidence=0.65,
        )

        decision = self.handler.handle(
            intent_prediction=prediction,
            user_query="帮我分析一下",
        )

        assert decision.can_execute is True
        assert decision.strategy.value in ["execute_with_caution", "request_clarification"]

    def test_low_confidence_request_clarification(self):
        """测试低置信度请求澄清"""
        prediction = MockIntentPrediction(
            intent_type="analytics_query",
            confidence=0.30,  # < 0.40 触发澄清
            clarification_questions=["请问您想查询什么指标？"],
        )

        decision = self.handler.handle(
            intent_prediction=prediction,
            user_query="帮我分析",
        )

        assert decision.can_execute is False
        assert decision.strategy.value in ["request_clarification", "multi_intent_candidates"]
        assert len(decision.clarification_questions) > 0

    def test_very_low_confidence_multi_intent(self):
        """测试很低置信度多意图候选"""
        prediction = MockIntentPrediction(
            intent_type="rag_qa",
            confidence=0.20,
        )

        decision = self.handler.handle(
            intent_prediction=prediction,
            user_query="看看",
        )

        assert decision.can_execute is False
        assert decision.strategy.value in ["multi_intent_candidates", "request_clarification"]

    def test_high_risk_domain_higher_threshold(self):
        """测试高风险域要求更高阈值"""
        # 合同审查，中等置信度
        prediction = MockIntentPrediction(
            intent_type="contract_review",
            confidence=0.70,
        )

        decision = self.handler.handle(
            intent_prediction=prediction,
            user_query="帮我看看这个合同",
            business_domain="contract",
            risk_level="high",
        )

        # 高风险域应该要求澄清
        assert decision.can_execute is False or decision.risk_warning is not None

    def test_identify_missing_slots(self):
        """测试缺失槽位识别"""
        prediction = MockIntentPrediction(
            intent_type="analytics_query",
            confidence=0.50,
            slots={},  # 缺少 metric 和 time_range
        )

        decision = self.handler.handle(
            intent_prediction=prediction,
            user_query="帮我分析",
        )

        # 应该识别到缺失的槽位
        assert "metric" in decision.missing_slots or "time_range" in decision.missing_slots


class TestIncrementalContextRequester:
    """测试增量信息请求器"""

    def setup_method(self):
        from core.agent.confidence_handler import IncrementalContextRequester
        self.requester = IncrementalContextRequester()

    def test_generate_time_range_question(self):
        """测试时间范围追问"""
        prediction = MockIntentPrediction(
            intent_type="analytics_query",
            confidence=0.50,
            slots={},
        )

        questions = self.requester.generate_incremental_questions(
            user_query="帮我分析发电量",
            prediction=prediction,
        )

        assert len(questions) > 0
        # 应该包含时间范围的追问
        has_time_question = any("时间" in q for q in questions)
        has_metric_question = any("指标" in q for q in questions)
        assert has_time_question or has_metric_question

    def test_identify_fuzzy_slots(self):
        """测试模糊槽位识别"""
        # 包含"本月"
        fuzzy_slots = self.requester._identify_fuzzy_slots("本月发电量是多少？")
        assert "time_range" in fuzzy_slots

        # 包含"多少"
        fuzzy_slots = self.requester._identify_fuzzy_slots("收入有多少？")
        assert "metric" in fuzzy_slots or "quantity" in fuzzy_slots


class TestHandlingDecision:
    """测试处理决策"""

    def test_decision_to_dict(self):
        """测试决策转字典"""
        from core.agent.confidence_handler import HandlingDecision, HandlingStrategy

        decision = HandlingDecision(
            strategy=HandlingStrategy.EXECUTE_IMMEDIATELY,
            confidence=0.90,
            threshold_used=0.80,
            can_execute=True,
        )

        d = decision.to_dict()

        assert d["strategy"] == "execute_immediately"
        assert d["confidence"] == 0.90
        assert d["can_execute"] is True


class TestFallbackWithRules:
    """测试降级到规则"""

    def test_fallback_when_llm_low_confidence(self):
        """测试 LLM 低置信度时降级到规则"""
        from core.agent.confidence_handler import ConfidenceHandler

        # 模拟规则检测器
        class MockRuleDetector:
            def detect(self, query):
                return MockIntentPrediction(
                    intent_type="rag_qa",
                    confidence=0.70,  # 规则置信度更高
                    reasoning="规则检测结果",
                )

        handler = ConfidenceHandler(fallback_detector=MockRuleDetector())

        # LLM 返回极低置信度
        prediction = MockIntentPrediction(
            intent_type="rag_qa",
            confidence=0.15,
        )

        decision = handler.handle(
            intent_prediction=prediction,
            user_query="看看",
        )

        # 应该降级到规则
        assert decision.strategy.value in [
            "fallback_to_rules",
            "request_clarification"
        ]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
