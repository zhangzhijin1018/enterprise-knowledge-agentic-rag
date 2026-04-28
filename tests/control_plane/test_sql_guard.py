"""SQL Guard 测试。"""

from __future__ import annotations

from core.agent.control_plane.sql_guard import SQLGuard


def test_sql_guard_allows_select_and_adds_limit() -> None:
    """合法 SELECT 应通过，并自动补 LIMIT。"""

    guard = SQLGuard(allowed_tables=["analytics_metrics_daily"], default_limit=100)

    result = guard.validate(
        "SELECT metric_name, SUM(metric_value) AS total_value FROM analytics_metrics_daily"
    )

    assert result.is_safe is True
    assert result.checked_sql is not None
    assert "LIMIT 100" in result.checked_sql


def test_sql_guard_blocks_dangerous_sql() -> None:
    """危险 SQL 应被拦截。"""

    guard = SQLGuard(allowed_tables=["analytics_metrics_daily"])

    result = guard.validate("DELETE FROM analytics_metrics_daily")

    assert result.is_safe is False
    assert result.blocked_reason is not None
