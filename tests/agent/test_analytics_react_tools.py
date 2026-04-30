"""Analytics ReAct Tool Registry 测试。"""

from __future__ import annotations

from core.agent.workflows.analytics.react.tools import AnalyticsReactToolRegistry
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.config.settings import Settings


def _tool_registry() -> AnalyticsReactToolRegistry:
    """构造测试用只读 planning 工具注册表。"""

    return AnalyticsReactToolRegistry(
        metric_catalog=MetricCatalog(),
        schema_registry=SchemaRegistry(settings=Settings()),
    )


def test_react_tool_registry_rejects_forbidden_tool() -> None:
    """禁止工具请求必须被拒绝，且不产生副作用。"""

    result = _tool_registry().run(
        tool_name="sql_execute",
        tool_input={"sql": "select 1"},
        conversation_memory={},
    )

    assert result["allowed"] is False
    assert result["reason"] == "tool_not_allowed"


def test_schema_registry_lookup_uses_default_data_source_when_missing() -> None:
    """data_source 为空时应使用默认数据源，不应直接异常。"""

    result = _tool_registry().run(
        tool_name="schema_registry_lookup",
        tool_input={},
        conversation_memory={},
    )

    assert result["allowed"] is True
    assert result["data_source"] == "local_analytics"
    assert "month" in result["group_by_keys"]


def test_schema_registry_lookup_returns_safe_miss_for_unknown_data_source() -> None:
    """未知 data_source 应返回 matched=False，而不是破坏整条链。"""

    result = _tool_registry().run(
        tool_name="schema_registry_lookup",
        tool_input={"data_source": "missing_source"},
        conversation_memory={},
    )

    assert result["allowed"] is True
    assert result["matched"] is False
    assert result["reason"] == "data_source_not_found"


def test_react_tool_registry_cleans_tool_input() -> None:
    """tool_input 会做最小清洗，只保留简单可读字段。"""

    result = _tool_registry().run(
        tool_name="business_term_normalize",
        tool_input={"text": " 收入同比排名 ", "nested": {"danger": object()}},
        conversation_memory={},
    )

    assert result["allowed"] is True
    assert result["normalized_terms"]["compare_target"] == "yoy"
    assert result["normalized_terms"]["ranking_intent"] is True
