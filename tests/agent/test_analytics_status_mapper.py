"""经营分析微观状态到 Supervisor 宏观状态映射测试。"""

from __future__ import annotations

from core.agent.workflows.analytics import (
    AnalyticsWorkflowOutcome,
    AnalyticsWorkflowStage,
    AnalyticsWorkflowStatusMapper,
)


def test_status_mapper_maps_executing_stage_to_supervisor_executing() -> None:
    """执行中微观状态应映射成 Supervisor 的 executing。"""

    status = AnalyticsWorkflowStatusMapper.map_to_supervisor_status(
        {
            "workflow_stage": AnalyticsWorkflowStage.ANALYTICS_BUILD_SQL,
            "workflow_outcome": AnalyticsWorkflowOutcome.CONTINUE,
            "clarification_needed": False,
            "review_required": False,
        }
    )

    assert status.status == "executing"
    assert status.sub_status == "collecting_result"


def test_status_mapper_maps_clarification_to_awaiting_user_clarification() -> None:
    """clarification 必须映射成 awaiting_user_clarification，而不是 failed。"""

    status = AnalyticsWorkflowStatusMapper.map_to_supervisor_status(
        {
            "workflow_stage": AnalyticsWorkflowStage.ANALYTICS_CLARIFY,
            "workflow_outcome": AnalyticsWorkflowOutcome.CLARIFY,
            "clarification_needed": True,
            "review_required": False,
        }
    )

    assert status.status == "awaiting_user_clarification"
    assert status.sub_status == "awaiting_user_input"


def test_status_mapper_maps_review_required_to_waiting_review() -> None:
    """review_required 必须映射成 waiting_review。"""

    status = AnalyticsWorkflowStatusMapper.map_to_supervisor_status(
        {
            "workflow_stage": AnalyticsWorkflowStage.ANALYTICS_FINISH,
            "workflow_outcome": AnalyticsWorkflowOutcome.REVIEW,
            "clarification_needed": False,
            "review_required": True,
        }
    )

    assert status.status == "waiting_review"
    assert status.sub_status == "awaiting_reviewer"
    assert status.review_status == "pending"


def test_status_mapper_maps_finish_to_succeeded() -> None:
    """成功完成的 workflow 应映射成 succeeded。"""

    status = AnalyticsWorkflowStatusMapper.map_to_supervisor_status(
        {
            "workflow_stage": AnalyticsWorkflowStage.ANALYTICS_FINISH,
            "workflow_outcome": AnalyticsWorkflowOutcome.FINISH,
            "clarification_needed": False,
            "review_required": False,
        }
    )

    assert status.status == "succeeded"


def test_status_mapper_maps_fail_to_failed() -> None:
    """失败的 workflow 应映射成 failed。"""

    status = AnalyticsWorkflowStatusMapper.map_to_supervisor_status(
        {
            "workflow_stage": AnalyticsWorkflowStage.ANALYTICS_GUARD_SQL,
            "workflow_outcome": AnalyticsWorkflowOutcome.FAIL,
            "clarification_needed": False,
            "review_required": False,
        }
    )

    assert status.status == "failed"
    assert status.sub_status == "terminal_failure"
