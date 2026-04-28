"""SQL Gateway 测试。"""

from __future__ import annotations

from core.analytics.schema_registry import SchemaRegistry
from core.tools.mcp.sql_mcp_contracts import SQLReadQueryRequest
from core.tools.sql.sql_gateway import SQLGateway


def test_sql_gateway_healthcheck_and_execute() -> None:
    """SQL Gateway 最小执行链路应可运行。"""

    gateway = SQLGateway(schema_registry=SchemaRegistry())

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
