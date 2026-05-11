"""带Checkpoint的工作流执行器。

支持：
1. 定期创建状态快照
2. 中断后从快照恢复
3. 完整审计日志
4. Human Review 门控

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from core.agent.workflows.contract.audit_logger import (
    AuditEventType,
    get_audit_logger,
)
from core.agent.workflows.contract.snapshot_manager import (
    SnapshotReason,
    get_snapshot_manager,
)

logger = logging.getLogger(__name__)


class CheckpointWorkflowRunner:
    """带Checkpoint的工作流执行器。

    设计目标：
    1. 支持工作流中断恢复
    2. 定期保存状态快照
    3. 完整记录审计日志
    4. 支持 Human Review 中断
    """

    def __init__(
        self,
        graph,
        audit_logger=None,
        snapshot_manager=None,
        checkpoint_interval: int = 3,
    ) -> None:
        """初始化执行器。

        Args:
            graph: LangGraph 工作流图
            audit_logger: 审计日志记录器
            snapshot_manager: 快照管理器
            checkpoint_interval: 快照间隔（工具调用次数）
        """
        self.graph = graph
        self.audit_logger = audit_logger or get_audit_logger()
        self.snapshot_manager = snapshot_manager or get_snapshot_manager()
        self.checkpoint_interval = checkpoint_interval

    async def run(
        self,
        initial_state: Dict[str, Any],
        user_context: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """运行工作流（带Checkpoint）。

        Args:
            initial_state: 初始状态
            user_context: 用户上下文

        Returns:
            工作流执行结果
        """
        run_id = initial_state.get("run_id")
        trace_id = initial_state.get("trace_id", run_id)
        user_id = user_context.user_id if user_context else initial_state.get("user_id", "system")
        user_role = user_context.user_role if user_context else initial_state.get("user_role", "system")

        # 1. 记录工作流启动
        self.audit_logger.log_workflow_start(
            run_id=run_id,
            trace_id=trace_id,
            user_id=user_id,
            user_role=user_role,
            contract_name=initial_state.get("contract_name", ""),
        )

        # 2. 创建初始快照
        self.snapshot_manager.create_snapshot(
            run_id=run_id,
            trace_id=trace_id,
            state=initial_state,
            reason=SnapshotReason.WORKFLOW_START,
        )

        # 3. 运行工作流
        try:
            result = self.graph.invoke(initial_state)

            # 4. 创建最终快照
            self.snapshot_manager.create_snapshot(
                run_id=run_id,
                trace_id=trace_id,
                state=result,
                reason=SnapshotReason.WORKFLOW_END,
                is_final=True,
            )

            # 5. 记录工作流结束
            self.audit_logger.log(
                run_id=run_id,
                trace_id=trace_id,
                event_type=AuditEventType.WORKFLOW_END,
                action="工作流正常结束",
                user_id=user_id,
                user_role=user_role,
                details={
                    "outcome": result.get("outcome"),
                    "risk_level": result.get("overall_risk_level"),
                    "need_review": result.get("need_human_review"),
                },
            )

            return result

        except Exception as e:
            logger.error(f"[{run_id}] 工作流执行失败: {e}", exc_info=True)

            # 记录错误
            self.audit_logger.log(
                run_id=run_id,
                trace_id=trace_id,
                event_type=AuditEventType.WORKFLOW_ERROR,
                action="工作流执行失败",
                user_id=user_id,
                user_role=user_role,
                error_message=str(e),
            )

            raise

    async def resume(
        self,
        run_id: str,
        user_context: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """从快照恢复工作流。

        Args:
            run_id: 运行ID
            user_context: 用户上下文

        Returns:
            恢复后的执行结果
        """
        # 1. 获取最新快照
        snapshot = self.snapshot_manager.get_latest_snapshot(run_id)
        if not snapshot:
            raise ValueError(f"未找到运行 {run_id} 的快照")

        # 2. 记录恢复
        user_id = user_context.user_id if user_context else "system"
        user_role = user_context.user_role if user_context else "system"

        self.audit_logger.log_workflow_resume(
            run_id=run_id,
            trace_id=snapshot.trace_id,
            user_id=user_id,
            user_role=user_role,
            snapshot_id=snapshot.snapshot_id,
            resume_from=snapshot.current_stage,
        )

        # 3. 恢复状态
        restored_state = snapshot.full_state

        # 4. 继续执行
        return await self.run(restored_state, user_context)

    def check_checkpoint(
        self,
        state: Dict[str, Any],
        tool_count: int,
    ) -> bool:
        """检查是否需要创建快照。

        Args:
            state: 当前状态
            tool_count: 已完成工具数

        Returns:
            是否需要创建快照
        """
        return tool_count > 0 and tool_count % self.checkpoint_interval == 0

    def create_checkpoint(
        self,
        state: Dict[str, Any],
        reason: str = SnapshotReason.PERIODIC,
    ) -> str:
        """创建Checkpoint。

        Args:
            state: 当前状态
            reason: 创建原因

        Returns:
            快照ID
        """
        run_id = state.get("run_id")
        trace_id = state.get("trace_id", run_id)

        snapshot = self.snapshot_manager.create_snapshot(
            run_id=run_id,
            trace_id=trace_id,
            state=state,
            reason=reason,
        )

        # 记录审计
        self.audit_logger.log_workflow_snapshot(
            run_id=run_id,
            trace_id=trace_id,
            user_id=state.get("user_id", "system"),
            user_role=state.get("user_role", "system"),
            snapshot_id=snapshot.snapshot_id,
            current_stage=state.get("current_stage", ""),
            completed_tools=state.get("completed_tools", []),
        )

        return snapshot.snapshot_id


# ==================== 便捷函数 ====================

_checkpoint_runner: CheckpointWorkflowRunner | None = None


def get_checkpoint_runner() -> CheckpointWorkflowRunner:
    """获取全局Checkpoint执行器。"""
    global _checkpoint_runner
    if _checkpoint_runner is None:
        _checkpoint_runner = CheckpointWorkflowRunner(
            graph=None,  # 稍后设置
            checkpoint_interval=3,
        )
    return _checkpoint_runner
