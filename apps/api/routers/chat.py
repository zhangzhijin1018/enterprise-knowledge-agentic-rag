"""智能问答路由。

当前文件只实现第一批最小可运行接口骨架：
- 接收用户问题；
- 调用 ChatService；
- 返回统一响应结构；

注意：
- router 不承载复杂业务逻辑；
- mock 业务编排放在 service；
- 后续真实工作流、LLM、RAG 会在 service / agent 层逐步接入。
"""

from fastapi import APIRouter, Depends, Request

from apps.api.deps import get_chat_service, get_current_user_context
from apps.api.schemas.chat import ChatRequest
from apps.api.schemas.common import SuccessResponse
from core.common.response import build_success_response
from core.security.auth import UserContext
from core.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=SuccessResponse)
def create_chat(
    request: Request,
    payload: ChatRequest,
    chat_service: ChatService = Depends(get_chat_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """提交最小智能问答请求。

    当前阶段的业务目标不是生成真实答案，而是先把下面这条链路打通：
    用户输入 -> Service -> Repository -> 统一响应。

    这样后续接入真实数据库、真实 Agent 工作流、真实 RAG 检索时，
    API 契约和分层边界都不需要推倒重来。

    这里使用 Depends 注入 Service，而不是在模块级直接创建单例，
    是为了让后续 Session、Repository、Mock 替换都能沿着依赖链自然切换。
    """

    result = chat_service.submit_chat(payload=payload, user_context=user_context)
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )
