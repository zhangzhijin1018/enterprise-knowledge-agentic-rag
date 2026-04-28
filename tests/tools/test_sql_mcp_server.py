"""SQL MCP Server 测试。"""

from __future__ import annotations

from pathlib import Path

from core.analytics.schema_registry import SchemaRegistry
from core.config.settings import Settings
from core.tools.mcp import SQLHealthcheckRequest, SQLMCPServer, SQLReadQueryRequest


def test_sql_mcp_server_handles_minimal_request_response() -> None:
    """SQL MCP Server 应能处理最小只读请求并返回标准响应。"""

    server = SQLMCPServer(schema_registry=SchemaRegistry())

    health = server.healthcheck(SQLHealthcheckRequest(data_source="local_analytics"))
    result = server.execute_readonly_query(
        SQLReadQueryRequest(
            data_source="local_analytics",
            sql="""
            SELECT metric_name, SUM(metric_value) AS total_value
            FROM analytics_metrics_daily
            WHERE metric_code = 'generation'
            GROUP BY metric_name
            """,
            timeout_ms=2000,
            row_limit=50,
            trace_id="tr_mcp_server_test",
            run_id="run_mcp_server_test",
        )
    )

    assert health.healthy is True
    assert result.data_source == "local_analytics"
    assert result.row_count >= 1
    assert result.trace_id == "tr_mcp_server_test"
    assert result.run_id == "run_mcp_server_test"


def test_sql_mcp_server_supports_configured_sqlite_data_source(tmp_path: Path) -> None:
    """SQL MCP Server 应支持通过配置接入测试 SQLite 数据源。"""

    db_path = tmp_path / "enterprise_readonly.sqlite"
    settings = Settings(
        analytics_real_data_source_url=f"sqlite:///{db_path}",
        analytics_real_data_source_required_permission="analytics:query:enterprise",
    )
    server = SQLMCPServer(schema_registry=SchemaRegistry(settings=settings))

    response = server.execute_readonly_query(
        SQLReadQueryRequest(
            data_source=settings.analytics_real_data_source_key,
            sql="""
            SELECT metric_name, SUM(metric_value) AS total_value
            FROM analytics_metrics_daily
            WHERE metric_code = 'generation'
            GROUP BY metric_name
            """,
            timeout_ms=2000,
            row_limit=10,
        )
    )

    assert response.data_source == settings.analytics_real_data_source_key
    assert response.row_count >= 1
