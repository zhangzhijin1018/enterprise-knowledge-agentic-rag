"""合同审查 API 路由。

提供合同审查接口：
1. POST /contract/review - 执行合同审查
2. GET /contract/{review_id} - 获取审查结果
3. POST /contract/{run_id}/resume - 恢复工作流（复核完成后）
4. GET /contract/{run_id}/resume/status - 获取恢复状态
5. GET /contracts - 列出审查记录

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from apps.api.deps import get_current_user_context
from apps.api.schemas.common import SuccessResponse
from core.common.response import build_success_response
from core.security.auth import UserContext
from core.services.contract_review_service import (
    ContractReviewRequest,
    ContractReviewResponse,
    get_contract_review_service,
)
from core.services.workflow_resume_service import get_resume_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contract", tags=["contract"])


def get_service() -> Any:
    """获取服务实例。"""
    return get_contract_review_service()


@router.post("/review", response_model=SuccessResponse)
async def review_contract(
    request: Request,
    contract_file_id: str,
    contract_name: Optional[str] = None,
    contract_type: Optional[str] = None,
    business_domain: str = "能源",
    query: Optional[str] = None,
    service: Any = Depends(get_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """执行合同审查。

    流程：
    1. 接收审查请求
    2. 调用合同审查工作流
    3. 返回审查结果

    Args:
        contract_file_id: 合同文件ID
        contract_name: 合同名称
        contract_type: 合同类型
        business_domain: 业务域
        query: 用户问题

    Returns:
        审查结果
    """
    logger.info(
        f"[Contract API] 审查请求 | "
        f"contract_file_id={contract_file_id} | "
        f"contract_type={contract_type}"
    )

    review_request = ContractReviewRequest(
        contract_file_id=contract_file_id,
        contract_name=contract_name,
        contract_type=contract_type,
        business_domain=business_domain,
        query=query,
    )

    result = await service.review(
        request=review_request,
        user_context=user_context,
    )

    return build_success_response(
        request=request,
        data=result.model_dump() if hasattr(result, 'model_dump') else result,
    )


@router.get("/{review_id}", response_model=SuccessResponse)
async def get_review(
    request: Request,
    review_id: str,
    service: Any = Depends(get_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """获取审查结果。

    Args:
        review_id: 审查ID

    Returns:
        审查结果
    """
    result = service.get_review(review_id)

    if result is None:
        return build_success_response(
            request=request,
            data={"error": "审查结果不存在"},
        )

    return build_success_response(
        request=request,
        data=result,
    )


@router.get("", response_model=SuccessResponse)
async def list_reviews(
    request: Request,
    status: Optional[str] = None,
    limit: int = 100,
    service: Any = Depends(get_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """列出审查记录。

    Args:
        status: 状态过滤
        limit: 返回数量限制

    Returns:
        审查记录列表
    """
    results = service.list_reviews(status=status, limit=limit)

    return build_success_response(
        request=request,
        data={
            "items": results,
            "total": len(results),
        },
    )


# ==================== 恢复接口 ====================


class ResumeRequest:
    """恢复请求模型（内部使用）。"""

    def __init__(
        self,
        decision: str,
        comments: str,
        reviewer_id: Optional[str] = None,
        reviewer_name: Optional[str] = None,
    ):
        self.decision = decision
        self.comments = comments
        self.reviewer_id = reviewer_id
        self.reviewer_name = reviewer_name


@router.post("/{run_id}/resume", response_model=SuccessResponse)
async def resume_workflow(
    request: Request,
    run_id: str,
    decision: str,
    comments: str = "",
    reviewer_id: Optional[str] = None,
    reviewer_name: Optional[str] = None,
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """恢复工作流（复核完成后）。

    当法务人员完成复核后，用户点击"生成报告"按钮调用此接口。

    流程：
    1. 验证复核任务状态
    2. 读取 Checkpoint
    3. 合并复核结果
    4. 继续执行工作流（自动跳转到 generate_report）
    5. 返回最终报告

    Args:
        run_id: 工作流运行ID
        decision: 复核决定（approved/rejected/revised）
        comments: 复核意见
        reviewer_id: 复核人ID（可选）
        reviewer_name: 复核人姓名（可选）

    Returns:
        恢复后的审查结果
    """
    logger.info(
        f"[Contract API] 恢复工作流 | run_id={run_id} | decision={decision}"
    )

    # 获取恢复服务
    resume_service = get_resume_service()

    # 使用 reviewer_id 和 reviewer_name（优先使用参数，其次使用 user_context）
    final_reviewer_id = reviewer_id or str(user_context.user_id)
    final_reviewer_name = reviewer_name or user_context.display_name

    try:
        result = await resume_service.resume_with_review_result(
            run_id=run_id,
            decision=decision,
            comments=comments,
            reviewer_id=final_reviewer_id,
            reviewer_name=final_reviewer_name,
        )

        return build_success_response(
            request=request,
            data={
                "success": True,
                "run_id": run_id,
                "decision": decision,
                "outcome": result.get("outcome"),
                "stage": result.get("current_stage"),
                "conclusion": result.get("conclusion"),
                "review_report": result.get("review_report"),
                "high_risk_count": result.get("high_risk_count", 0),
                "medium_risk_count": result.get("medium_risk_count", 0),
                "low_risk_count": result.get("low_risk_count", 0),
            },
        )

    except ValueError as e:
        logger.warning(f"[Contract API] 恢复失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error(f"[Contract API] 恢复异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"恢复工作流失败: {str(e)}")


@router.get("/{run_id}/resume/status", response_model=SuccessResponse)
async def get_resume_status(
    request: Request,
    run_id: str,
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """获取恢复状态。

    用于前端检查：
    - 复核是否已完成
    - Checkpoint 是否存在
    - 是否可以恢复

    Args:
        run_id: 工作流运行ID

    Returns:
        状态信息
    """
    logger.info(f"[Contract API] 获取恢复状态 | run_id={run_id}")

    resume_service = get_resume_service()
    status = resume_service.get_resume_status(run_id)

    return build_success_response(
        request=request,
        data=status,
    )
