"""经营分析 Planner 测试。"""

from __future__ import annotations

from core.agent.control_plane.analytics_planner import AnalyticsPlanner


def test_analytics_planner_extracts_minimal_executable_slots() -> None:
    """metric 和 time_range 齐全时应满足最小执行条件。"""

    planner = AnalyticsPlanner()

    plan = planner.plan("帮我分析一下上个月新疆区域发电量")

    assert plan.intent == "business_analysis"
    assert plan.is_executable is True
    assert plan.slots["metric"] == "发电量"
    assert plan.slots["time_range"]["label"] == "上个月"
    assert plan.slots["org_scope"]["value"] == "新疆区域"
    assert plan.missing_slots == []


def test_analytics_planner_returns_clarification_when_metric_missing() -> None:
    """缺少指标时应返回 metric 澄清。"""

    planner = AnalyticsPlanner()

    plan = planner.plan("帮我分析一下上个月的情况")

    assert plan.is_executable is False
    assert "metric" in plan.missing_slots
    assert plan.clarification_target_slots == ["metric"]


def test_analytics_planner_returns_clarification_when_time_range_missing() -> None:
    """缺少时间范围时应返回 time_range 澄清。"""

    planner = AnalyticsPlanner()

    plan = planner.plan("帮我分析一下新疆区域发电量")

    assert plan.is_executable is False
    assert "time_range" in plan.missing_slots
    assert plan.clarification_target_slots == ["time_range"]
