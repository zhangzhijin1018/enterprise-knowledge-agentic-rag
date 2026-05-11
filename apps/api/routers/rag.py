"""RAG 问答 API 路由。

提供 RAG 智能问答的 HTTP 接口。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from apps.api.deps import get_current_user_context
from apps.api.schemas.common import SuccessResponse
from core.common.response import build_success_response
from core.security.auth import UserContext
from core.services.rag_service import RAGService

router = APIRouter(prefix="/rag", tags=["rag"])


def get_rag_service() -> RAGService:
    """获取 RAG 服务。

    依赖注入函数，实际服务由 deps.py 提供。
    """
    from apps.api.deps import get_rag_service
    return get_rag_service()


@router.post("/query", response_model=SuccessResponse)
async def submit_query(
    request: Request,
    query: Annotated[str, Query(description="用户问题")],
    conversation_id: Annotated[str | None, Query(description="会话 ID，用于多轮对话")] = None,
    business_domain: Annotated[str | None, Query(description="业务域过滤")] = None,
    knowledge_base_ids: Annotated[str | None, Query(description="知识库 ID 列表，逗号分隔")] = None,
    rag_service: RAGService = Depends(get_rag_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """提交问答请求。

    Args:
        request: FastAPI 请求对象
        query: 用户问题
        conversation_id: 会话 ID（可选，用于多轮对话）
        business_domain: 业务域过滤（可选）
        knowledge_base_ids: 知识库 ID 列表（可选，逗号分隔）
        rag_service: RAG 服务
        user_context: 用户上下文

    Returns:
        统一响应，包含回答结果
    """

    # 解析 knowledge_base_ids
    kb_ids = None
    if knowledge_base_ids:
        kb_ids = [kb.strip() for kb in knowledge_base_ids.split(",") if kb.strip()]

    result = await rag_service.submit_query(
        query=query,
        user_context=user_context,
        conversation_id=conversation_id,
        business_domain=business_domain,
        knowledge_base_ids=kb_ids,
    )

    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )


@router.get("/run/{run_id}", response_model=SuccessResponse)
async def get_run_detail(
    request: Request,
    run_id: str,
    rag_service: RAGService = Depends(get_rag_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """获取运行详情。

    Args:
        request: FastAPI 请求对象
        run_id: 运行 ID
        rag_service: RAG 服务
        user_context: 用户上下文

    Returns:
        统一响应，包含运行详情
    """

    result = rag_service.get_run_detail(
        run_id=run_id,
        user_context=user_context,
    )

    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )
