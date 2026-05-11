"""合同审查工作流恢复服务。

提供：
1. 从 Checkpoint 恢复工作流
2. 合并复核结果
3. 继续执行工作流

用于场景：用户点击"生成报告"按钮后，恢复已暂停的工作流。

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from core.agent.workflows.contract.state import (
    ContractWorkflowState,
    ContractWorkflowOutcome,
)
from core.agent.workflows.contract.snapshot_manager import (
    get_snapshot_manager,
    WorkflowSnapshotManager,
)
from core.agent.workflows.contract.human_review_service import (
    get_human_review_service,
    HumanReviewService,
    ReviewDecision,
)
from core.agent.workflows.contract.graph import (
    create_contract_graph,
    run_contract_workflow,
)
from core.agent.workflows.contract.nodes import ContractWorkflowNodes

logger = logging.getLogger(__name__)


class WorkflowResumeService:
    """工作流恢复服务。

    职责：
    1. 从 Checkpoint 读取状态
    2. 验证复核已完成
    3. 合并复核结果到状态
    4. 继续执行工作流
    5. 返回最终结果
    """

    def __init__(
        self,
        snapshot_manager: Optional[WorkflowSnapshotManager] = None,
        human_review_service: Optional[HumanReviewService] = None,
    ) -> None:
        """初始化恢复服务。

        Args:
            snapshot_manager: 快照管理器（可选，默认使用全局实例）
            human_review_service: Human Review 服务（可选，默认使用全局实例）
        """
        self.snapshot_manager = snapshot_manager or get_snapshot_manager()
        self.human_review_service = human_review_service or get_human_review_service()

    async def resume_with_review_result(
        self,
        run_id: str,
        decision: str,
        comments: str,
        reviewer_id: str,
        reviewer_name: str,
    ) -> dict:
        """使用复核结果恢复工作流。

        这是用户点击"生成报告"按钮后调用的核心方法。

        流程：
        1. 验证复核任务状态
        2. 读取 Checkpoint
        3. 合并复核结果
        4. 继续执行工作流（LangGraph 会自动跳转到 generate_report）
        5. 返回最终报告

        Args:
            run_id: 工作流运行ID
            decision: 复核决定（approved/rejected/revised）
            comments: 复核意见
            reviewer_id: 复核人ID
            reviewer_name: 复核人姓名

        Returns:
            恢复后的工作流执行结果
        """
        logger.info(
            f"[ResumeService] 开始恢复工作流 | run_id={run_id} | "
            f"decision={decision} | reviewer={reviewer_name}"
        )

        # 1. 验证复核任务存在且已完成
        review_task = self._validate_review_task(run_id)

        # 2. 读取 Checkpoint
        restored_state = self._load_checkpoint(run_id)

        # 3. 提交复核结果到 Human Review 服务
        await self._submit_review_result(
            review_task=review_task,
            decision=decision,
            comments=comments,
            reviewer_id=reviewer_id,
            reviewer_name=reviewer_name,
        )

        # 4. 合并复核结果到状态
        merged_state = self._merge_review_result(
            state=restored_state,
            decision=decision,
            comments=comments,
            reviewer_id=reviewer_id,
            reviewer_name=reviewer_name,
        )

        # 5. 继续执行工作流
        result = await self._continue_workflow(merged_state)

        # 6. 记录审计日志
        self._log_resume_complete(
            run_id=run_id,
            decision=decision,
            result=result,
        )

        return result

    def _validate_review_task(self, run_id: str) -> any:
        """验证复核任务。

        Args:
            run_id: 运行ID

        Returns:
            复核任务

        Raises:
            ValueError: 复核任务不存在或未完成
        """
        review_task = self.human_review_service.get_review_task_by_run_id(run_id)

        if not review_task:
            raise ValueError(f"未找到运行 {run_id} 对应的复核任务")

        if review_task.status == "completed":
            raise ValueError(
                f"复核任务已完成，请勿重复提交 | "
                f"review_id={review_task.review_id}"
            )

        if review_task.status == "cancelled":
            raise ValueError(f"复核任务已取消 | review_id={review_task.review_id}")

        return review_task

    def _load_checkpoint(self, run_id: str) -> ContractWorkflowState:
        """加载 Checkpoint。

        Args:
            run_id: 运行ID

        Returns:
            恢复的状态

        Raises:
            ValueError: Checkpoint 不存在
        """
        snapshot = self.snapshot_manager.get_latest_snapshot(run_id)

        if not snapshot:
            raise ValueError(f"未找到运行 {run_id} 的 Checkpoint")

        logger.info(
            f"[ResumeService] 加载 Checkpoint | "
            f"snapshot_id={snapshot.snapshot_id} | "
            f"stage={snapshot.current_stage}"
        )

        return snapshot.full_state

    async def _submit_review_result(
        self,
        review_task: any,
        decision: str,
        comments: str,
        reviewer_id: str,
        reviewer_name: str,
    ) -> None:
        """提交复核结果。

        Args:
            review_task: 复核任务
            decision: 复核决定
            comments: 复核意见
            reviewer_id: 复核人ID
            reviewer_name: 复核人姓名
        """
        # 将字符串转换为枚举
        decision_enum = ReviewDecision(decision)

        # 更新复核任务
        self.human_review_service.submit_review_result(
            review_id=review_task.review_id,
            reviewer_id=reviewer_id,
            reviewer_name=reviewer_name,
            decision=decision_enum,
            comments=comments,
        )

        logger.info(
            f"[ResumeService] 提交复核结果 | "
            f"review_id={review_task.review_id} | "
            f"decision={decision}"
        )

    def _merge_review_result(
        self,
        state: ContractWorkflowState,
        decision: str,
        comments: str,
        reviewer_id: str,
        reviewer_name: str,
    ) -> ContractWorkflowState:
        """合并复核结果到状态。

        这是关键步骤：
        - 设置 human_review_status = "completed"
        - 设置 human_review_decision
        - 设置 reviewer 信息

        LangGraph 的 _reflect_decision 条件边会根据
        human_review_status == "completed" 自动跳转到 generate_report。

        Args:
            state: 恢复的状态
            decision: 复核决定
            comments: 复核意见
            reviewer_id: 复核人ID
            reviewer_name: 复核人姓名

        Returns:
            合并后的状态
        """
        # 更新复核状态
        state["human_review_status"] = "completed"
        state["human_review_decision"] = decision
        state["human_review_comments"] = comments
        state["reviewer_id"] = reviewer_id
        state["reviewer_name"] = reviewer_name

        # 确保关键字段存在
        if "outcome" not in state:
            state["outcome"] = ContractWorkflowOutcome.REVIEW.value

        logger.info(
            f"[ResumeService] 合并复核结果 | "
            f"decision={decision} | "
            f"reviewer={reviewer_name} | "
            f"human_review_status={state['human_review_status']}"
        )

        return state

    async def _continue_workflow(self, state: ContractWorkflowState) -> dict:
        """继续执行工作流。

        创建新的 Graph 并从恢复的状态继续执行。
        由于 human_review_status == "completed"，LangGraph 会：
        1. 进入 reflect 节点
        2. _reflect_decision 返回 "generate_report"
        3. 进入 generate_report 节点
        4. 生成最终报告

        Args:
            state: 恢复的状态

        Returns:
            工作流执行结果
        """
        run_id = state.get("run_id", "unknown")

        logger.info(f"[ResumeService] 继续执行工作流 | run_id={run_id}")

        try:
            # 创建节点和图
            nodes = ContractWorkflowNodes()
            graph = create_contract_graph(nodes)

            # 从恢复的状态继续执行
            # 注意：不是从头开始，而是从 reflect 节点继续
            result = run_contract_workflow(graph=graph, initial_state=state)

            logger.info(
                f"[ResumeService] 工作流执行完成 | run_id={run_id} | "
                f"outcome={result.get('outcome')} | "
                f"stage={result.get('current_stage')}"
            )

            return result

        except Exception as e:
            logger.error(
                f"[ResumeService] 工作流执行失败 | run_id={run_id} | error={e}",
                exc_info=True
            )
            raise

    def _log_resume_complete(
        self,
        run_id: str,
        decision: str,
        result: dict,
    ) -> None:
        """记录恢复完成的审计日志。

        Args:
            run_id: 运行ID
            decision: 复核决定
            result: 执行结果
        """
        try:
            from core.agent.workflows.contract.audit_logger import (
                get_audit_logger,
                AuditEventType,
            )

            audit_logger = get_audit_logger()
            audit_logger.log(
                run_id=run_id,
                trace_id=result.get("trace_id", run_id),
                event_type=AuditEventType.WORKFLOW_RESUME,
                action=f"工作流恢复完成 | decision={decision}",
                user_id=result.get("user_id", "system"),
                user_role=result.get("user_role", "system"),
                details={
                    "decision": decision,
                    "outcome": result.get("outcome"),
                    "stage": result.get("current_stage"),
                    "has_report": result.get("review_report") is not None,
                },
            )
        except Exception as e:
            logger.warning(f"[ResumeService] 记录审计日志失败: {e}")

    def get_resume_status(self, run_id: str) -> dict:
        """获取恢复状态信息。

        用于前端显示：
        - 复核是否已完成
        - Checkpoint 是否存在
        - 下一步操作

        Args:
            run_id: 运行ID

        Returns:
            状态信息
        """
        # 检查复核任务
        review_task = self.human_review_service.get_review_task_by_run_id(run_id)

        # 检查 Checkpoint
        snapshot = self.snapshot_manager.get_latest_snapshot(run_id)

        status = {
            "run_id": run_id,
            "has_checkpoint": snapshot is not None,
            "checkpoint_stage": snapshot.current_stage if snapshot else None,
            "has_review_task": review_task is not None,
            "review_status": review_task.status if review_task else None,
            "review_decision": None,
            "can_resume": False,
            "next_action": None,
        }

        if review_task:
            if review_task.status == "pending":
                status["can_resume"] = False
                status["next_action"] = "等待法务人员复核"
            elif review_task.status == "completed":
                status["review_decision"] = review_task.decision.value if review_task.decision else None
                status["can_resume"] = snapshot is not None
                status["next_action"] = "点击生成报告" if snapshot else None
            elif review_task.status == "cancelled":
                status["next_action"] = "复核已取消，需重新发起审查"

        return status


# ==================== 全局实例 ====================

_resume_service: WorkflowResumeService | None = None


def get_resume_service() -> WorkflowResumeService:
    """获取恢复服务全局实例。"""
    global _resume_service

    if _resume_service is None:
        _resume_service = WorkflowResumeService()

    return _resume_service
