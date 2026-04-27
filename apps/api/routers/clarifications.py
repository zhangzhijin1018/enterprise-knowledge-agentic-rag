"""澄清与槽位补充路由。

当前阶段先把“系统追问 -> 用户补充 -> 恢复最小 mock 流程”的接口骨架搭起来，
为后续真实工作流恢复机制预留稳定 API 契约。
"""

from fastapi import APIRouter, Depends, Request

from apps.api.deps import get_clarification_service
from apps.api.deps import get_current_user_context
from apps.api.schemas.clarification import ClarificationReplyRequest
from apps.api.schemas.common import SuccessResponse
from core.common.response import build_success_response
from core.security.auth import UserContext
from core.services.clarification_service import ClarificationService

router = APIRouter(prefix="/clarifications", tags=["clarifications"])


@router.post("/{clarification_id}/reply", response_model=SuccessResponse)
def reply_clarification(
    request: Request,
    clarification_id: str,
    payload: ClarificationReplyRequest,
    clarification_service: ClarificationService = Depends(get_clarification_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """提交澄清回复并恢复最小 mock 任务。"""

    result = clarification_service.reply(
        clarification_id=clarification_id,
        payload=payload,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )
