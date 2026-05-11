"""Human Review 审核管理 API 路由。

提供审核任务的 HTTP 接口。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from apps.api.deps import get_current_user_context
from apps.api.schemas.common import SuccessResponse
from core.common.response import build_success_response
from core.review.models import ReviewDecisionRequest, ReviewRequest, ReviewStatus, TaskType
from core.security.auth import UserContext
from core.review.review_service import ReviewService

router = APIRouter(prefix="/reviews", tags=["reviews"])


def get_review_service() -> ReviewService:
    """获取 Review Service。"""
    from apps.api.deps import get_review_service as _get
    return _get()


@router.post("", response_model=SuccessResponse)
async def create_review(
    request: Request,
    body: ReviewRequest,
    review_service: ReviewService = Depends(get_review_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """创建审核任务。

    Args:
        request: FastAPI 请求对象
        body: 审核请求
        review_service: 审核服务
        user_context: 用户上下文

    Returns:
        统一响应
    """
    # 设置提交人
    body.submitted_by = user_context.user_id

    # 创建审核任务
    task = review_service.create_review(body)

    return build_success_response(
        request=request,
        data={
            "review_id": task.review_id,
            "status": task.status.value,
            "message": "审核任务创建成功",
        },
    )


@router.get("/{review_id}", response_model=SuccessResponse)
async def get_review(
    request: Request,
    review_id: str,
    review_service: ReviewService = Depends(get_review_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """获取审核任务详情。

    Args:
        request: FastAPI 请求对象
        review_id: 审核 ID
        review_service: 审核服务
        user_context: 用户上下文

    Returns:
        统一响应
    """
    task = review_service.get_task(review_id)

    if not task:
        return build_success_response(
            request=request,
            data={"error": "审核任务不存在"},
        )

    return build_success_response(
        request=request,
        data=task.model_dump(),
    )


@router.get("", response_model=SuccessResponse)
async def list_reviews(
    request: Request,
    status: Annotated[str | None, Query(description="审核状态")] = None,
    task_type: Annotated[str | None, Query(description="任务类型")] = None,
    reviewer_id: Annotated[str | None, Query(description="审核人 ID")] = None,
    include_pending: Annotated[bool, Query(description="是否包含待审核")] = True,
    limit: Annotated[int, Query(description="返回数量")] = 20,
    review_service: ReviewService = Depends(get_review_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """获取审核任务列表。

    Args:
        request: FastAPI 请求对象
        status: 审核状态
        task_type: 任务类型
        reviewer_id: 审核人 ID
        include_pending: 是否包含待审核
        limit: 返回数量
        review_service: 审核服务
        user_context: 用户上下文

    Returns:
        统一响应
    """
    # 解析状态
    review_status = None
    if status:
        try:
            review_status = ReviewStatus(status)
        except ValueError:
            pass

    # 解析任务类型
    task_type_enum = None
    if task_type:
        try:
            task_type_enum = TaskType(task_type)
        except ValueError:
            pass

    if include_pending:
        tasks = review_service.get_pending_tasks(
            reviewer_id=reviewer_id,
            task_type=task_type_enum,
            limit=limit,
        )
    else:
        tasks = review_service.get_reviewed_tasks(
            reviewer_id=reviewer_id,
            status=review_status,
            limit=limit,
        )

    return build_success_response(
        request=request,
        data={
            "items": [t.model_dump() for t in tasks],
            "total": len(tasks),
        },
    )


@router.post("/{review_id}/assign", response_model=SuccessResponse)
async def assign_reviewer(
    request: Request,
    review_id: str,
    assigned_to: Annotated[str, Query(description="分配的审核人 ID")],
    review_service: ReviewService = Depends(get_review_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """分配审核人。

    Args:
        request: FastAPI 请求对象
        review_id: 审核 ID
        assigned_to: 分配的审核人 ID
        review_service: 审核服务
        user_context: 用户上下文

    Returns:
        统一响应
    """
    task = review_service.assign_reviewer(
        review_id=review_id,
        reviewer_id=assigned_to,
        assigned_by=user_context.user_id,
    )

    return build_success_response(
        request=request,
        data={
            "review_id": task.review_id,
            "status": task.status.value,
            "message": f"已分配审核人: {assigned_to}",
        },
    )


@router.post("/{review_id}/decision", response_model=SuccessResponse)
async def submit_decision(
    request: Request,
    review_id: str,
    body: ReviewDecisionRequest,
    review_service: ReviewService = Depends(get_review_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """提交审核决策。

    Args:
        request: FastAPI 请求对象
        review_id: 审核 ID
        body: 审核决策请求
        review_service: 审核服务
        user_context: 用户上下文

    Returns:
        统一响应
    """
    task = review_service.submit_decision(
        review_id=review_id,
        decision=body.decision,
        reviewer_id=user_context.user_id,
        reason=body.reason,
        revised_content=body.revised_content,
        revision_notes=body.revision_notes,
    )

    return build_success_response(
        request=request,
        data={
            "review_id": task.review_id,
            "status": task.status.value,
            "decision": task.decision.value if task.decision else None,
            "message": f"审核决策已提交: {task.decision.value}",
        },
    )


@router.post("/{review_id}/cancel", response_model=SuccessResponse)
async def cancel_review(
    request: Request,
    review_id: str,
    reason: Annotated[str | None, Query(description="取消原因")] = None,
    review_service: ReviewService = Depends(get_review_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """取消审核任务。

    Args:
        request: FastAPI 请求对象
        review_id: 审核 ID
        reason: 取消原因
        review_service: 审核服务
        user_context: 用户上下文

    Returns:
        统一响应
    """
    task = review_service.cancel_review(
        review_id=review_id,
        cancelled_by=user_context.user_id,
        reason=reason,
    )

    return build_success_response(
        request=request,
        data={
            "review_id": task.review_id,
            "status": task.status.value,
            "message": "审核任务已取消",
        },
    )


@router.get("/statistics/summary", response_model=SuccessResponse)
async def get_statistics(
    request: Request,
    review_service: ReviewService = Depends(get_review_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """获取审核统计信息。

    Args:
        request: FastAPI 请求对象
        review_service: 审核服务
        user_context: 用户上下文

    Returns:
        统一响应
    """
    stats = review_service.get_statistics()

    return build_success_response(
        request=request,
        data=stats,
    )
