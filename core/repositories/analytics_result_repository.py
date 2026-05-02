"""经营分析结果仓库。

负责持久化经营分析的重量结果（表格、图表、洞察、报告等）。

设计原则：
- 只负责持久化，不负责业务逻辑
- 提供内存和数据库两种存储方式
- 当前阶段优先内存存储，便于本地开发和测试
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


# 内存存储
_in_memory_store: dict[str, dict] = {}


def reset_in_memory_analytics_result_store() -> None:
    """重置内存存储。"""
    global _in_memory_store
    _in_memory_store = {}


class AnalyticsResultRepository:
    """经营分析结果仓库。

    负责持久化经营分析的重量结果。
    当前阶段使用内存存储，后续可扩展为数据库存储。
    """

    def __init__(self, session=None) -> None:
        self.session = session

    def save_heavy_result(self, run_id: str, heavy_result: dict) -> dict:
        """保存重量结果。

        Args:
            run_id: 运行 ID
            heavy_result: 重量结果，包含 tables、chart_spec、insight_cards、report_blocks 等

        Returns:
            保存后的结果
        """

        timestamp = datetime.now(timezone.utc)

        record = {
            "run_id": run_id,
            "tables": heavy_result.get("tables", []),
            "chart_spec": heavy_result.get("chart_spec"),
            "insight_cards": heavy_result.get("insight_cards", []),
            "report_blocks": heavy_result.get("report_blocks", []),
            "governance_decision": heavy_result.get("governance_decision", {}),
            "audit_info": heavy_result.get("audit_info", {}),
            "created_at": timestamp.isoformat(),
        }

        _in_memory_store[run_id] = record

        return record

    def get_heavy_result(self, run_id: str) -> dict | None:
        """获取重量结果。

        Args:
            run_id: 运行 ID

        Returns:
            重量结果，不存在则返回 None
        """

        return _in_memory_store.get(run_id)

    def delete_heavy_result(self, run_id: str) -> bool:
        """删除重量结果。

        Args:
            run_id: 运行 ID

        Returns:
            是否删除成功
        """

        if run_id in _in_memory_store:
            del _in_memory_store[run_id]
            return True
        return False

    def list_heavy_results(self, limit: int = 100) -> list[dict]:
        """列出最近的重量结果。

        Args:
            limit: 返回数量限制

        Returns:
            重量结果列表
        """

        results = sorted(
            _in_memory_store.values(),
            key=lambda x: x.get("created_at", ""),
            reverse=True,
        )
        return results[:limit]
