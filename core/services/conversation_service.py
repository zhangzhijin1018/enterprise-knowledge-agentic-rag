"""会话查询 Service。"""

from __future__ import annotations

from core.common import error_codes
from core.common.exceptions import AppException
from core.common.response import build_response_meta
from core.repositories.conversation_repository import ConversationRepository
from core.security.auth import UserContext


class ConversationService:
    """会话查询编排服务。"""

    def __init__(self, conversation_repository: ConversationRepository) -> None:
        """显式注入会话仓储。"""

        self.conversation_repository = conversation_repository

    def _get_accessible_conversation_or_raise(
        self,
        conversation_id: str,
        user_context: UserContext,
    ) -> dict:
        """读取当前用户可访问的会话记录。

        业务含义：
        - 当前阶段虽然还没接真实 RBAC/ABAC 权限系统，
          但多轮会话本身已经属于用户私有上下文；
        - 如果这里不做最小 owner 校验，任何人只要拿到 conversation_id，
          就可能读取别人的历史问题、澄清回复和系统答案；
        - 因此先落一条最稳妥的默认规则：普通接口只能访问自己的会话。

        后续扩展：
        - 如果要支持管理员、审计员或人工复核人员跨用户查看，
          可以在这里增加更细粒度的角色与权限判断，而不用改 router。
        """

        conversation = self.conversation_repository.get_conversation(conversation_id)
        if conversation is None:
            raise AppException(
                error_code=error_codes.CONVERSATION_NOT_FOUND,
                message="指定会话不存在",
                status_code=404,
                detail={"conversation_id": conversation_id},
            )

        if conversation["user_id"] != user_context.user_id:
            raise AppException(
                error_code=error_codes.PERMISSION_DENIED,
                message="当前用户无权访问该会话",
                status_code=403,
                detail={
                    "conversation_id": conversation_id,
                    "resource_type": "conversation",
                    "owner_user_id": conversation["user_id"],
                    "current_user_id": user_context.user_id,
                },
            )

        return conversation

    def list_conversations(
        self,
        page: int,
        page_size: int,
        status: str | None,
        user_context: UserContext,
    ) -> dict:
        """分页查询当前用户自己的会话列表。

        这里把用户过滤下沉到 repository，而不是在 service 拿到所有结果后再切片，
        这样更符合生产级接口的权限前置原则，也更利于后续切真实 PostgreSQL。
        """

        items, total = self.conversation_repository.list_conversations(
            page=page,
            page_size=page_size,
            status=status,
            user_id=user_context.user_id,
        )

        serialized_items = [
            {
                "conversation_id": item["conversation_id"],
                "title": item["title"],
                "current_route": item["current_route"],
                "current_status": item["current_status"],
                "last_run_id": item["last_run_id"],
                "updated_at": item["updated_at"].isoformat(),
            }
            for item in items
        ]

        return {
            "data": {
                "items": serialized_items,
                "total": total,
            },
            "meta": build_response_meta(
                page=page,
                page_size=page_size,
                total=total,
            ),
        }

    def list_messages(self, conversation_id: str, user_context: UserContext) -> dict:
        """查询当前用户可访问的单个会话消息列表。"""

        self._get_accessible_conversation_or_raise(
            conversation_id=conversation_id,
            user_context=user_context,
        )

        messages = self.conversation_repository.list_messages(conversation_id)
        serialized_messages = [
            {
                "message_id": item["message_id"],
                "role": item["role"],
                "message_type": item["message_type"],
                "content": item["content"],
                "related_run_id": item["related_run_id"],
                "created_at": item["created_at"].isoformat(),
            }
            for item in messages
        ]

        return {
            "data": {
                "conversation_id": conversation_id,
                "messages": serialized_messages,
            },
            "meta": build_response_meta(conversation_id=conversation_id),
        }
