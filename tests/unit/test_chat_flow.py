"""最小问答闭环单元测试。

当前测试目标不是验证真实 RAG 或真实 Agent 行为，
而是确保第一阶段最小骨架具备稳定的接口编排能力：
- 能创建会话；
- 能写入消息；
- 能返回 mock answer；
- 能触发 clarification 并恢复。
"""

import pytest

from apps.api.schemas.chat import ChatRequest
from apps.api.schemas.clarification import ClarificationReplyRequest
from core.agent.workflow import ChatWorkflowFacade
from core.common import error_codes
from core.common.exceptions import AppException
from core.repositories.conversation_repository import reset_in_memory_conversation_store
from core.repositories.conversation_repository import ConversationRepository
from core.repositories.task_run_repository import reset_in_memory_task_run_store
from core.repositories.task_run_repository import TaskRunRepository
from core.security.auth import UserContext
from core.services.chat_service import ChatService
from core.services.clarification_service import ClarificationService
from core.services.conversation_service import ConversationService


def setup_function() -> None:
    """每个测试前清空内存存储，避免测试间串扰。"""

    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()


def build_mock_user_context() -> UserContext:
    """构造测试使用的最小用户上下文。"""

    return UserContext(
        user_id=1,
        username="test_user",
        display_name="Test User",
        roles=["employee"],
    )


def build_other_user_context() -> UserContext:
    """构造另一个用户上下文，用于验证最小权限隔离是否生效。"""

    return UserContext(
        user_id=2,
        username="other_user",
        display_name="Other User",
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


def test_chat_returns_mock_answer_and_persists_messages() -> None:
    """普通问答应直接返回 mock answer，并写入 user/assistant 两条消息。"""

    conversation_repository = ConversationRepository()
    task_run_repository = TaskRunRepository()
    chat_service = build_chat_service(conversation_repository, task_run_repository)
    conversation_service = ConversationService(conversation_repository=conversation_repository)

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

    assert "answer" in result["data"]
    assert result["meta"]["status"] == "succeeded"

    conversation_id = result["meta"]["conversation_id"]
    messages_result = conversation_service.list_messages(
        conversation_id=conversation_id,
        user_context=build_mock_user_context(),
    )

    assert len(messages_result["data"]["messages"]) == 2
    assert messages_result["data"]["messages"][0]["role"] == "user"
    assert messages_result["data"]["messages"][1]["role"] == "assistant"


def test_chat_can_enter_clarification_and_resume() -> None:
    """缺少关键槽位的问答应先进入 clarification，再可通过 reply 恢复。"""

    conversation_repository = ConversationRepository()
    task_run_repository = TaskRunRepository()
    chat_service = build_chat_service(conversation_repository, task_run_repository)
    clarification_service = ClarificationService(
        conversation_repository=conversation_repository,
        task_run_repository=task_run_repository,
    )
    conversation_service = ConversationService(conversation_repository=conversation_repository)

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

    clarification = chat_result["data"]["clarification"]
    assert chat_result["meta"]["status"] == "awaiting_user_clarification"
    assert clarification["target_slots"] == ["metric"]

    reply_result = clarification_service.reply(
        clarification_id=clarification["clarification_id"],
        payload=ClarificationReplyRequest(reply="发电量"),
        user_context=build_mock_user_context(),
    )

    assert reply_result["meta"]["status"] == "succeeded"

    conversation_id = reply_result["meta"]["conversation_id"]
    messages_result = conversation_service.list_messages(
        conversation_id=conversation_id,
        user_context=build_mock_user_context(),
    )

    roles = [message["role"] for message in messages_result["data"]["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]


def test_other_user_cannot_read_another_users_conversation_messages() -> None:
    """跨用户读取会话消息应被拒绝，避免最小骨架阶段就出现越权读取。"""

    conversation_repository = ConversationRepository()
    task_run_repository = TaskRunRepository()
    chat_service = build_chat_service(conversation_repository, task_run_repository)
    conversation_service = ConversationService(conversation_repository=conversation_repository)

    chat_result = chat_service.submit_chat(
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

    conversation_id = chat_result["meta"]["conversation_id"]

    with pytest.raises(AppException) as exc_info:
        conversation_service.list_messages(
            conversation_id=conversation_id,
            user_context=build_other_user_context(),
        )

    assert exc_info.value.error_code == error_codes.PERMISSION_DENIED
    assert exc_info.value.status_code == 403


def test_other_user_cannot_reply_another_users_clarification() -> None:
    """跨用户回复澄清应被拒绝，避免篡改他人会话的槽位补充结果。"""

    conversation_repository = ConversationRepository()
    task_run_repository = TaskRunRepository()
    chat_service = build_chat_service(conversation_repository, task_run_repository)
    clarification_service = ClarificationService(
        conversation_repository=conversation_repository,
        task_run_repository=task_run_repository,
    )

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

    clarification_id = chat_result["data"]["clarification"]["clarification_id"]

    with pytest.raises(AppException) as exc_info:
        clarification_service.reply(
            clarification_id=clarification_id,
            payload=ClarificationReplyRequest(reply="发电量"),
            user_context=build_other_user_context(),
        )

    assert exc_info.value.error_code == error_codes.PERMISSION_DENIED
    assert exc_info.value.status_code == 403
