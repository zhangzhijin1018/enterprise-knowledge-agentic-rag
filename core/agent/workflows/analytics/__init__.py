"""经营分析微观工作流导出。

这里使用惰性导出而不是模块加载时立刻 import 全部对象，原因是：
1. `AnalyticsService -> SnapshotBuilder` 会从本包读取轻量快照构造层；
2. 如果 `__init__` 再 eager import `adapter -> graph -> nodes -> service`，
   会重新形成导入环；
3. 因此这里通过 `__getattr__` 做懒加载，既保留对外导出体验，也避免循环依赖。
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型提示
    from core.agent.workflows.analytics.adapter import AnalyticsWorkflowAdapter
    from core.agent.workflows.analytics.degradation import AnalyticsWorkflowDegradationController
    from core.agent.workflows.analytics.graph import AnalyticsLangGraphWorkflow
    from core.agent.workflows.analytics.retry_policy import AnalyticsWorkflowRetryController
    from core.agent.workflows.analytics.snapshot_builder import AnalyticsSnapshotBuilder
    from core.agent.workflows.analytics.state import (
        AnalyticsWorkflowOutcome,
        AnalyticsWorkflowStage,
        AnalyticsWorkflowState,
    )
    from core.agent.workflows.analytics.status_mapper import AnalyticsWorkflowStatusMapper

__all__ = [
    "AnalyticsLangGraphWorkflow",
    "AnalyticsWorkflowAdapter",
    "AnalyticsWorkflowDegradationController",
    "AnalyticsSnapshotBuilder",
    "AnalyticsWorkflowState",
    "AnalyticsWorkflowStage",
    "AnalyticsWorkflowOutcome",
    "AnalyticsWorkflowStatusMapper",
    "AnalyticsWorkflowRetryController",
]


def __getattr__(name: str) -> Any:
    """按需导出经营分析 workflow 相关对象。"""

    if name == "AnalyticsWorkflowAdapter":
        return getattr(import_module("core.agent.workflows.analytics.adapter"), name)
    if name == "AnalyticsWorkflowDegradationController":
        return getattr(import_module("core.agent.workflows.analytics.degradation"), name)
    if name == "AnalyticsLangGraphWorkflow":
        return getattr(import_module("core.agent.workflows.analytics.graph"), name)
    if name == "AnalyticsWorkflowRetryController":
        return getattr(import_module("core.agent.workflows.analytics.retry_policy"), name)
    if name == "AnalyticsSnapshotBuilder":
        return getattr(import_module("core.agent.workflows.analytics.snapshot_builder"), name)
    if name in {"AnalyticsWorkflowState", "AnalyticsWorkflowStage", "AnalyticsWorkflowOutcome"}:
        return getattr(import_module("core.agent.workflows.analytics.state"), name)
    if name == "AnalyticsWorkflowStatusMapper":
        return getattr(import_module("core.agent.workflows.analytics.status_mapper"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
