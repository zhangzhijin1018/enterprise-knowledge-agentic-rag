"""API 业务路由包。

该包用于放置 `/api/v1` 下的业务接口路由。
当前阶段只落最小可运行骨架：
- chat
- conversations
- clarifications
- documents
"""

from apps.api.routers.chat import router as chat_router
from apps.api.routers.clarifications import router as clarifications_router
from apps.api.routers.conversations import router as conversations_router
from apps.api.routers.documents import router as documents_router

__all__ = [
    "chat_router",
    "conversations_router",
    "clarifications_router",
    "documents_router",
]
