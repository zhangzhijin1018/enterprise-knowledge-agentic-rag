"""SQL Guard 测试。"""

from __future__ import annotations

from core.agent.control_plane.sql_guard import SQLGuard


def test_sql_guard_allows_select_and_adds_limit() -> None:
    """合法 SELECT 应通过，并自动补 LIMIT。"""

    guard = SQLGuard(allowed_tables=["analytics_metrics_daily"], default_limit=100)

    result = guard.validate(
        "SELECT metric_name, SUM(metric_value) AS total_value FROM analytics_metrics_daily WHERE department_code = 'analytics-center'",
        required_filter_column="department_code",
        required_filter_value="analytics-center",
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


def test_sql_guard_blocks_table_outside_whitelist() -> None:
    """不在表白名单中的表必须被拦截。"""

    guard = SQLGuard(allowed_tables=["analytics_metrics_daily"])

    result = guard.validate("SELECT * FROM secret_finance_table")

    assert result.is_safe is False
    assert result.blocked_reason == "存在未授权表：secret_finance_table"


def test_sql_guard_blocks_sql_without_required_department_filter() -> None:
    """声明需要部门范围过滤时，缺少过滤条件必须被拦截。"""

    guard = SQLGuard(allowed_tables=["analytics_metrics_daily"])

    result = guard.validate(
        "SELECT metric_name, SUM(metric_value) AS total_value FROM analytics_metrics_daily",
        required_filter_column="department_code",
        required_filter_value="analytics-center",
    )

    assert result.is_safe is False
    assert result.blocked_reason == "缺少必需的数据范围过滤：department_code"
