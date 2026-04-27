"""API 依赖注入模块。

当前阶段先把最关键的一层依赖注入打通：
- 数据库 Session 依赖；
- Repository 依赖；
- Service 依赖；

这样做的业务意义是：
1. router 不直接 new service/repository，职责更干净；
2. 后续从内存实现切到真实 PostgreSQL 时，API 层不需要再改；
3. 单元测试和接口测试时，更容易替换某一层依赖。
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from core.agent.workflow import ChatWorkflowFacade
from core.config import get_settings
from core.database.session import get_db_session
from core.repositories.conversation_repository import ConversationRepository
from core.repositories.task_run_repository import TaskRunRepository
from core.security.auth import UserContext
from core.security.auth import resolve_user_context_from_request
from core.services.chat_service import ChatService
from core.services.clarification_service import ClarificationService
from core.services.conversation_service import ConversationService


def get_session() -> Iterator[Session | None]:
    """提供数据库 Session 依赖。

    当前默认场景下会返回 `None`，
    让下游 Repository 自动走内存实现；
    当后续启用真实数据库时，这里会 transparently 切到真实 Session。
    """

    yield from get_db_session()


def get_current_user_context(request: Request) -> UserContext:
    """提供当前用户上下文依赖。

    当前阶段采用“Bearer 占位 + Header 透传 + 本地 mock 回退”的策略：
    - 正式调用链路可以显式传入用户上下文头；
    - 本地开发在未接认证系统前仍可直接联调；
    - 后续接 JWT / SSO 时，router 和 service 都不需要再改。
    """

    settings = get_settings()
    user_context = resolve_user_context_from_request(
        request,
        allow_local_mock=settings.auth_allow_local_mock,
    )
    request.state.user_context = user_context
    return user_context


def get_conversation_repository(
    session: Session | None = Depends(get_session),
) -> ConversationRepository:
    """提供会话 Repository 依赖。"""

    return ConversationRepository(session=session)


def get_task_run_repository(
    session: Session | None = Depends(get_session),
) -> TaskRunRepository:
    """提供任务运行 Repository 依赖。"""

    return TaskRunRepository(session=session)


def get_chat_service(
    conversation_repository: ConversationRepository = Depends(get_conversation_repository),
    task_run_repository: TaskRunRepository = Depends(get_task_run_repository),
) -> ChatService:
    """提供 ChatService 依赖。"""

    workflow_facade = ChatWorkflowFacade(
        conversation_repository=conversation_repository,
        task_run_repository=task_run_repository,
    )
    return ChatService(chat_workflow_facade=workflow_facade)


def get_conversation_service(
    conversation_repository: ConversationRepository = Depends(get_conversation_repository),
) -> ConversationService:
    """提供 ConversationService 依赖。"""

    return ConversationService(conversation_repository=conversation_repository)


def get_clarification_service(
    conversation_repository: ConversationRepository = Depends(get_conversation_repository),
    task_run_repository: TaskRunRepository = Depends(get_task_run_repository),
) -> ClarificationService:
    """提供 ClarificationService 依赖。"""

    return ClarificationService(
        conversation_repository=conversation_repository,
        task_run_repository=task_run_repository,
    )
