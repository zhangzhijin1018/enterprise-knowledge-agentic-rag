"""TaskRunRepository 最小行为测试。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.config.settings import Settings
from core.database.base import Base
from core.database.session import build_engine, get_session_factory, reset_database_runtime_state
from core.repositories.conversation_repository import ConversationRepository
from core.repositories.conversation_repository import reset_in_memory_conversation_store
from core.repositories.task_run_repository import TaskRunRepository
from core.repositories.task_run_repository import reset_in_memory_task_run_store


def test_task_run_repository_in_memory_mode() -> None:
    """内存模式下应支持 task_run、slot_snapshot 和 clarification_event 的最小闭环。"""

    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()

    conversation_repository = ConversationRepository(session=None)
    task_run_repository = TaskRunRepository(session=None)

    conversation = conversation_repository.create_conversation(
        user_id=1,
        title="内存运行态测试",
    )
    task_run = task_run_repository.create_task_run(
        conversation_id=conversation["conversation_id"],
        user_id=1,
        task_type="chat",
        route="business_analysis",
        status="awaiting_user_clarification",
        sub_status="awaiting_slot_fill",
        input_snapshot={"query": "帮我分析经营情况"},
    )
    task_run_repository.create_slot_snapshot(
        run_id=task_run["run_id"],
        task_type="chat",
        required_slots=["metric"],
        collected_slots={},
        missing_slots=["metric"],
        min_executable_satisfied=False,
        awaiting_user_input=True,
        resume_step="resume_after_metric_clarification",
    )
    clarification = task_run_repository.create_clarification_event(
        run_id=task_run["run_id"],
        conversation_id=conversation["conversation_id"],
        question_text="你想看哪个指标？",
        target_slots=["metric"],
    )

    assert task_run_repository.get_task_run(task_run["run_id"]) is not None
    assert task_run_repository.get_slot_snapshot(task_run["run_id"]) is not None
    assert task_run_repository.get_clarification_event(clarification["clarification_id"]) is not None

    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()


def test_task_run_repository_database_mode() -> None:
    """数据库模式下应支持最小运行态持久化。"""

    reset_database_runtime_state()
    settings = Settings(
        database_enabled=True,
        use_in_memory_repository=False,
        database_url="sqlite+pysqlite:///:memory:",
    )
    engine = build_engine(settings=settings)
    assert engine is not None
    Base.metadata.create_all(engine)

    session_factory = get_session_factory(settings=settings)
    assert session_factory is not None

    session: Session = session_factory()
    try:
        conversation_repository = ConversationRepository(session=session)
        task_run_repository = TaskRunRepository(session=session)

        conversation = conversation_repository.create_conversation(
            user_id=2,
            title="数据库运行态测试",
        )
        task_run = task_run_repository.create_task_run(
            conversation_id=conversation["conversation_id"],
            user_id=2,
            task_type="chat",
            route="business_analysis",
            status="awaiting_user_clarification",
            sub_status="awaiting_slot_fill",
            input_snapshot={"query": "帮我分析经营情况"},
        )
        task_run_repository.create_slot_snapshot(
            run_id=task_run["run_id"],
            task_type="chat",
            required_slots=["metric"],
            collected_slots={},
            missing_slots=["metric"],
            min_executable_satisfied=False,
            awaiting_user_input=True,
            resume_step="resume_after_metric_clarification",
        )
        clarification = task_run_repository.create_clarification_event(
            run_id=task_run["run_id"],
            conversation_id=conversation["conversation_id"],
            question_text="你想看哪个指标？",
            target_slots=["metric"],
        )
        session.commit()

        assert task_run_repository.get_task_run(task_run["run_id"]) is not None
        assert task_run_repository.get_slot_snapshot(task_run["run_id"]) is not None
        assert task_run_repository.get_clarification_event(clarification["clarification_id"]) is not None
    finally:
        session.close()
        reset_database_runtime_state()
