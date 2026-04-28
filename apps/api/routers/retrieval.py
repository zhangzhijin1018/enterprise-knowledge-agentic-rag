"""检索验证路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from apps.api.deps import get_current_user_context, get_retrieval_service
from apps.api.schemas.common import SuccessResponse
from apps.api.schemas.retrieval import RetrievalSearchRequest
from core.common.response import build_success_response
from core.security.auth import UserContext
from core.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.post("/search", response_model=SuccessResponse)
def search_retrieval(
    request: Request,
    payload: RetrievalSearchRequest,
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """执行最小 hybrid retrieval。"""

    result = retrieval_service.search(
        query=payload.query,
        user_context=user_context,
        top_k=payload.top_k,
        knowledge_base_ids=payload.knowledge_base_ids,
        business_domain=payload.business_domain,
        chunk_types=payload.chunk_types or None,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )
