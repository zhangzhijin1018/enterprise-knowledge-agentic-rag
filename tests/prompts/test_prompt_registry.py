"""Prompt Registry 测试。"""

from __future__ import annotations

from core.prompts import PromptRegistry, PromptRenderer


def test_prompt_registry_loads_analytics_react_templates() -> None:
    """Prompt Registry 应能加载经营分析 ReAct planner 模板。"""

    registry = PromptRegistry()

    system_template = registry.load("analytics/react_planner_system")
    user_template = registry.load("analytics/react_planner_user")

    assert "不能生成最终 SQL" in system_template
    assert "{{ query }}" in user_template


def test_prompt_renderer_renders_variables() -> None:
    """轻量 Renderer 应支持基本变量替换。"""

    renderer = PromptRenderer()

    result = renderer.render(
        "问题：{{ query }}\n指标：{{ metric_names }}\n记忆：{{ memory }}",
        {"query": "收入同比", "metric_names": ["收入", "成本"], "memory": {"last_metric": "收入"}},
    )

    assert "收入同比" in result
    assert "成本" in result
    assert "last_metric" in result
