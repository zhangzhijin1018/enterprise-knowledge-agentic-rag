"""Analytics 局部 ReAct Planner 测试。"""

from __future__ import annotations

import pytest

from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.agent.workflows.analytics.react.planner import AnalyticsReactPlanner
from core.agent.workflows.analytics.react.policy import AnalyticsReactPlanningPolicy
from core.agent.workflows.analytics.react.tools import AnalyticsReactToolRegistry
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.config.settings import Settings
from core.llm import MockLLMGateway


def _build_react_planner(*, response_payload: dict, max_steps: int = 3) -> tuple[AnalyticsReactPlanner, MockLLMGateway]:
    """构造测试用 ReAct Planner。"""

    schema_registry = SchemaRegistry(settings=Settings())
    metric_catalog = MetricCatalog()
    gateway = MockLLMGateway(structured_payload=response_payload)
    planner = AnalyticsReactPlanner(
        base_planner=AnalyticsPlanner(metric_catalog=metric_catalog),
        tool_registry=AnalyticsReactToolRegistry(
            metric_catalog=metric_catalog,
            schema_registry=schema_registry,
        ),
        llm_gateway=gateway,
        settings=Settings(analytics_react_max_steps=max_steps),
    )
    return planner, gateway


def test_react_policy_only_triggers_for_complex_questions() -> None:
    """简单问题不走 ReAct，复杂问题才走 ReAct。"""

    policy = AnalyticsReactPlanningPolicy(settings=Settings(analytics_react_planner_enabled=True))

    assert policy.should_use_react(query="上个月发电量", conversation_memory={}) is False
    assert policy.should_use_react(query="上个月收入同比对比", conversation_memory={}) is True


def test_react_planner_outputs_analytics_plan_candidate() -> None:
    """ReAct 输出必须收敛成 AnalyticsPlan。"""

    planner, gateway = _build_react_planner(
        response_payload={
            "thought": "识别收入同比分析",
            "action": "finish",
            "action_input": {},
            "final_plan_candidate": {
                "slots": {
                    "metric": "收入",
                    "time_range": {
                        "type": "explicit_month",
                        "label": "2024-03",
                        "start_date": "2024-03-01",
                        "end_date": "2024-03-31",
                    },
                    "compare_target": "yoy",
                    "group_by": "month",
                },
                "confidence": 0.92,
                "reason": "复杂对比问题",
            },
            "stopped_reason": "finished",
        }
    )

    plan, react_state = planner.plan(query="看一下上个月收入同比对比", conversation_memory={})

    assert plan.is_executable is True
    assert plan.planning_source == "react_planner"
    assert plan.slots["metric"] == "收入"
    assert react_state.stopped_reason == "finished"
    assert len(gateway.calls) == 1


def test_react_planner_rejects_forbidden_tools_without_execution() -> None:
    """ReAct 子循环遇到禁止工具时应停止并失败回退。"""

    planner, _ = _build_react_planner(
        response_payload={
            "thought": "错误地尝试执行 SQL",
            "action": "sql_execute",
            "action_input": {"sql": "select 1"},
            "final_plan_candidate": None,
            "stopped_reason": "",
        }
    )

    with pytest.raises(RuntimeError, match="forbidden_or_unknown_tool"):
        planner.plan(query="收入原因分析", conversation_memory={})


def test_react_planner_respects_max_steps() -> None:
    """ReAct 子循环必须遵守 max_steps，防止无限循环。"""

    planner, gateway = _build_react_planner(
        response_payload={
            "thought": "继续查指标目录",
            "action": "metric_catalog_lookup",
            "action_input": {"query": "收入同比"},
            "final_plan_candidate": None,
            "stopped_reason": "",
        },
        max_steps=2,
    )

    with pytest.raises(RuntimeError, match="max_steps_reached"):
        planner.plan(query="收入同比原因分析", conversation_memory={})

    assert len(gateway.calls) == 2
