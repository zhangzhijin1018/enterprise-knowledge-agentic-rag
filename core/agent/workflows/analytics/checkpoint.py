"""经营分析 LangGraph Checkpoint 支持。

LangGraph Checkpoint 允许保存和恢复工作流状态，支持：
1. 工作流中断后的恢复
2. 多轮对话的状态持久化
3. 故障恢复

当前设计：
1. 使用 MemorySaver 作为默认 Checkpoint 存储（生产环境可替换为 PostgresSaver 等）
2. Checkpoint 存储的是 workflow state 的快照
3. 业务持久化（task_run, slot_snapshot）仍然独立
"""

from __future__ import annotations

from typing import Any
import json
from datetime import datetime

from core.agent.workflows.analytics.state import (
    AnalyticsWorkflowState,
    AnalyticsWorkflowOutcome,
    AnalyticsWorkflowStage,
)


class CheckpointConfig:
    """Checkpoint 配置。"""

    def __init__(
        self,
        enabled: bool = True,
        checkpoint_dir: str | None = None,
        storage_type: str = "memory",  # memory, file, postgres
    ) -> None:
        self.enabled = enabled
        self.checkpoint_dir = checkpoint_dir
        self.storage_type = storage_type


class CheckpointMetadata:
    """Checkpoint 元数据。"""

    def __init__(
        self,
        thread_id: str,
        checkpoint_id: str,
        created_at: str,
        workflow_stage: str,
        workflow_outcome: str | None = None,
        node_name: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.thread_id = thread_id
        self.checkpoint_id = checkpoint_id
        self.created_at = created_at
        self.workflow_stage = workflow_stage
        self.workflow_outcome = workflow_outcome
        self.node_name = node_name
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        """转换为字典。"""
        return {
            "thread_id": self.thread_id,
            "checkpoint_id": self.checkpoint_id,
            "created_at": self.created_at,
            "workflow_stage": self.workflow_stage,
            "workflow_outcome": self.workflow_outcome,
            "node_name": self.node_name,
            "metadata": self.metadata,
        }


class CheckpointStore:
    """Checkpoint 存储基类。"""

    def save(self, thread_id: str, checkpoint_id: str, state: dict) -> None:
        """保存 checkpoint。"""
        raise NotImplementedError

    def load(self, thread_id: str, checkpoint_id: str | None = None) -> dict | None:
        """加载 checkpoint。"""
        raise NotImplementedError

    def list_checkpoints(self, thread_id: str) -> list[CheckpointMetadata]:
        """列出线程的所有 checkpoint。"""
        raise NotImplementedError

    def delete(self, thread_id: str, checkpoint_id: str) -> None:
        """删除 checkpoint。"""
        raise NotImplementedError


class MemoryCheckpointStore(CheckpointStore):
    """内存Checkpoint存储。用于测试和开发环境。"""

    def __init__(self) -> None:
        self._checkpoints: dict[str, dict[str, dict]] = {}

    def save(self, thread_id: str, checkpoint_id: str, state: dict) -> None:
        """保存 checkpoint 到内存。"""
        if thread_id not in self._checkpoints:
            self._checkpoints[thread_id] = {}
        self._checkpoints[thread_id][checkpoint_id] = {
            "checkpoint_id": checkpoint_id,
            "created_at": datetime.now().isoformat(),
            "state": state,
        }

    def load(self, thread_id: str, checkpoint_id: str | None = None) -> dict | None:
        """从内存加载 checkpoint。"""
        if thread_id not in self._checkpoints:
            return None

        checkpoints = self._checkpoints[thread_id]
        if checkpoint_id is None:
            # 返回最新的
            if not checkpoints:
                return None
            return list(checkpoints.values())[-1]["state"]

        return checkpoints.get(checkpoint_id, {}).get("state")

    def list_checkpoints(self, thread_id: str) -> list[CheckpointMetadata]:
        """列出线程的所有 checkpoint。"""
        if thread_id not in self._checkpoints:
            return []

        checkpoints = self._checkpoints[thread_id]
        result = []
        for cp in checkpoints.values():
            state = cp.get("state", {})
            result.append(
                CheckpointMetadata(
                    thread_id=thread_id,
                    checkpoint_id=cp["checkpoint_id"],
                    created_at=cp["created_at"],
                    workflow_stage=state.get("workflow_stage", "unknown"),
                    workflow_outcome=state.get("workflow_outcome"),
                    metadata={},
                )
            )
        return result

    def delete(self, thread_id: str, checkpoint_id: str) -> None:
        """删除 checkpoint。"""
        if thread_id in self._checkpoints:
            self._checkpoints[thread_id].pop(checkpoint_id, None)

    def clear(self) -> None:
        """清空所有 checkpoint。"""
        self._checkpoints.clear()


class WorkflowCheckpointManager:
    """工作流 Checkpoint 管理器。

    负责：
    1. 在节点执行前后保存 checkpoint
    2. 管理 checkpoint 存储
    3. 提供恢复接口
    """

    def __init__(
        self,
        config: CheckpointConfig | None = None,
        store: CheckpointStore | None = None,
    ) -> None:
        self.config = config or CheckpointConfig()
        self.store = store or MemoryCheckpointStore()
        self._current_thread_id: str | None = None
        self._current_checkpoint_id: str | None = None

    def start_checkpoint(
        self,
        thread_id: str,
        initial_state: AnalyticsWorkflowState,
    ) -> str | None:
        """开始新的 checkpoint 会话。"""
        import uuid

        if not self.config.enabled:
            return None

        self._current_thread_id = thread_id
        self._current_checkpoint_id = f"cp_{uuid.uuid4().hex[:12]}"
        self.save_checkpoint(initial_state)
        return self._current_checkpoint_id

    def save_checkpoint(
        self,
        state: AnalyticsWorkflowState,
        node_name: str | None = None,
    ) -> str | None:
        """保存当前状态。"""
        if not self.config.enabled or not self._current_thread_id:
            return None

        # 提取可序列化的状态
        serializable_state = self._serialize_state(state)

        self.store.save(
            thread_id=self._current_thread_id,
            checkpoint_id=self._current_checkpoint_id,
            state=serializable_state,
        )

        return self._current_checkpoint_id

    def save_node_checkpoint(
        self,
        state: AnalyticsWorkflowState,
        node_name: str,
    ) -> str | None:
        """保存节点级 checkpoint（在节点执行前后）。"""
        if not self.config.enabled:
            return None

        import uuid

        checkpoint_id = f"node_{node_name}_{uuid.uuid4().hex[:8]}"
        serializable_state = self._serialize_state(state)

        self.store.save(
            thread_id=self._current_thread_id,
            checkpoint_id=checkpoint_id,
            state=serializable_state,
        )

        return checkpoint_id

    def restore_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: str | None = None,
    ) -> AnalyticsWorkflowState | None:
        """恢复 checkpoint。"""
        if not self.config.enabled:
            return None

        state = self.store.load(thread_id, checkpoint_id)
        if state:
            self._current_thread_id = thread_id
            # 返回最新的 checkpoint_id
            checkpoints = self.store.list_checkpoints(thread_id)
            if checkpoints:
                self._current_checkpoint_id = checkpoints[-1].checkpoint_id
        return state

    def list_checkpoints(self, thread_id: str) -> list[CheckpointMetadata]:
        """列出线程的所有 checkpoint。"""
        return self.store.list_checkpoints(thread_id)

    def delete_checkpoint(self, thread_id: str, checkpoint_id: str) -> None:
        """删除指定 checkpoint。"""
        self.store.delete(thread_id, checkpoint_id)

    def _serialize_state(self, state: AnalyticsWorkflowState) -> dict:
        """序列化状态，移除不可序列化的对象。"""

        def _clean(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {k: _clean(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_clean(item) for item in obj]
            elif hasattr(obj, "__dict__"):
                # Pydantic 模型
                return _clean(obj.__dict__ if hasattr(obj, "__dict__") else str(obj))
            elif isinstance(obj, (str, int, float, bool, type(None))):
                return obj
            else:
                return str(obj)

        return _clean(dict(state))

    def get_current_thread_id(self) -> str | None:
        """获取当前线程 ID。"""
        return self._current_thread_id

    def get_current_checkpoint_id(self) -> str | None:
        """获取当前 checkpoint ID。"""
        return self._current_checkpoint_id


def create_checkpoint_manager(
    enabled: bool = True,
    storage_type: str = "memory",
) -> WorkflowCheckpointManager:
    """创建 Checkpoint 管理器工厂函数。"""
    config = CheckpointConfig(enabled=enabled, storage_type=storage_type)
    store = MemoryCheckpointStore()
    return WorkflowCheckpointManager(config=config, store=store)
