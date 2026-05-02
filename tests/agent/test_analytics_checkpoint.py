"""Checkpoint 管理器单元测试。"""

from __future__ import annotations

import pytest

from core.agent.workflows.analytics.checkpoint import (
    CheckpointConfig,
    CheckpointMetadata,
    CheckpointStore,
    MemoryCheckpointStore,
    WorkflowCheckpointManager,
    create_checkpoint_manager,
)


# ============================================================================
# CheckpointConfig 测试
# ============================================================================

def test_checkpoint_config_defaults() -> None:
    """测试默认配置。"""
    config = CheckpointConfig()
    assert config.enabled is True
    assert config.storage_type == "memory"


def test_checkpoint_config_custom() -> None:
    """测试自定义配置。"""
    config = CheckpointConfig(
        enabled=False,
        checkpoint_dir="/tmp/checkpoints",
        storage_type="file",
    )
    assert config.enabled is False
    assert config.checkpoint_dir == "/tmp/checkpoints"
    assert config.storage_type == "file"


# ============================================================================
# CheckpointMetadata 测试
# ============================================================================

def test_checkpoint_metadata_creation() -> None:
    """测试元数据创建。"""
    metadata = CheckpointMetadata(
        thread_id="thread_123",
        checkpoint_id="cp_abc",
        created_at="2024-01-01T00:00:00",
        workflow_stage="analytics_build_sql",
        workflow_outcome=None,
        node_name="analytics_build_sql",
    )
    assert metadata.thread_id == "thread_123"
    assert metadata.checkpoint_id == "cp_abc"
    assert metadata.workflow_stage == "analytics_build_sql"


def test_checkpoint_metadata_to_dict() -> None:
    """测试转换为字典。"""
    metadata = CheckpointMetadata(
        thread_id="thread_123",
        checkpoint_id="cp_abc",
        created_at="2024-01-01T00:00:00",
        workflow_stage="analytics_build_sql",
    )
    d = metadata.to_dict()
    assert d["thread_id"] == "thread_123"
    assert d["checkpoint_id"] == "cp_abc"


# ============================================================================
# MemoryCheckpointStore 测试
# ============================================================================

def test_memory_store_save_and_load() -> None:
    """测试保存和加载。"""
    store = MemoryCheckpointStore()
    state = {"query": "test", "workflow_stage": "analytics_plan"}

    store.save("thread_1", "cp_1", state)
    loaded = store.load("thread_1", "cp_1")

    assert loaded is not None
    assert loaded["query"] == "test"


def test_memory_store_load_nonexistent() -> None:
    """测试加载不存在的 checkpoint。"""
    store = MemoryCheckpointStore()
    loaded = store.load("nonexistent_thread", "cp_1")
    assert loaded is None


def test_memory_store_load_latest() -> None:
    """测试加载最新的 checkpoint。"""
    store = MemoryCheckpointStore()
    store.save("thread_1", "cp_1", {"step": 1})
    store.save("thread_1", "cp_2", {"step": 2})
    store.save("thread_1", "cp_3", {"step": 3})

    loaded = store.load("thread_1", None)  # None = latest
    assert loaded["step"] == 3


def test_memory_store_list_checkpoints() -> None:
    """测试列出 checkpoint。"""
    store = MemoryCheckpointStore()
    store.save("thread_1", "cp_1", {"workflow_stage": "plan"})
    store.save("thread_1", "cp_2", {"workflow_stage": "build_sql"})
    store.save("thread_2", "cp_3", {"workflow_stage": "execute"})

    checkpoints = store.list_checkpoints("thread_1")
    assert len(checkpoints) == 2
    assert all(cp.thread_id == "thread_1" for cp in checkpoints)


def test_memory_store_delete() -> None:
    """测试删除 checkpoint。"""
    store = MemoryCheckpointStore()
    store.save("thread_1", "cp_1", {"step": 1})
    store.save("thread_1", "cp_2", {"step": 2})

    store.delete("thread_1", "cp_1")

    checkpoints = store.list_checkpoints("thread_1")
    assert len(checkpoints) == 1
    assert checkpoints[0].checkpoint_id == "cp_2"


