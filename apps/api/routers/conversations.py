"""多轮会话路由。

该路由负责最小会话查询能力：
- 查询会话列表；
- 查询单个会话消息列表；

业务编排放在 ConversationService，router 仅负责参数接收与响应封装。
"""

from fastapi import APIRouter, Depends, Query, Request

from apps.api.deps import get_conversation_service
from apps.api.deps import get_current_user_context
from apps.api.schemas.common import SuccessResponse
from core.common.response import build_success_response
from core.security.auth import UserContext
from core.services.conversation_service import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=SuccessResponse)
def list_conversations(
    request: Request,
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    status: str | None = Query(default=None, description="会话状态过滤条件"),
    conversation_service: ConversationService = Depends(get_conversation_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """查询当前最小会话列表。"""

    result = conversation_service.list_conversations(
        page=page,
        page_size=page_size,
        status=status,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )


@router.get("/{conversation_id}/messages", response_model=SuccessResponse)
def list_conversation_messages(
    request: Request,
    conversation_id: str,
    conversation_service: ConversationService = Depends(get_conversation_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """查询单个会话的消息记录。"""

    result = conversation_service.list_messages(
        conversation_id=conversation_id,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )
