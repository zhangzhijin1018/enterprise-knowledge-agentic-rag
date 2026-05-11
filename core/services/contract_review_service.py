"""合同审查服务 - 核心业务逻辑。

职责：
1. 编排合同审查工作流
2. 调用 Contract Agent (A2A)
3. 管理审查状态
4. 处理 Human Review

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ContractReviewRequest(BaseModel):
    """合同审查请求。"""

    contract_file_id: str = Field(description="合同文件ID")
    contract_name: Optional[str] = Field(default=None, description="合同名称")
    contract_type: Optional[str] = Field(default=None, description="合同类型")
    business_domain: str = Field(default="能源", description="业务域")
    query: Optional[str] = Field(default=None, description="用户问题")


class ContractReviewResponse(BaseModel):
    """合同审查响应。"""

    review_id: str = Field(description="审查ID")
    contract_id: str = Field(description="合同ID")
    contract_name: str = Field(description="合同名称")
    contract_type: Optional[str] = Field(default=None, description="合同类型")
    overall_risk_level: str = Field(description="整体风险等级")
    status: str = Field(description="状态")
    need_human_review: bool = Field(description="是否需要人工复核")
    report: Optional[Dict[str, Any]] = Field(default=None, description="审查报告")
    processing_time_ms: int = Field(description="处理时间(毫秒)")
    run_id: str = Field(description="运行ID")
    trace_id: str = Field(description="追踪ID")


class ContractReviewService:
    """合同审查服务。

    职责：
    1. 接收审查请求
    2. 调用 Contract Agent (通过 A2A 或直接调用)
    3. 处理返回结果
    4. 管理审查状态
    """

    def __init__(self) -> None:
        """初始化合同审查服务。"""
        self._reviews: Dict[str, Dict[str, Any]] = {}

    async def review(
        self,
        request: ContractReviewRequest,
        user_context: Any,
    ) -> ContractReviewResponse:
        """执行合同审查。

        Args:
            request: 审查请求
            user_context: 用户上下文

        Returns:
            审查响应
        """
        start_time = time.time()
        run_id = f"contract_{uuid.uuid4().hex[:12]}"
        trace_id = f"tr_{uuid.uuid4().hex[:12]}"
        review_id = f"review_{uuid.uuid4().hex[:12]}"

        logger.info(
            f"[{run_id}] 开始合同审查 | "
            f"contract_file_id={request.contract_file_id} | "
            f"contract_type={request.contract_type}"
        )

        try:
            # 调用 Contract Agent 工作流
            result = await self._execute_review_workflow(
                run_id=run_id,
                trace_id=trace_id,
                request=request,
                user_context=user_context,
            )

            # 构建响应
            processing_time_ms = int((time.time() - start_time) * 1000)

            response = ContractReviewResponse(
                review_id=review_id,
                contract_id=request.contract_file_id,
                contract_name=request.contract_name or result.get("contract_name", "未知合同"),
                contract_type=request.contract_type,
                overall_risk_level=result.get("overall_risk_level", "unknown"),
                status=result.get("outcome", "unknown"),
                need_human_review=result.get("need_human_review", False),
                report=result.get("review_report"),
                processing_time_ms=processing_time_ms,
                run_id=run_id,
                trace_id=trace_id,
            )

            # 缓存结果
            self._reviews[review_id] = response.model_dump()

            logger.info(
                f"[{run_id}] 合同审查完成 | "
                f"review_id={review_id} | "
                f"risk_level={response.overall_risk_level} | "
                f"time={processing_time_ms}ms"
            )

            return response

        except Exception as e:
            logger.error(f"[{run_id}] 合同审查失败: {e}", exc_info=True)
            processing_time_ms = int((time.time() - start_time) * 1000)

            return ContractReviewResponse(
                review_id=review_id,
                contract_id=request.contract_file_id,
                contract_name=request.contract_name or "未知合同",
                contract_type=request.contract_type,
                overall_risk_level="error",
                status="failed",
                need_human_review=False,
                report={"error": str(e)},
                processing_time_ms=processing_time_ms,
                run_id=run_id,
                trace_id=trace_id,
            )

    async def _execute_review_workflow(
        self,
        run_id: str,
        trace_id: str,
        request: ContractReviewRequest,
        user_context: Any,
    ) -> Dict[str, Any]:
        """执行合同审查工作流。

        两种模式：
        1. 直接调用 - 本地执行工作流
        2. A2A 调用 - 远程调用 Contract Agent

        当前使用直接调用模式。
        """
        from core.agent.workflows.contract import (
            ContractWorkflowNodes,
            create_contract_graph,
            create_initial_contract_state,
        )

        # 创建工作流
        nodes = ContractWorkflowNodes(use_reflection=True)
        graph = create_contract_graph(nodes)

        # 构建初始状态
        initial_state = create_initial_contract_state(
            run_id=run_id,
            contract_file_id=request.contract_file_id,
            user_id=user_context.user_id if user_context else "anonymous",
            user_role=user_context.user_role if user_context else "user",
            contract_name=request.contract_name,
            contract_type=request.contract_type,
            business_domain=request.business_domain,
            query=request.query or f"审查{request.contract_name or '合同'}",
            trace_id=trace_id,
        )

        # 执行工作流
        result = graph.invoke(initial_state)

        return result

    def get_review(self, review_id: str) -> Optional[Dict[str, Any]]:
        """获取审查结果。"""
        return self._reviews.get(review_id)

    def list_reviews(
        self,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """列出审查记录。"""
        reviews = list(self._reviews.values())

        if status:
            reviews = [r for r in reviews if r.get("status") == status]

        reviews.sort(key=lambda r: r.get("processing_time_ms", 0), reverse=True)

        return reviews[:limit]


# ==================== 全局实例 ====================

_contract_review_service: Optional[ContractReviewService] = None


def get_contract_review_service() -> ContractReviewService:
    """获取合同审查服务全局实例。"""
    global _contract_review_service

    if _contract_review_service is None:
        _contract_review_service = ContractReviewService()

    return _contract_review_service
