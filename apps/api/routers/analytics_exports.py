"""经营分析导出接口路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from apps.api.deps import get_analytics_export_service, get_current_user_context
from apps.api.schemas.analytics_export import AnalyticsExportRequest
from apps.api.schemas.common import SuccessResponse
from core.common.response import build_success_response
from core.security.auth import UserContext
from core.services.analytics_export_service import AnalyticsExportService

router = APIRouter(prefix="/analytics", tags=["analytics-exports"])


@router.post("/runs/{run_id}/export", response_model=SuccessResponse)
def create_analytics_export(
    request: Request,
    run_id: str,
    payload: AnalyticsExportRequest,
    analytics_export_service: AnalyticsExportService = Depends(get_analytics_export_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """基于既有经营分析运行结果创建导出任务。"""

    result = analytics_export_service.create_export(
        run_id=run_id,
        export_type=payload.export_type,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )


@router.get("/exports/{export_id}", response_model=SuccessResponse)
def get_analytics_export_detail(
    request: Request,
    export_id: str,
    analytics_export_service: AnalyticsExportService = Depends(get_analytics_export_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """读取经营分析导出任务详情。"""

    result = analytics_export_service.get_export_detail(
        export_id=export_id,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )
