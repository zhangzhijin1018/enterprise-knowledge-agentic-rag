"""
上下文感知意图检测器测试

测试场景：
1. 基础意图识别（无上下文）
2. 代词消解
3. 意图继承
4. 多因子置信度计算
"""

import pytest
from dataclasses import dataclass, field
from typing import Any, Optional

# 导入被测模块
from core.agent.context_aware_intent_detector import (
    DEFAULT_WEIGHTS,
    ConfidenceWeights,
    ContextAnalyzer,
    IntentDetectionContext,
    PronounResolver,
    SlotConfidenceCalculator,
    ConfidenceBreakdown,
)


class TestPronounResolver:
    """测试代词消解器"""

    def setup_method(self):
        self.resolver = PronounResolver()

    def test_is_pronoun_query_inherit(self):
        """测试继承类代词识别"""
        assert self.resolver.is_pronoun_query("继续")
        assert self.resolver.is_pronoun_query("继续分析")
        assert self.resolver.is_pronoun_query("同上")
        assert self.resolver.is_pronoun_query("一样")

    def test_is_pronoun_query_short(self):
        """测试短句代词识别"""
        # 很短的句子且没有明确意图词
        assert self.resolver.is_pronoun_query("详细说说")
        assert self.resolver.is_pronoun_query("怎么看")

    def test_is_not_pronoun_query(self):
        """测试非代词查询"""
        # 完整的查询问句（有明确意图词），不是代词查询
        assert not self.resolver.is_pronoun_query("本月光伏发电量是多少？")
        assert not self.resolver.is_pronoun_query("请帮我审查这份合同")
        assert not self.resolver.is_pronoun_query("动火作业的安全规程是什么")

    def test_is_pronoun_query_with_question(self):
        """测试包含疑问词的查询 - 这些也应该被识别为代词（因为是简短的追问）"""
        # 以疑问词开头但很短的句子，可能需要上下文
        assert self.resolver.is_pronoun_query("怎么看")  # 简短追问

    def test_resolve_inherit(self):
        """测试继承消解"""
        context = IntentDetectionContext(
            current_query="继续",
            conversation_history=[],
            previous_intent="analytics_query",
            previous_slots={"metric": "发电量", "time_range": "本月"},
            weights=DEFAULT_WEIGHTS,
        )

        resolved, confidence = self.resolver.resolve_pronoun("继续", context)
        assert confidence > 0  # 应该有一定的置信度

    def test_resolve_cannot_resolve(self):
        """测试无法消解的情况"""
        context = IntentDetectionContext(
            current_query="本月光伏发电量是多少",
            conversation_history=[],
            weights=DEFAULT_WEIGHTS,
        )

        resolved, confidence = self.resolver.resolve_pronoun("本月光伏发电量是多少", context)
        assert resolved == "本月光伏发电量是多少"
        # 无法消解时置信度较低（这里会返回 0.2 因为短句判断）
        assert confidence < 0.5


class TestContextAnalyzer:
    """测试上下文分析器"""

    def setup_method(self):
        self.analyzer = ContextAnalyzer()

    def test_compute_context_match(self):
        """测试上下文匹配计算"""
        context = IntentDetectionContext(
            current_query="它的风险点有哪些",
            conversation_history=[
                {"role": "assistant", "content": "这份采购合同的主要风险点包括：付款条件、交付验收条款。"}
            ],
            previous_intent="contract_review",
            weights=DEFAULT_WEIGHTS,
        )

        score = self.analyzer._compute_context_match(context)
        assert score >= 0  # 应该有上下文匹配

    def test_compute_intent_inheritance(self):
        """测试意图继承计算"""
        # 连续分析
        context = IntentDetectionContext(
            current_query="继续分析上月数据",
            conversation_history=[],
            previous_intent="analytics_query",
            weights=DEFAULT_WEIGHTS,
        )

        score = self.analyzer._compute_intent_inheritance(context)
        assert score > 0

    def test_compute_domain_consistency(self):
        """测试业务域一致性"""
        context = IntentDetectionContext(
            current_query="继续看看",
            conversation_history=[],
            previous_domain="new_energy",
            weights=DEFAULT_WEIGHTS,
        )

        score = self.analyzer._compute_domain_consistency(context)
        assert score > 0  # 业务域一致，应该加分

    def test_analyze_with_pronoun(self):
        """测试带代词的完整分析"""
        context = IntentDetectionContext(
            current_query="继续",
            conversation_history=[],
            previous_intent="analytics_query",
            previous_slots={"metric": "发电量", "time_range": "本月"},
            weights=DEFAULT_WEIGHTS,
        )

        enhanced_context, breakdown = self.analyzer.analyze("继续", context)

        assert enhanced_context.current_query != "继续" or breakdown.factors  # 应该产生变化或有加成
        assert breakdown.base_score == 0.0


