"""ConversationRepository 最小行为测试。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.config.settings import Settings
from core.database.base import Base
from core.database.session import build_engine, get_session_factory, reset_database_runtime_state
from core.repositories.conversation_repository import ConversationRepository
from core.repositories.conversation_repository import reset_in_memory_conversation_store


def test_conversation_repository_in_memory_mode() -> None:
    """内存模式下应支持创建、查询、消息追加和取消。"""

    reset_in_memory_conversation_store()
    repository = ConversationRepository(session=None)

    conversation = repository.create_conversation(
        user_id=1,
        title="测试会话",
        current_route="chat",
        current_status="active",
    )
    repository.add_message(
        conversation_id=conversation["conversation_id"],
        role="user",
        message_type="text",
        content="你好",
    )
    repository.cancel_conversation(conversation["conversation_id"])

    conversations, total = repository.list_conversations(page=1, page_size=20, user_id=1)
    messages = repository.list_messages(conversation["conversation_id"])

    assert total == 1
    assert conversations[0]["current_status"] == "cancelled"
    assert len(messages) == 1

    reset_in_memory_conversation_store()


def test_conversation_repository_database_mode() -> None:
    """数据库模式下应支持最小会话持久化。"""

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
        repository = ConversationRepository(session=session)
        conversation = repository.create_conversation(
            user_id=2,
            title="数据库会话",
            current_route="chat",
            current_status="active",
        )
        repository.add_message(
            conversation_id=conversation["conversation_id"],
            role="user",
            message_type="text",
            content="数据库模式测试",
        )
        repository.cancel_conversation(conversation["conversation_id"])
        session.commit()

        verification = ConversationRepository(session=session)
        conversations, total = verification.list_conversations(page=1, page_size=20, user_id=2)
        messages = verification.list_messages(conversation["conversation_id"])

        assert total == 1
        assert conversations[0]["current_status"] == "cancelled"
        assert len(messages) == 1
    finally:
        session.close()
        reset_database_runtime_state()
