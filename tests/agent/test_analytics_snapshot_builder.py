"""经营分析 Snapshot Builder 测试。"""

from __future__ import annotations

from core.agent.control_plane.analytics_planner import AnalyticsPlan
from core.agent.workflows.analytics.snapshot_builder import AnalyticsSnapshotBuilder
from core.analytics.analytics_result_model import AnalyticsResult
from core.security.auth import UserContext


def build_user_context(user_id: int = 2201) -> UserContext:
    """构造最小用户上下文。"""

    return UserContext(
        user_id=user_id,
        username=f"user_{user_id}",
        display_name=f"user_{user_id}",
        roles=["employee", "analyst"],
        department_code="analytics-center",
        permissions=[
            "analytics:query",
            "analytics:metric:generation",
            "analytics:metric:output",
        ],
    )


def build_plan() -> AnalyticsPlan:
    """构造最小 AnalyticsPlan。"""

    return AnalyticsPlan(
        intent="business_analysis",
        slots={
            "metric": "发电量",
            "time_range": {"label": "上个月"},
        },
        required_slots=["metric", "time_range"],
        missing_slots=[],
        conflict_slots=[],
        is_executable=True,
        validation_reason="all_required_slots_present",
        clarification_question=None,
        clarification_target_slots=[],
        clarification_reason=None,
        clarification_type=None,
        clarification_suggested_options=[],
        data_source="local_analytics",
        planning_source="rule",
        confidence=0.96,
    )


def build_result() -> AnalyticsResult:
    """构造最小 AnalyticsResult。"""

    return AnalyticsResult(
        run_id="run_test",
        trace_id="tr_test",
        summary="查询成功",
        sql_preview="select metric_value from analytics_metrics_daily limit 100",
        row_count=3,
        latency_ms=15,
        data_source="local_analytics",
        metric_scope="发电量",
        compare_target=None,
        group_by="month",
        slots={"metric": "发电量", "time_range": {"label": "上个月"}},
        planning_source="rule",
        columns=["month", "metric_value"],
        rows=[{"month": "2025-01", "metric_value": 1}],
        masked_columns=["month", "metric_value"],
        masked_rows=[{"month": "2025-01", "metric_value": 1}],
        chart_spec={"chart_type": "line"},
        insight_cards=[{"type": "trend"}],
        report_blocks=[{"block_type": "overview"}],
        governance_decision="no_masking_needed",
        effective_filters={"department_code": "analytics-center"},
        timing_breakdown={"sql_execute_ms": 12.1},
    )


def test_build_input_snapshot_keeps_only_lightweight_fields() -> None:
    """build_input_snapshot 不应产出微观大对象字段。"""

    builder = AnalyticsSnapshotBuilder()
    snapshot = builder.build_input_snapshot(
        query="帮我分析上个月发电量",
        conversation_id="conv_1",
        output_mode="standard",
        need_sql_explain=False,
        user_context=build_user_context(),
        planner_slots={"metric": "发电量"},
        planning_source="rule",
        confidence=0.95,
    )

    assert snapshot["query"] == "帮我分析上个月发电量"
    assert snapshot["conversation_id"] == "conv_1"
    assert snapshot["output_mode"] == "standard"
    assert snapshot["user_context_summary"]["department_code"] == "analytics-center"
    assert snapshot["user_context_summary"]["permissions_count"] == 3
    assert "sql_bundle" not in snapshot
    assert "execution_result" not in snapshot
    assert "workflow_stage" not in snapshot


def test_build_output_snapshot_excludes_heavy_result_fields() -> None:
    """build_output_snapshot 不应包含 tables / chart_spec / insight_cards / report_blocks。"""

    builder = AnalyticsSnapshotBuilder()
    snapshot = builder.build_output_snapshot(analytics_result=build_result())

    assert snapshot["summary"] == "查询成功"
    assert snapshot["row_count"] == 3
    assert snapshot["group_by"] == "month"
    assert snapshot["has_heavy_result"] is True
    assert "tables" not in snapshot
    assert "chart_spec" not in snapshot
    assert "insight_cards" not in snapshot
    assert "report_blocks" not in snapshot


def test_build_context_snapshot_excludes_workflow_temporary_objects() -> None:
    """build_context_snapshot 只应保留恢复执行和审计需要的轻量上下文。"""

    builder = AnalyticsSnapshotBuilder()
    snapshot = builder.build_context_snapshot(
        slots={"metric": "发电量"},
        planning_source="rule",
        confidence=0.93,
        missing_slots=["time_range"],
        clarification_type="missing_required_slot",
        resume_step="resume_after_analytics_slot_fill",
    )

    assert snapshot["slots"]["metric"] == "发电量"
    assert snapshot["missing_slots"] == ["time_range"]
    assert snapshot["clarification_type"] == "missing_required_slot"
    assert snapshot["resume_step"] == "resume_after_analytics_slot_fill"
    assert "plan" not in snapshot
    assert "sql_bundle" not in snapshot
    assert "execution_result" not in snapshot


def test_build_slot_snapshot_and_clarification_payloads_keep_only_recovery_fields() -> None:
    """slot_snapshot 和 clarification_event 的 builder 应只输出恢复执行必需字段。"""

    builder = AnalyticsSnapshotBuilder()
    plan = build_plan()

    slot_payload = builder.build_slot_snapshot_payload(plan=plan)
    assert set(slot_payload.keys()) == {
        "required_slots",
        "collected_slots",
        "missing_slots",
        "min_executable_satisfied",
        "awaiting_user_input",
        "resume_step",
    }

    clarification_payload = builder.build_clarification_event_payload(plan=plan)
    assert set(clarification_payload.keys()) == {"question_text", "target_slots"}