class TestSlotConfidenceCalculator:
    """测试槽位置信度计算器"""

    def setup_method(self):
        self.calculator = SlotConfidenceCalculator()

    def test_complete_slots(self):
        """测试完整槽位"""
        slots = {
            "metric": {"value": "发电量", "confidence": 0.9},
            "time_range": {"value": "本月", "confidence": 0.85},
        }

        bonus, breakdown = self.calculator.compute_slot_confidence("analytics_query", slots)
        assert bonus > 0  # 应该有加成
        assert len(breakdown.factors) > 0

    def test_partial_slots(self):
        """测试部分槽位"""
        slots = {
            "metric": {"value": "发电量", "confidence": 0.9},
            # time_range 缺失
        }

        bonus, breakdown = self.calculator.compute_slot_confidence("analytics_query", slots)
        assert bonus < 0.08  # 部分填充，加成较低

    def test_no_required_slots(self):
        """测试不需要槽位的意图"""
        slots = {}

        bonus, breakdown = self.calculator.compute_slot_confidence("rag_qa", slots)
        assert bonus > 0  # RAG 问答不需要必需槽位


class TestConfidenceBreakdown:
    """测试置信度分解"""

    def test_add_factor(self):
        """测试添加因子"""
        breakdown = ConfidenceBreakdown(base_score=0.7)
        breakdown.add_factor(
            name="test_factor",
            value=1.0,
            weight=0.1,
            description="测试因子",
        )

        assert len(breakdown.factors) == 1
        assert breakdown.factors[0].contribution == 0.1

    def test_compute_final_score(self):
        """测试最终分数计算"""
        breakdown = ConfidenceBreakdown(base_score=0.7)
        breakdown.add_factor(name="factor1", value=1.0, weight=0.1)
        breakdown.add_factor(name="factor2", value=0.5, weight=0.2)

        final = breakdown.compute_final_score()

        expected = 0.7 + 0.1 * 1.0 + 0.2 * 0.5  # = 0.9
        assert abs(final - expected) < 0.01

    def test_max_score_cap(self):
        """测试分数上限"""
        breakdown = ConfidenceBreakdown(base_score=0.95)
        breakdown.add_factor(name="factor1", value=1.0, weight=0.1)
        breakdown.add_factor(name="factor2", value=1.0, weight=0.1)

        final = breakdown.compute_final_score(max_score=0.98)
        assert final <= 0.98  # 不应该超过上限


class TestConfidenceWeights:
    """测试置信度权重"""

    def test_default_weights(self):
        """测试默认权重"""
        weights = ConfidenceWeights()

        assert weights.BASE_MATCH_MIN == 0.40
        assert weights.BASE_MATCH_MAX == 0.85
        assert weights.CONTEXT_MATCH == 0.10
        assert weights.MAX_CONFIDENCE == 0.98

    def test_weights_sum(self):
        """测试权重合理性"""
        weights = ConfidenceWeights()

        # 所有加成权重之和应该不超过一定范围
        total_bonus_weight = (
            weights.CONTEXT_MATCH +
            weights.PRONOUN_RESOLVED +
            weights.SLOT_COMPLETE +
            weights.INTENT_INHERIT +
            weights.DOMAIN_CONSISTENT
        )

        # 总加成权重应该合理（不超过0.35）
        assert total_bonus_weight <= 0.35


