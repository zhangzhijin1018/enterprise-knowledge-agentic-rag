"""SQLAlchemy 持久化最小闭环测试。

这些测试的目标不是替代未来真正的 PostgreSQL 集成测试，
而是先验证当前 repository / service 分层在“真实 ORM Session”路径下能跑通。

为什么这里允许使用 SQLite：
1. 项目生产数据库仍然明确是 PostgreSQL，这一点没有变化；
2. 但在本地自动化测试里，使用轻量数据库可以更快验证事务边界和 ORM 映射是否正确；
3. 真正涉及 PostgreSQL 特性、索引、方言差异的部分，后续仍需要独立集成测试覆盖。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from apps.api.schemas.chat import ChatRequest
from apps.api.schemas.clarification import ClarificationReplyRequest
from core.agent.workflow import ChatWorkflowFacade
from core.config.settings import Settings
from core.database.base import Base
from core.database.session import get_session_factory
from core.database.session import reset_database_runtime_state
from core.database.session import build_engine
from core.repositories.conversation_repository import ConversationRepository
from core.repositories.task_run_repository import TaskRunRepository
from core.security.auth import UserContext
from core.services.chat_service import ChatService
from core.services.clarification_service import ClarificationService
from core.services.conversation_service import ConversationService


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """创建测试专用 SQLAlchemy Session。

    这里显式创建 schema，目的是验证当前 ORM 模型和 repository 在真实 Session 路径下可工作。
    测试结束后会清理 engine 缓存，避免影响其他测试。
    """

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

    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        reset_database_runtime_state()


def build_mock_user_context() -> UserContext:
    """构造最小测试用户上下文。"""

    return UserContext(
        user_id=1,
        username="db_test_user",
        display_name="DB Test User",
        roles=["employee"],
    )


def build_chat_service(
    conversation_repository: ConversationRepository,
    task_run_repository: TaskRunRepository,
) -> ChatService:
    """构造带 workflow facade 的 ChatService。"""

    workflow_facade = ChatWorkflowFacade(
        conversation_repository=conversation_repository,
        task_run_repository=task_run_repository,
    )
    return ChatService(chat_workflow_facade=workflow_facade)


def test_chat_answer_flow_can_persist_with_sqlalchemy_session(db_session: Session) -> None:
    """直接回答路径应能持久化会话、消息和任务运行。"""

    conversation_repository = ConversationRepository(session=db_session)
    task_run_repository = TaskRunRepository(session=db_session)
    chat_service = build_chat_service(conversation_repository, task_run_repository)

    result = chat_service.submit_chat(
        ChatRequest(
            query="集团新能源业务有哪些核心制度？",
            conversation_id=None,
            history_messages=[],
            business_hint=None,
            knowledge_base_ids=[],
            stream=False,
        ),
        user_context=build_mock_user_context(),
    )
    db_session.commit()

    conversation_id = result["meta"]["conversation_id"]
    run_id = result["meta"]["run_id"]

    verification_session = db_session.__class__(bind=db_session.bind)
    try:
        conversation_service = ConversationService(
            conversation_repository=ConversationRepository(session=verification_session)
        )
        task_run_repository = TaskRunRepository(session=verification_session)

        conversations = conversation_service.list_conversations(
            page=1,
            page_size=20,
            status=None,
            user_context=build_mock_user_context(),
        )
        messages = conversation_service.list_messages(
            conversation_id=conversation_id,
            user_context=build_mock_user_context(),
        )
        task_run = task_run_repository.get_task_run(run_id)

        assert conversations["data"]["total"] == 1
        assert len(messages["data"]["messages"]) == 2
        assert task_run is not None
        assert task_run["status"] == "succeeded"
    finally:
        verification_session.close()


def test_clarification_flow_can_resume_with_sqlalchemy_session(db_session: Session) -> None:
    """澄清路径应能持久化补槽、恢复执行和最终回答。"""

    conversation_repository = ConversationRepository(session=db_session)
    task_run_repository = TaskRunRepository(session=db_session)
    chat_service = build_chat_service(conversation_repository, task_run_repository)

    chat_result = chat_service.submit_chat(
        ChatRequest(
            query="帮我分析经营情况",
            conversation_id=None,
            history_messages=[],
            business_hint=None,
            knowledge_base_ids=[],
            stream=False,
        ),
        user_context=build_mock_user_context(),
    )
    db_session.commit()

    conversation_id = chat_result["meta"]["conversation_id"]
    run_id = chat_result["meta"]["run_id"]
    clarification_id = chat_result["data"]["clarification"]["clarification_id"]

    reply_session = db_session.__class__(bind=db_session.bind)
    try:
        clarification_service = ClarificationService(
            conversation_repository=ConversationRepository(session=reply_session),
            task_run_repository=TaskRunRepository(session=reply_session),
        )

        reply_result = clarification_service.reply(
            clarification_id=clarification_id,
            payload=ClarificationReplyRequest(reply="发电量"),
            user_context=build_mock_user_context(),
        )
        reply_session.commit()
        assert reply_result["meta"]["status"] == "succeeded"
    finally:
        reply_session.close()

    verification_session = db_session.__class__(bind=db_session.bind)
    try:
        conversation_service = ConversationService(
            conversation_repository=ConversationRepository(session=verification_session)
        )
        task_run_repository = TaskRunRepository(session=verification_session)

        messages = conversation_service.list_messages(
            conversation_id=conversation_id,
            user_context=build_mock_user_context(),
        )
        task_run = task_run_repository.get_task_run(run_id)
        clarification_event = task_run_repository.get_clarification_event(clarification_id)
        slot_snapshot = task_run_repository.get_slot_snapshot(run_id)

        assert len(messages["data"]["messages"]) == 4
        assert task_run is not None
        assert task_run["status"] == "succeeded"
        assert clarification_event is not None
        assert clarification_event["status"] == "resolved"
        assert slot_snapshot is not None
        assert slot_snapshot["awaiting_user_input"] is False
    finally:
        verification_session.close()
