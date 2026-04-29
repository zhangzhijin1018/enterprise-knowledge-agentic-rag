"""经营分析 Human Review 接口路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from apps.api.deps import get_analytics_review_service, get_current_user_context
from apps.api.schemas.analytics_review import AnalyticsReviewDecisionRequest
from apps.api.schemas.common import SuccessResponse
from core.common.response import build_success_response
from core.security.auth import UserContext
from core.services.analytics_review_service import AnalyticsReviewService

router = APIRouter(prefix="/analytics", tags=["analytics-reviews"])


@router.post("/exports/{export_id}/submit-review", response_model=SuccessResponse)
def submit_analytics_export_review(
    request: Request,
    export_id: str,
    analytics_review_service: AnalyticsReviewService = Depends(get_analytics_review_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """提交或读取某个导出任务的审核请求。"""

    result = analytics_review_service.submit_export_review(
        export_id=export_id,
        user_context=user_context,
    )
    return build_success_response(request=request, data=result["data"], meta=result["meta"])


@router.post("/reviews/{review_id}/approve", response_model=SuccessResponse)
def approve_analytics_review(
    request: Request,
    review_id: str,
    payload: AnalyticsReviewDecisionRequest,
    analytics_review_service: AnalyticsReviewService = Depends(get_analytics_review_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """审批通过某个经营分析审核任务。"""

    result = analytics_review_service.approve_review(
        review_id=review_id,
        comment=payload.comment,
        reviewer_context=user_context,
    )
    return build_success_response(request=request, data=result["data"], meta=result["meta"])


@router.post("/reviews/{review_id}/reject", response_model=SuccessResponse)
def reject_analytics_review(
    request: Request,
    review_id: str,
    payload: AnalyticsReviewDecisionRequest,
    analytics_review_service: AnalyticsReviewService = Depends(get_analytics_review_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """驳回某个经营分析审核任务。"""

    result = analytics_review_service.reject_review(
        review_id=review_id,
        comment=payload.comment,
        reviewer_context=user_context,
    )
    return build_success_response(request=request, data=result["data"], meta=result["meta"])


@router.get("/reviews/{review_id}", response_model=SuccessResponse)
def get_analytics_review_detail(
    request: Request,
    review_id: str,
    analytics_review_service: AnalyticsReviewService = Depends(get_analytics_review_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """读取某个经营分析审核任务详情。"""

    result = analytics_review_service.get_review_detail(
        review_id=review_id,
        user_context=user_context,
    )
    return build_success_response(request=request, data=result["data"], meta=result["meta"])