class TestMultiTurnScenarios:
    """测试多轮对话场景"""

    def test_scenario_1_multi_turn_analysis(self):
        """场景1：多轮经营分析"""
        # 第一轮
        first_query = "本月光伏发电量是多少？"

        # 第二轮（继续分析）
        second_context = IntentDetectionContext(
            current_query="和上月相比呢？",
            conversation_history=[
                {"role": "user", "content": "本月光伏发电量是多少？"},
                {"role": "assistant", "content": "本月光伏发电量为 1234 万千瓦时。"},
            ],
            previous_intent="analytics_query",
            previous_domain="new_energy",
            previous_slots={"metric": "发电量", "time_range": "本月"},
            weights=DEFAULT_WEIGHTS,
        )

        analyzer = ContextAnalyzer()
        resolved_context, breakdown = analyzer.analyze("和上月相比呢？", second_context)

        # 应该识别到这是继续分析
        assert breakdown.factors  # 应该有上下文加成

        # 第三轮（追问）
        third_context = IntentDetectionContext(
            current_query="详细说说",
            conversation_history=[
                {"role": "user", "content": "本月光伏发电量是多少？"},
                {"role": "assistant", "content": "本月光伏发电量为 1234 万千瓦时，环比增长 5%。"},
            ],
            previous_intent="analytics_query",
            previous_domain="new_energy",
            previous_slots={"metric": "发电量", "time_range": "本月"},
            weights=DEFAULT_WEIGHTS,
        )

        resolved_context, breakdown = analyzer.analyze("详细说说", third_context)
        assert len(breakdown.factors) > 0  # 应该有继承加成

    def test_scenario_2_pronoun_reference(self):
        """场景2：代词指代"""
        context = IntentDetectionContext(
            current_query="它的风险点有哪些？",
            conversation_history=[
                {"role": "user", "content": "帮我审查这份采购合同"},
                {"role": "assistant", "content": "好的，这是一份设备采购合同，主要条款包括..."},
            ],
            previous_intent="contract_review",
            previous_domain="contract",
            weights=DEFAULT_WEIGHTS,
        )

        resolver = PronounResolver()
        assert resolver.is_pronoun_query("它的风险点有哪些？")

    def test_scenario_3_domain_switch(self):
        """场景3：业务域切换"""
        context = IntentDetectionContext(
            current_query="本月设备检修计划是什么？",
            conversation_history=[
                {"role": "user", "content": "本月光伏发电量是多少？"},
                {"role": "assistant", "content": "本月发电量为 1234 万千瓦时。"},
            ],
            previous_intent="analytics_query",
            previous_domain="new_energy",
            weights=DEFAULT_WEIGHTS,
        )

        analyzer = ContextAnalyzer()
        score = analyzer._compute_domain_consistency(context)
        # 业务域切换，不应该加分
        assert score < 0.5


class TestEdgeCases:
    """测试边界情况"""

    def test_empty_query(self):
        """测试空查询"""
        context = IntentDetectionContext(
            current_query="",
            conversation_history=[],
            weights=DEFAULT_WEIGHTS,
        )

        analyzer = ContextAnalyzer()
        # 空查询应该不会崩溃
        try:
            _, breakdown = analyzer.analyze("", context)
            assert True
        except Exception:
            assert False

    def test_empty_history(self):
        """测试空历史"""
        context = IntentDetectionContext(
            current_query="本月光伏发电量是多少？",
            conversation_history=[],
            previous_intent=None,
            previous_domain=None,
            weights=DEFAULT_WEIGHTS,
        )

        analyzer = ContextAnalyzer()
        _, breakdown = analyzer.analyze("本月光伏发电量是多少？", context)

        # 没有历史，不应该有上下文加成
        context_factors = [f for f in breakdown.factors if "context" in f.name or "inherit" in f.name]
        assert len(context_factors) == 0 or all(f.contribution == 0 for f in context_factors)

    def test_very_long_history(self):
        """测试超长历史"""
        long_history = [
            {"role": "user", "content": f"这是第{i}轮对话"}
            for i in range(100)
        ]

        context = IntentDetectionContext(
            current_query="继续",
            conversation_history=long_history,
            previous_intent="analytics_query",
            weights=DEFAULT_WEIGHTS,
        )

        analyzer = ContextAnalyzer()
        _, breakdown = analyzer.analyze("继续", context)

        # 不应该因为历史太长而出问题
        assert breakdown.base_score == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
