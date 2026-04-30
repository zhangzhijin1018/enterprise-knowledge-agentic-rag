"""TaskRunRepository 持久化边界测试。"""

from __future__ import annotations

from core.repositories.conversation_repository import (
    ConversationRepository,
    reset_in_memory_conversation_store,
)
from core.repositories.task_run_repository import (
    TaskRunRepository,
    reset_in_memory_task_run_store,
)


def test_task_run_repository_strips_heavy_objects_from_runtime_snapshots() -> None:
    """task_run 轻快照应自动剥离重对象和微观执行大字段。"""

    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()

    conversation_repository = ConversationRepository(session=None)
    task_run_repository = TaskRunRepository(session=None)
    conversation = conversation_repository.create_conversation(user_id=1, title="持久化边界测试")
    task_run = task_run_repository.create_task_run(
        conversation_id=conversation["conversation_id"],
        user_id=1,
        task_type="analytics",
        route="business_analysis",
        status="executing",
        sub_status="planning_query",
        input_snapshot={
            "query": "帮我分析发电量",
            "sql_bundle": {"generated_sql": "select * from analytics_metrics_daily"},
        },
    )

    task_run_repository.update_task_run(
        task_run["run_id"],
        output_snapshot={
            "summary": "执行成功",
            "sql_preview": "select ...",
            "row_count": 5,
            "timing_breakdown": {"sql_execute_ms": 12.3},
            "tables": [{"name": "main"}],
            "chart_spec": {"chart_type": "line"},
            "execution_result": {"rows": [{"metric_value": 1}]},
            "workflow_stage": "analytics_execute_sql",
        },
        context_snapshot={
            "slots": {"metric": "发电量"},
            "planning_source": "rule",
            "confidence": 0.93,
            "sql_bundle": {"generated_sql": "select ..."},
            "execution_result": {"rows": [{"metric_value": 1}]},
            "workflow_outcome": "continue",
        },
    )

    persisted = task_run_repository.get_task_run(task_run["run_id"])
    assert persisted is not None

    input_snapshot = persisted["input_snapshot"]
    assert input_snapshot["query"] == "帮我分析发电量"
    assert "sql_bundle" not in input_snapshot

    output_snapshot = persisted["output_snapshot"]
    assert output_snapshot["summary"] == "执行成功"
    assert output_snapshot["sql_preview"] == "select ..."
    assert output_snapshot["timing_breakdown"]["sql_execute_ms"] == 12.3
    assert "tables" not in output_snapshot
    assert "chart_spec" not in output_snapshot
    assert "execution_result" not in output_snapshot
    assert "workflow_stage" not in output_snapshot

    context_snapshot = persisted["context_snapshot"]
    assert context_snapshot["slots"]["metric"] == "发电量"
    assert context_snapshot["planning_source"] == "rule"
    assert context_snapshot["confidence"] == 0.93
    assert "sql_bundle" not in context_snapshot
    assert "execution_result" not in context_snapshot
    assert "workflow_outcome" not in context_snapshot


def test_slot_snapshot_and_clarification_event_only_keep_recovery_fields() -> None:
    """slot_snapshot 和 clarification_event 应只保存恢复执行所需字段。"""

    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()

    conversation_repository = ConversationRepository(session=None)
    task_run_repository = TaskRunRepository(session=None)
    conversation = conversation_repository.create_conversation(user_id=2, title="恢复执行态测试")
    task_run = task_run_repository.create_task_run(
        conversation_id=conversation["conversation_id"],
        user_id=2,
        task_type="analytics",
        route="business_analysis",
        status="awaiting_user_clarification",
        sub_status="awaiting_slot_fill",
        input_snapshot={"query": "帮我分析上个月的情况"},
    )

    task_run_repository.create_slot_snapshot(
        run_id=task_run["run_id"],
        task_type="analytics",
        required_slots=["metric", "time_range"],
        collected_slots={"time_range": "上个月"},
        missing_slots=["metric"],
        min_executable_satisfied=False,
        awaiting_user_input=True,
        resume_step="resume_after_analytics_slot_fill",
    )
    task_run_repository.update_slot_snapshot(
        task_run["run_id"],
        collected_slots={"metric": "发电量", "time_range": "上个月"},
        missing_slots=[],
        min_executable_satisfied=True,
        awaiting_user_input=False,
        workflow_stage="analytics_build_sql",
        report_blocks=[{"type": "overview"}],
    )
    slot_snapshot = task_run_repository.get_slot_snapshot(task_run["run_id"])
    assert slot_snapshot is not None
    assert slot_snapshot["collected_slots"]["metric"] == "发电量"
    assert slot_snapshot["resume_step"] == "resume_after_analytics_slot_fill"
    assert "workflow_stage" not in slot_snapshot
    assert "report_blocks" not in slot_snapshot

    clarification = task_run_repository.create_clarification_event(
        run_id=task_run["run_id"],
        conversation_id=conversation["conversation_id"],
        question_text="请补充你要看的指标",
        target_slots=["metric"],
    )
    task_run_repository.update_clarification_event(
        clarification["clarification_id"],
        user_reply="发电量",
        resolved_slots={"metric": "发电量"},
        status="resolved",
        sql_bundle={"generated_sql": "select ..."},
        insight_cards=[{"type": "trend"}],
    )
    clarification_event = task_run_repository.get_clarification_event(clarification["clarification_id"])
    assert clarification_event is not None
    assert clarification_event["user_reply"] == "发电量"
    assert clarification_event["resolved_slots"]["metric"] == "发电量"
    assert clarification_event["status"] == "resolved"
    assert "sql_bundle" not in clarification_event
    assert "insight_cards" not in clarification_event
