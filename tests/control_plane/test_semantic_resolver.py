"""SemanticResolver 测试。"""

from __future__ import annotations

from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.control_plane.semantic_resolver import SemanticResolver
from core.analytics.metric_catalog import MetricCatalog
from core.config.settings import Settings


def test_semantic_resolver_inherits_context_for_compare_query() -> None:
    """多轮表达“再看一下同比”时应继承已有上下文。"""

    resolver = SemanticResolver(metric_catalog=MetricCatalog())

    result = resolver.resolve(
        query="再看一下同比",
        conversation_memory={
            "last_metric": "发电量",
            "last_time_range": {
                "label": "上个月",
                "start_date": "2024-03-01",
                "end_date": "2024-03-31",
            },
            "last_org_scope": {"type": "region", "value": "新疆区域"},
            "short_term_memory": {
                "last_group_by": "station",
                "last_compare_target": None,
            },
        },
    )

    assert result.slots["metric"] == "发电量"
    assert result.slots["time_range"]["label"] == "上个月"
    assert result.slots["compare_target"] == "yoy"
    assert result.slots["group_by"] == "station"


def test_semantic_resolver_supports_org_scope_switch() -> None:
    """“新疆换成北疆”应覆盖组织范围并继承其他关键槽位。"""

    resolver = SemanticResolver(metric_catalog=MetricCatalog())

    result = resolver.resolve(
        query="新疆换成北疆",
        conversation_memory={
            "last_metric": "发电量",
            "last_time_range": {
                "label": "上个月",
                "start_date": "2024-03-01",
                "end_date": "2024-03-31",
            },
            "last_org_scope": {"type": "region", "value": "新疆区域"},
            "short_term_memory": {},
        },
    )

    assert result.slots["metric"] == "发电量"
    assert result.slots["org_scope"]["value"] == "北疆区域"


def test_semantic_resolver_can_use_llm_fallback_for_low_confidence_query() -> None:
    """低置信问题应允许走 LLM fallback 做结构化补强。"""

    def mock_planner_callable(*, query: str, current_slots: dict, conversation_memory: dict) -> dict:
        return {
            "slots": {"metric": "利润"},
            "confidence": 0.9,
            "source": "mock_llm",
            "should_use": True,
        }

    resolver = SemanticResolver(
        metric_catalog=MetricCatalog(),
        llm_planner_gateway=LLMAnalyticsPlannerGateway(
            settings=Settings(analytics_planner_enable_llm_fallback=True),
            planner_callable=mock_planner_callable,
        ),
    )

    result = resolver.resolve(
        query="最近经营表现怎么样",
        conversation_memory={},
    )

    assert result.slots["metric"] == "利润"
    assert result.planning_source == "rule+mock_llm"
