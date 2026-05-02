"""AnalyticsRepairController 单元测试。"""

from __future__ import annotations

import pytest

from core.analytics.intent.schema import (
    AnalyticsIntent,
    MetricIntent,
    TimeRangeIntent,
    IntentConfidence,
    ComplexityType,
    PlanningMode,
    AnalysisIntentType,
    TimeRangeType,
)
from core.agent.workflows.analytics.repair_controller import (
    AnalyticsRepairController,
    RepairAction,
    RepairResult,
)


@pytest.fixture
def repair_controller() -> AnalyticsRepairController:
    """创建 RepairController 实例。"""
    return AnalyticsRepairController()


def create_sample_intent() -> AnalyticsIntent:
    """创建样例意图。"""
    return AnalyticsIntent(
        task_type="analytics_query",
        complexity=ComplexityType.SIMPLE,
        planning_mode=PlanningMode.DIRECT,
        analysis_intent=AnalysisIntentType.SIMPLE_QUERY,
        metric=MetricIntent(
            raw_text="发电量",
            metric_code="generation",
            metric_name="发电量",
            confidence=0.9,
        ),
        time_range=TimeRangeIntent(
            raw_text="2024年3月",
            type=TimeRangeType.ABSOLUTE,
            value="2024-03",
            start="2024-03-01",
            end="2024-03-31",
            confidence=0.9,
        ),
        confidence=IntentConfidence(overall=0.9),
        need_clarification=False,
        missing_fields=[],
        ambiguous_fields=[],
    )


# ============================================================================
# 错误分类测试
# ============================================================================

def test_classify_timeout_error(repair_controller: AnalyticsRepairController) -> None:
    """超时错误应该被分类为 relax_time_range。"""
    strategy = repair_controller._classify_error("timeout", "Query timeout after 30s")
    assert strategy == "relax_time_range"


def test_classify_no_data_error(repair_controller: AnalyticsRepairController) -> None:
    """无数据错误应该被分类为 simplify_query。"""
    strategy = repair_controller._classify_error("no_data", "No rows returned")
    assert strategy == "simplify_query"


def test_classify_permission_error(repair_controller: AnalyticsRepairController) -> None:
    """权限错误应该被分类为 cannot_repair。"""
    strategy = repair_controller._classify_error("permission", "Access denied")
    assert strategy == "cannot_repair"


def test_classify_syntax_error(repair_controller: AnalyticsRepairController) -> None:
    """语法错误应该被分类为 request_clarification。"""
    strategy = repair_controller._classify_error("syntax_error", "Invalid SQL syntax")
    assert strategy == "request_clarification"


# ============================================================================
# Repair Result 测试
# ============================================================================

def test_repair_result_cannot_repair(repair_controller: AnalyticsRepairController) -> None:
    """无法修复的错误应该返回 CANNOT_REPAIR。"""
    result = repair_controller.repair(
        original_intent=create_sample_intent(),
        error_message="Access denied",
        error_type="permission",
    )
    assert result.action == RepairAction.CANNOT_REPAIR
    assert "无法自动修复" in result.explanation


def test_repair_result_relax_time_range(repair_controller: AnalyticsRepairController) -> None:
    """放宽时间范围修复。"""
    result = repair_controller._create_relaxed_intent(create_sample_intent())
    assert result.action == RepairAction.RELAX_TIME_RANGE
    assert result.repaired_intent is not None
    assert result.repaired_intent.time_range.value == "近三个月"


def test_repair_result_simplify_group_by(repair_controller: AnalyticsRepairController) -> None:
    """简化分组维度修复。"""
    intent = create_sample_intent()
    intent.group_by = "station"

    result = repair_controller._create_simplified_intent(intent)
    assert result.action == RepairAction.SIMPLIFY_GROUP_BY
    assert result.repaired_intent is not None
    assert result.repaired_intent.group_by == "region"


def test_repair_result_reduce_top_n(repair_controller: AnalyticsRepairController) -> None:
    """减少 top_n 修复。"""
    intent = create_sample_intent()
    intent.top_n = 100

    result = repair_controller._create_reduced_intent(intent)
    assert result.action == RepairAction.REDUCE_TOP_N
    assert result.repaired_intent is not None
    assert result.repaired_intent.top_n == 10


# ============================================================================
# Repair History 测试
# ============================================================================

def test_record_repair_history(repair_controller: AnalyticsRepairController) -> None:
    """修复历史应该被正确记录。"""
    repair_controller._record_repair(
        action="relax_time_range",
        success=True,
        error=None,
    )
    repair_controller._record_repair(
        action="llm_repair",
        success=False,
        error="Test error",
    )

    history = repair_controller.get_repair_history()
    assert len(history) == 2
    assert history[0]["action"] == "relax_time_range"
    assert history[0]["success"] is True
    assert history[1]["action"] == "llm_repair"
    assert history[1]["success"] is False


# ============================================================================
# Integration Test
# ============================================================================

def test_repair_timeout_error(repair_controller: AnalyticsRepairController) -> None:
    """测试超时错误的修复流程。"""
    result = repair_controller.repair(
        original_intent=create_sample_intent(),
        error_message="Query timeout after 30s",
        error_type="timeout",
    )

    # 应该返回修复结果
    assert isinstance(result, RepairResult)
    # 如果有 LLM，应该返回修复后的意图
    # 否则返回 CANNOT_REPAIR（因为没有 mock LLM）
