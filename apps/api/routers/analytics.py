"""经营分析接口路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from apps.api.deps import (
    get_analytics_clarification_service,
    get_analytics_service,
    get_current_user_context,
)
from apps.api.schemas.analytics import (
    AnalyticsClarificationReplyRequest,
    AnalyticsQueryRequest,
)
from apps.api.schemas.common import SuccessResponse
from core.common.response import build_success_response
from core.security.auth import UserContext
from core.services.analytics_clarification_service import AnalyticsClarificationService
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
    output_mode: str = Query(default="full", description="输出模式：lite / standard / full"),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """读取经营分析运行详情。"""

    result = analytics_service.get_run_detail(
        run_id=run_id,
        output_mode=output_mode,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )


@router.post("/clarifications/{clarification_id}/reply", response_model=SuccessResponse)
def reply_analytics_clarification(
    request: Request,
    clarification_id: str,
    payload: AnalyticsClarificationReplyRequest,
    analytics_clarification_service: AnalyticsClarificationService = Depends(
        get_analytics_clarification_service
    ),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """提交经营分析澄清回复并恢复 workflow。

    接口语义说明：
    - 这里恢复的是经营分析业务状态机；
    - 不是恢复原 Python 线程；
    - 成功补齐后会复用原 run_id 重新进入 Analytics StateGraph。
    """

    result = analytics_clarification_service.reply(
        clarification_id=clarification_id,
        reply=payload.reply,
        output_mode=payload.output_mode,
        need_sql_explain=payload.need_sql_explain,
        user_context=user_context,
    )
    return build_success_response(request=request, data=result["data"], meta=result["meta"])


@router.get("/clarifications/{clarification_id}", response_model=SuccessResponse)
def get_analytics_clarification_detail(
    request: Request,
    clarification_id: str,
    analytics_clarification_service: AnalyticsClarificationService = Depends(
        get_analytics_clarification_service
    ),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """读取经营分析澄清详情。"""

    result = analytics_clarification_service.get_detail(
        clarification_id=clarification_id,
        user_context=user_context,
    )
    return build_success_response(request=request, data=result["data"], meta=result["meta"])
