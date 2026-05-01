"""经营分析 LLM slot fallback 测试。"""

from __future__ import annotations

from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.config.settings import Settings
from core.llm import MockLLMGateway


def test_llm_slot_fallback_disabled_does_not_call_gateway() -> None:
    """fallback 默认关闭时不应调用 LLM。"""

    mock_gateway = MockLLMGateway(structured_payload={"slots": {"metric": "收入"}, "should_use": True})
    gateway = LLMAnalyticsPlannerGateway(
        settings=Settings(analytics_planner_enable_llm_fallback=False),
        llm_gateway=mock_gateway,
    )

    result = gateway.enhance_slots(query="最近经营表现", current_slots={}, conversation_memory={})

    assert result.should_use is False
    assert result.source == "disabled"
    assert mock_gateway.calls == []


def test_llm_slot_fallback_uses_mock_gateway_for_valid_slots() -> None:
    """启用 fallback 且模型返回合法 slots 时，应产出安全补强结果。"""

    mock_gateway = MockLLMGateway(
        structured_payload={
            "slots": {
                "metric": "收入",
                "group_by": "month",
                "compare_target": "yoy",
            },
            "clarification_question": None,
            "clarification_target_slots": [],
            "confidence": 0.86,
            "should_use": True,
            "reason": "用户表达为收入同比分析",
        }
    )
    gateway = LLMAnalyticsPlannerGateway(
        settings=Settings(analytics_planner_enable_llm_fallback=True),
        llm_gateway=mock_gateway,
    )

    result = gateway.enhance_slots(query="收入同比看看", current_slots={}, conversation_memory={})

    assert result.should_use is True
    assert result.slots["metric"] == "收入"
    assert result.source == "llm_gateway"
    assert len(mock_gateway.calls) == 1


def test_llm_slot_fallback_rejects_forbidden_keys() -> None:
    """fallback 输出含 SQL 等禁止字段时应弃用，不影响规则主链。"""

    mock_gateway = MockLLMGateway(
        structured_payload={
            "slots": {
                "metric": "收入",
                "raw_sql": "select * from analytics_metrics_daily",
            },
            "confidence": 0.9,
            "should_use": True,
            "reason": "bad",
        }
    )
    gateway = LLMAnalyticsPlannerGateway(
        settings=Settings(analytics_planner_enable_llm_fallback=True),
        llm_gateway=mock_gateway,
    )

    result = gateway.enhance_slots(query="收入同比看看", current_slots={}, conversation_memory={})

    assert result.should_use is False
    assert result.source == "llm_fallback_failed"
    assert "禁止字段" in result.reason


def test_llm_slot_fallback_unknown_metric_becomes_candidate() -> None:
    """非法/未知指标不能直接作为 metric 使用。"""

    mock_gateway = MockLLMGateway(
        structured_payload={
            "slots": {"metric": "神秘指标"},
            "confidence": 0.8,
            "should_use": True,
            "reason": "模型不确定",
        }
    )
    gateway = LLMAnalyticsPlannerGateway(
        settings=Settings(analytics_planner_enable_llm_fallback=True),
        llm_gateway=mock_gateway,
    )

    result = gateway.enhance_slots(query="神秘指标看看", current_slots={}, conversation_memory={})

    assert result.should_use is True
    assert "metric" not in result.slots
    assert result.slots["metric_candidates"] == ["神秘指标"]


def test_llm_slot_fallback_should_use_false_is_not_merged() -> None:
    """should_use=false 时，即使返回 slots，也不能进入规则 Planner 主链。"""

    mock_gateway = MockLLMGateway(
        structured_payload={
            "slots": {"metric": "收入"},
            "confidence": 0.9,
            "should_use": False,
            "reason": "不确定",
        }
    )
    planner = AnalyticsPlanner(
        llm_planner_gateway=LLMAnalyticsPlannerGateway(
            settings=Settings(analytics_planner_enable_llm_fallback=True),
            llm_gateway=mock_gateway,
        )
    )

    plan = planner.plan("最近经营表现怎么样")

    assert "metric" in plan.missing_slots
    assert plan.planning_source == "rule"


def test_llm_slot_fallback_failure_does_not_break_rule_planner() -> None:
    """LLM fallback 失败时，应回退规则结果，不影响主链。"""

    mock_gateway = MockLLMGateway(response_content="不是 JSON")
    planner = AnalyticsPlanner(
        llm_planner_gateway=LLMAnalyticsPlannerGateway(
            settings=Settings(analytics_planner_enable_llm_fallback=True),
            llm_gateway=mock_gateway,
        )
    )

    plan = planner.plan("最近发电表现")

    assert plan.is_executable is True
    assert plan.slots["metric"] == "发电量"
    assert plan.planning_source == "rule"
