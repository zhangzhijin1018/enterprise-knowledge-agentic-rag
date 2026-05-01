"""经营分析接口路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from apps.api.deps import get_analytics_service, get_current_user_context
from apps.api.schemas.analytics import AnalyticsQueryRequest
from apps.api.schemas.common import SuccessResponse
from core.common.response import build_success_response
from core.security.auth import UserContext
from core.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post("/query", response_model=SuccessResponse)
def submit_analytics_query(
    request: Request,
    payload: AnalyticsQueryRequest,
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """提交最小经营分析请求。"""

    result = analytics_service.submit_query(
        query=payload.query,
        conversation_id=payload.conversation_id,
        output_mode=payload.output_mode,
        need_sql_explain=payload.need_sql_explain,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )


@router.get("/runs/{run_id}", response_model=SuccessResponse)
def get_analytics_run_detail(
    request: Request,
    run_id: str,
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """读取经营分析运行详情。"""

    result = analytics_service.get_run_detail(
        run_id=run_id,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )
