"""合同审查状态快照服务。

支持：
1. 定期保存状态快照
2. 支持从快照恢复
3. 快照持久化到数据库
4. 支持工作流中断恢复

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SnapshotReason(str):
    """快照创建原因。"""
    WORKFLOW_START = "workflow_start"      # 工作流启动
    PERIODIC = "periodic"                  # 定期快照
    TOOL_COMPLETED = "tool_completed"       # 工具完成
    NODE_COMPLETED = "node_completed"       # 节点完成
    BEFORE_REVIEW = "before_review"        # 复核前
    BEFORE_ERROR = "before_error"           # 错误前
    WORKFLOW_END = "workflow_end"          # 工作流结束
    MANUAL = "manual"                       # 手动快照


class WorkflowSnapshot(BaseModel):
    """工作流状态快照。

    用于：
    1. 支持断点恢复
    2. 支持审计追溯
    3. 支持状态回滚
    """

    snapshot_id: str = Field(description="快照ID")
    run_id: str = Field(description="运行ID")
    trace_id: str = Field(description="追踪ID")

    # 快照时间
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")

    # 快照内容
    current_stage: str = Field(description="当前阶段")
    completed_tools: List[str] = Field(default_factory=list, description="已完成工具")
    react_iterations: int = Field(default=0, description="迭代次数")

    # 业务状态
    parsed_content: str = Field(default="", description="解析内容")
    extracted_clauses: List[dict] = Field(default_factory=list, description="抽取条款")
    identified_risks: List[dict] = Field(default_factory=list, description="识别风险")
    review_report: Optional[dict] = Field(default=None, description="审查报告")

    # Human Review 状态
    need_human_review: bool = Field(default=False, description="需要复核")
    human_review_id: Optional[str] = Field(default=None, description="复核ID")
    human_review_status: Optional[str] = Field(default=None, description="复核状态")

    # 完整状态 JSON
    full_state: Dict[str, Any] = Field(default_factory=dict, description="完整状态")

    # 元数据
    checkpoint_reason: str = Field(description="创建快照原因")
    is_final: bool = Field(default=False, description="是否为最终快照")


class WorkflowSnapshotManager:
    """工作流快照管理器。

    职责：
    1. 创建状态快照
    2. 保存快照到数据库
    3. 从快照恢复状态
    4. 查询历史快照
    5. 管理快照生命周期
    """

    def __init__(self, db_session: Any = None) -> None:
        """初始化快照管理器。"""
        self.db_session = db_session
        self._snapshots: Dict[str, WorkflowSnapshot] = {}  # 内存缓存
        self._run_snapshots: Dict[str, List[str]] = {}  # run_id -> snapshot_ids

    def create_snapshot(
        self,
        run_id: str,
        trace_id: str,
        state: Dict[str, Any],
        reason: str = SnapshotReason.PERIODIC,
        is_final: bool = False,
    ) -> WorkflowSnapshot:
        """创建状态快照。

        Args:
            run_id: 运行ID
            trace_id: 追踪ID
            state: 当前状态
            reason: 创建原因
            is_final: 是否为最终快照

        Returns:
            创建的快照
        """
        snapshot_id = f"snap_{uuid4().hex[:12]}"

        snapshot = WorkflowSnapshot(
            snapshot_id=snapshot_id,
            run_id=run_id,
            trace_id=trace_id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            current_stage=state.get("current_stage", ""),
            completed_tools=state.get("completed_tools", []),
            react_iterations=state.get("react_iterations", 0),
            parsed_content=state.get("parsed_content", ""),
            extracted_clauses=state.get("extracted_clauses", []),
            identified_risks=state.get("identified_risks", []),
            review_report=state.get("review_report"),
            need_human_review=state.get("need_human_review", False),
            human_review_id=state.get("human_review_id"),
            human_review_status=state.get("human_review_status"),
            full_state=state,
            checkpoint_reason=reason,
            is_final=is_final,
        )

        # 保存到缓存
        self._snapshots[snapshot_id] = snapshot

        # 记录 run_id 到 snapshot_id 的映射
        if run_id not in self._run_snapshots:
            self._run_snapshots[run_id] = []
        self._run_snapshots[run_id].append(snapshot_id)

        # 持久化到数据库
        self._save_to_db(snapshot)

        logger.info(
            f"[Snapshot] 创建快照 | id={snapshot_id} | "
            f"run_id={run_id} | reason={reason}"
        )

        return snapshot

    def get_snapshot(self, snapshot_id: str) -> Optional[WorkflowSnapshot]:
        """获取快照。"""
        return self._snapshots.get(snapshot_id)

    def get_latest_snapshot(self, run_id: str) -> Optional[WorkflowSnapshot]:
        """获取最新的快照。"""
        snapshot_ids = self._run_snapshots.get(run_id, [])
        if not snapshot_ids:
            return None

        latest = None
        for sid in snapshot_ids:
            snapshot = self._snapshots.get(sid)
            if snapshot and (latest is None or snapshot.created_at > latest.created_at):
                latest = snapshot
        return latest

    def get_snapshots_by_run(self, run_id: str) -> List[WorkflowSnapshot]:
        """获取某个运行的所有快照。"""
        snapshot_ids = self._run_snapshots.get(run_id, [])
        snapshots = []
        for sid in snapshot_ids:
            snapshot = self._snapshots.get(sid)
            if snapshot:
                snapshots.append(snapshot)
        return sorted(snapshots, key=lambda s: s.created_at)

    def restore_state(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        """从快照恢复状态。

        Args:
            snapshot_id: 快照ID

        Returns:
            恢复的状态
        """
        snapshot = self.get_snapshot(snapshot_id)
        if not snapshot:
            logger.warning(f"[Snapshot] 快照不存在: {snapshot_id}")
            return None

        logger.info(
            f"[Snapshot] 恢复状态 | snapshot_id={snapshot_id} | "
            f"stage={snapshot.current_stage} | "
            f"run_id={snapshot.run_id}"
        )

        return snapshot.full_state

    def restore_latest(self, run_id: str) -> Optional[Dict[str, Any]]:
        """从最新快照恢复状态。"""
        latest = self.get_latest_snapshot(run_id)
        if not latest:
            return None
        return self.restore_state(latest.snapshot_id)

    def delete_old_snapshots(self, run_id: str, keep_count: int = 3) -> int:
        """删除旧的快照，保留最近的N个。

        Args:
            run_id: 运行ID
            keep_count: 保留数量

        Returns:
            删除数量
        """
        snapshots = self.get_snapshots_by_run(run_id)
        if len(snapshots) <= keep_count:
            return 0

        # 保留最后的 keep_count 个
        to_delete = snapshots[:-keep_count]
        deleted = 0

        for snapshot in to_delete:
            self._snapshots.pop(snapshot.snapshot_id, None)
            if snapshot.snapshot_id in self._run_snapshots.get(run_id, []):
                self._run_snapshots[run_id].remove(snapshot.snapshot_id)
            self._delete_from_db(snapshot.snapshot_id)
            deleted += 1

        logger.info(f"[Snapshot] 删除 {deleted} 个旧快照 | run_id={run_id}")
        return deleted

    def _save_to_db(self, snapshot: WorkflowSnapshot) -> None:
        """保存快照到数据库。"""
        # TODO: 实现实际的数据库写入
        # 示例: self.db_session.add(snapshot)
        pass

    def _delete_from_db(self, snapshot_id: str) -> None:
        """从数据库删除快照。"""
        # TODO: 实现实际的数据库删除
        pass


# ==================== 全局实例 ====================

_snapshot_manager: WorkflowSnapshotManager | None = None


def get_snapshot_manager() -> WorkflowSnapshotManager:
    """获取快照管理器全局实例。"""
    global _snapshot_manager
    if _snapshot_manager is None:
        _snapshot_manager = WorkflowSnapshotManager()
    return _snapshot_manager