def test_memory_store_clear() -> None:
    """测试清空所有 checkpoint。"""
    store = MemoryCheckpointStore()
    store.save("thread_1", "cp_1", {"step": 1})
    store.save("thread_2", "cp_2", {"step": 2})

    store.clear()

    assert len(store.list_checkpoints("thread_1")) == 0
    assert len(store.list_checkpoints("thread_2")) == 0


# ============================================================================
# WorkflowCheckpointManager 测试
# ============================================================================

def test_checkpoint_manager_start() -> None:
    """测试启动 checkpoint 会话。"""
    manager = create_checkpoint_manager(enabled=True)
    initial_state = {"query": "test"}

    checkpoint_id = manager.start_checkpoint("thread_123", initial_state)

    assert checkpoint_id is not None
    assert checkpoint_id.startswith("cp_")


def test_checkpoint_manager_disabled() -> None:
    """测试禁用时的行为。"""
    manager = create_checkpoint_manager(enabled=False)
    initial_state = {"query": "test"}

    checkpoint_id = manager.start_checkpoint("thread_123", initial_state)
    assert checkpoint_id is None

    saved = manager.save_checkpoint(initial_state)
    assert saved is None


def test_checkpoint_manager_save_and_restore() -> None:
    """测试保存和恢复。"""
    manager = create_checkpoint_manager(enabled=True)
    initial_state = {
        "query": "查询发电量",
        "workflow_stage": "analytics_plan",
    }

    manager.start_checkpoint("thread_123", initial_state)
    manager.save_checkpoint({"query": "查询发电量", "workflow_stage": "analytics_build_sql"})

    restored = manager.restore_checkpoint("thread_123")
    assert restored is not None
    assert "workflow_stage" in restored


def test_checkpoint_manager_node_checkpoint() -> None:
    """测试节点级 checkpoint。"""
    manager = create_checkpoint_manager(enabled=True)
    manager.start_checkpoint("thread_123", {"query": "test"})

    cp1 = manager.save_node_checkpoint({"step": 1}, "analytics_plan")
    cp2 = manager.save_node_checkpoint({"step": 2}, "analytics_build_sql")

    assert cp1 is not None
    assert cp2 is not None
    assert cp1 != cp2


def test_checkpoint_manager_list() -> None:
    """测试列出 checkpoint。"""
    manager = create_checkpoint_manager(enabled=True)
    manager.start_checkpoint("thread_123", {"step": 0})
    manager.save_node_checkpoint({"step": 1}, "analytics_plan")
    manager.save_node_checkpoint({"step": 2}, "analytics_build_sql")

    checkpoints = manager.list_checkpoints("thread_123")
    assert len(checkpoints) >= 3  # 包含 start + 2 node checkpoints


def test_checkpoint_manager_current_ids() -> None:
    """测试获取当前 ID。"""
    manager = create_checkpoint_manager(enabled=True)
    manager.start_checkpoint("thread_123", {"step": 0})

    assert manager.get_current_thread_id() == "thread_123"
    assert manager.get_current_checkpoint_id() is not None


# ============================================================================
# 序列化测试
# ============================================================================

def test_serialize_state_with_pydantic() -> None:
    """测试序列化包含 Pydantic 模型的状态。"""
    from pydantic import BaseModel

    class MockModel(BaseModel):
        name: str
        value: int

    manager = create_checkpoint_manager(enabled=True)
    manager.start_checkpoint("thread_123", {"step": 0})

    state_with_pydantic = {
        "query": "test",
        "model": MockModel(name="test", value=42),
        "list": [1, 2, 3],
        "nested": {"a": {"b": "c"}},
    }

    # 应该能正常序列化
    saved = manager.save_checkpoint(state_with_pydantic)
    assert saved is not None


def test_serialize_state_with_complex_objects() -> None:
    """测试序列化包含复杂对象的状态。"""
    manager = create_checkpoint_manager(enabled=True)
    manager.start_checkpoint("thread_123", {"step": 0})

    state = {
        "query": "test",
        "callable": lambda x: x,  # 不可序列化
        "nested": {
            "datetime": "2024-01-01",  # 转为字符串
        },
    }

    # 应该能正常序列化（不可序列化的转为字符串）
    saved = manager.save_checkpoint(state)
    assert saved is not None
