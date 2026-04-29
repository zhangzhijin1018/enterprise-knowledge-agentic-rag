"""经营分析 Planner 测试。"""

from __future__ import annotations

from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.config.settings import Settings


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
    assert plan.clarification_type == "missing_required_slot"
    assert plan.clarification_reason is not None


def test_analytics_planner_returns_clarification_when_time_range_missing() -> None:
    """缺少时间范围时应返回 time_range 澄清。"""

    planner = AnalyticsPlanner()

    plan = planner.plan("帮我分析一下新疆区域发电量")

    assert plan.is_executable is False
    assert "time_range" in plan.missing_slots
    assert plan.clarification_target_slots == ["time_range"]
    assert plan.clarification_type == "missing_required_slot"


def test_analytics_planner_supports_recent_and_topn_query() -> None:
    """口语化 recent + topN 查询应尽量走本地规则。"""

    planner = AnalyticsPlanner()

    plan = planner.plan("最近发电表现按站点排名前3")

    assert plan.slots["metric"] == "发电量"
    assert plan.slots["time_range"]["label"] == "近一个月"
    assert plan.slots["group_by"] == "station"
    assert plan.slots["top_n"] == 3
    assert plan.planning_source == "rule"


def test_analytics_planner_can_use_llm_fallback_when_rule_confidence_is_low() -> None:
    """规则低置信时应允许走 LLM fallback 分支。"""

    def mock_planner_callable(*, query: str, current_slots: dict, conversation_memory: dict) -> dict:
        return {
            "slots": {"metric": "收入"},
            "confidence": 0.9,
            "source": "mock_llm",
            "should_use": True,
        }

    planner = AnalyticsPlanner(
        llm_planner_gateway=LLMAnalyticsPlannerGateway(
            settings=Settings(analytics_planner_enable_llm_fallback=True),
            planner_callable=mock_planner_callable,
        )
    )

    plan = planner.plan("最近经营表现怎么样")

    assert plan.slots["metric"] == "收入"
    assert plan.planning_source == "rule+mock_llm"


def test_analytics_planner_can_detect_multi_metric_query_and_request_clarification() -> None:
    """组合指标表达应先识别候选指标并返回澄清。"""

    planner = AnalyticsPlanner()

    plan = planner.plan("最近收入和成本一起看看")

    assert plan.is_executable is False
    assert "metric" in plan.conflict_slots
    assert plan.slots["metric_candidates"] == ["收入", "成本"]
    assert plan.clarification_type == "slot_conflict"
    assert "多个指标" in (plan.clarification_question or "")


def test_analytics_planner_llm_fallback_cannot_skip_minimum_execute_condition() -> None:
    """LLM fallback 只能补强，不能绕过最小可执行条件判断。"""

    def mock_planner_callable(*, query: str, current_slots: dict, conversation_memory: dict) -> dict:
        return {
            "slots": {"group_by": "month"},
            "confidence": 0.95,
            "source": "mock_llm",
            "should_use": True,
        }

    planner = AnalyticsPlanner(
        llm_planner_gateway=LLMAnalyticsPlannerGateway(
            settings=Settings(analytics_planner_enable_llm_fallback=True),
            planner_callable=mock_planner_callable,
        )
    )

    plan = planner.plan("最近经营表现怎么样")

    assert plan.is_executable is False
    assert set(plan.missing_slots) == {"metric"}
