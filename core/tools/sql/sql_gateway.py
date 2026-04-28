"""SQL Gateway。

当前阶段这里先实现“本地版 SQL MCP 风格网关”，目标不是替代未来真实 SQL MCP，
而是先把接口契约和分层边界做对：

- Service 层只知道“我要执行一个只读 SQL”；
- Gateway 负责数据源路由、超时参数、行数限制、健康检查；
- 后续如果接真实 SQL MCP server、只读 PostgreSQL 或数据仓库，
  只需要替换 Gateway 内部实现，不需要改 AnalyticsService。

为什么不直接在 Service 里写 sqlite3：
1. 会导致业务逻辑和底层连接逻辑耦合；
2. 后续切真实数据源会大面积改代码；
3. 无法清晰表达 data_source routing / timeout / row limit 这些基础设施语义。
"""

from __future__ import annotations

import sqlite3
import time

from core.analytics.schema_registry import SchemaRegistry
from core.tools.mcp.sql_mcp_contracts import (
    SQLGatewayExecutionError,
    SQLReadQueryRequest,
    SQLReadQueryResponse,
)


class SQLGateway:
    """最小 SQL Gateway。"""

    def __init__(self, schema_registry: SchemaRegistry) -> None:
        self.schema_registry = schema_registry
        self._connections: dict[str, sqlite3.Connection] = {}

    def execute_readonly_query(self, request: SQLReadQueryRequest) -> SQLReadQueryResponse:
        """执行只读 SQL。

        当前方法的 request / response 已经向 SQL MCP-compatible 契约收口：
        - request 中显式携带 data_source、sql、timeout_ms、row_limit、trace_id、run_id；
        - response 中显式携带 rows、columns、row_count、latency_ms、checked_sql；
        - 后续如果 transport 改成真实 MCP client，AnalyticsService 不需要改调用方式。
        """

        source_definition = self.schema_registry.get_data_source(request.data_source)
        connection = self._get_connection(source_definition.key)
        normalized_sql = self._apply_row_limit(request.sql, row_limit=request.row_limit)

        try:
            started_at = time.perf_counter()
            cursor = connection.cursor()
            cursor.execute(normalized_sql)
            rows = [dict(item) for item in cursor.fetchall()]
            latency_ms = int((time.perf_counter() - started_at) * 1000)
        except Exception as exc:  # pragma: no cover - 底层执行异常兜底
            raise SQLGatewayExecutionError(
                "SQL Gateway 执行失败",
                detail={
                    "data_source": request.data_source,
                    "trace_id": request.trace_id,
                    "run_id": request.run_id,
                },
            ) from exc

        columns = list(rows[0].keys()) if rows else [item[0] for item in cursor.description or []]
        return SQLReadQueryResponse(
            data_source=source_definition.key,
            db_type=source_definition.db_type,
            rows=rows,
            columns=columns,
            row_count=len(rows),
            latency_ms=latency_ms,
            checked_sql=normalized_sql,
            trace_id=request.trace_id,
            run_id=request.run_id,
            metadata={
                "timeout_ms": request.timeout_ms,
            },
        )

    def healthcheck(self, data_source: str | None = None) -> dict:
        """执行最小健康检查。"""

        source_definition = self.schema_registry.get_data_source(data_source)
        connection = self._get_connection(source_definition.key)
        cursor = connection.cursor()
        cursor.execute("SELECT 1 AS ok")
        row = cursor.fetchone()
        return {
            "healthy": row is not None and row["ok"] == 1,
            "data_source": source_definition.key,
            "db_type": source_definition.db_type,
        }

    def _get_connection(self, data_source: str) -> sqlite3.Connection:
        """按数据源获取连接。

        当前阶段每个数据源使用一个内存 SQLite 连接，
        未来如果接 SQL MCP，则这里可以替换成 Client Session。
        """

        if data_source not in self._connections:
            connection = sqlite3.connect(":memory:")
            connection.row_factory = sqlite3.Row
            self._bootstrap_local_analytics_source(connection)
            self._connections[data_source] = connection
        return self._connections[data_source]

    def _bootstrap_local_analytics_source(self, connection: sqlite3.Connection) -> None:
        """初始化本地经营分析样例数据。"""

        cursor = connection.cursor()
        cursor.execute(
            """
            CREATE TABLE analytics_metrics_daily (
                biz_date TEXT NOT NULL,
                metric_code TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                region_name TEXT NOT NULL,
                station_name TEXT NOT NULL,
                metric_value REAL NOT NULL
            )
            """
        )

        sample_rows = [
            ("2024-03-01", "generation", "发电量", "新疆区域", "哈密电站", 1200.0),
            ("2024-03-02", "generation", "发电量", "新疆区域", "哈密电站", 1350.0),
            ("2024-03-03", "generation", "发电量", "新疆区域", "吐鲁番电站", 980.0),
            ("2024-03-04", "generation", "发电量", "北疆区域", "阿勒泰电站", 760.0),
            ("2024-03-05", "generation", "发电量", "南疆区域", "和田电站", 680.0),
            ("2024-03-01", "revenue", "收入", "新疆区域", "哈密电站", 320.0),
            ("2024-03-02", "revenue", "收入", "新疆区域", "吐鲁番电站", 305.0),
            ("2024-03-03", "cost", "成本", "新疆区域", "哈密电站", 210.0),
            ("2024-03-04", "profit", "利润", "新疆区域", "哈密电站", 110.0),
            ("2024-04-01", "generation", "发电量", "新疆区域", "哈密电站", 1400.0),
            ("2024-04-02", "generation", "发电量", "新疆区域", "吐鲁番电站", 1110.0),
        ]
        cursor.executemany(
            """
            INSERT INTO analytics_metrics_daily (
                biz_date,
                metric_code,
                metric_name,
                region_name,
                station_name,
                metric_value
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            sample_rows,
        )
        connection.commit()

    def _apply_row_limit(self, sql: str, *, row_limit: int) -> str:
        """确保 SQL 有明确的返回行数上限。"""

        upper_sql = sql.upper()
        if " LIMIT " in upper_sql:
            return sql
        return f"{sql} LIMIT {row_limit}"
