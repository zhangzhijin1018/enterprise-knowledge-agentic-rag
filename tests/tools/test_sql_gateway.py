"""SQL Gateway 测试。"""

from __future__ import annotations

from pathlib import Path

from core.config.settings import Settings
from core.analytics.schema_registry import SchemaRegistry
from core.tools.mcp.sql_mcp_contracts import SQLReadQueryRequest
from core.tools.sql.sql_gateway import SQLGateway


def test_sql_gateway_healthcheck_and_execute() -> None:
    """SQL Gateway 最小执行链路应可运行。"""

    gateway = SQLGateway(
        schema_registry=SchemaRegistry(),
        settings=Settings(analytics_sql_gateway_transport_mode="inprocess_mcp_server"),
    )

    health = gateway.healthcheck()
    result = gateway.execute_readonly_query(
        SQLReadQueryRequest(
            data_source="local_analytics",
            sql="""
            SELECT metric_name, SUM(metric_value) AS total_value
            FROM analytics_metrics_daily
            WHERE metric_code = 'generation'
            GROUP BY metric_name
            """,
            timeout_ms=2000,
            row_limit=20,
            trace_id="tr_sql_gateway_test",
            run_id="run_sql_gateway_test",
        )
    )

    assert health["healthy"] is True
    assert result.data_source == "local_analytics"
    assert result.db_type == "sqlite"
    assert result.row_count >= 1
    assert result.checked_sql.endswith("LIMIT 20")
    assert result.trace_id == "tr_sql_gateway_test"
    assert result.run_id == "run_sql_gateway_test"
    assert result.metadata["server_mode"] == "inprocess_sql_mcp_server"


def test_sql_gateway_can_route_to_configured_sqlite_data_source(tmp_path: Path) -> None:
    """Gateway 应支持通过配置路由到测试 SQLite 数据源。"""

    db_path = tmp_path / "analytics_real.sqlite"
    settings = Settings(
        analytics_real_data_source_url=f"sqlite:///{db_path}",
        analytics_real_data_source_required_permission="analytics:query:enterprise",
        analytics_sql_gateway_transport_mode="inprocess_mcp_server",
    )
    registry = SchemaRegistry(settings=settings)
    gateway = SQLGateway(schema_registry=registry, settings=settings)

    result = gateway.execute_readonly_query(
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
            trace_id="tr_real_sqlite_test",
            run_id="run_real_sqlite_test",
        )
    )

    assert result.data_source == settings.analytics_real_data_source_key
    assert result.row_count >= 1
