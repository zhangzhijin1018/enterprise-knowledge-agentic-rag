"""最小 SQL MCP Server。

当前阶段这里实现的是“进程内 SQL MCP server”：
- 对外暴露的输入输出严格围绕 SQLReadQueryRequest / SQLReadQueryResponse；
- 内部仍然可以连接本地样例数据源或真实只读数据源；
- Gateway 通过 server 调用执行链路，而不是自己直接操作数据库连接。

这样做的意义：
1. AnalyticsService 只依赖稳定 contract，不再关心底层 transport；
2. 当前即使还没有把 SQL MCP 独立部署成远端服务，接口边界已经收口；
3. 后续如果扩成 HTTP / gRPC / 真正 MCP server，只需要替换 transport，不需要改经营分析业务编排。
"""

from __future__ import annotations

import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from core.analytics.schema_registry import DataSourceDefinition, SchemaRegistry
from core.tools.mcp.sql_mcp_contracts import (
    SQLGatewayExecutionError,
    SQLHealthcheckRequest,
    SQLHealthcheckResponse,
    SQLMCPError,
    SQLReadQueryRequest,
    SQLReadQueryResponse,
)


class SQLMCPServer:
    """最小 SQL MCP Server。

    说明：
    - 当前不是完整标准 MCP server；
    - 但已经把“数据源路由、只读执行、统一返回结构、统一错误结构”收口到 server 侧；
    - Gateway 可以把这里视为未来远端 MCP server 的本地替身。
    """

    def __init__(self, schema_registry: SchemaRegistry) -> None:
        self.schema_registry = schema_registry
        self._engines: dict[str, Engine] = {}

    def execute_readonly_query(self, request: SQLReadQueryRequest) -> SQLReadQueryResponse:
        """执行只读 SQL 查询。

        关键边界：
        - 这里只负责执行 contract 中定义好的只读查询；
        - 不负责生成 SQL，也不负责做 SQL Guard；
        - 业务层必须先完成槽位化、SQL 模板构造和安全校验，再把 checked_sql 发到这里。
        """

        source_definition = self.schema_registry.get_data_source(request.data_source)
        engine = self._get_engine(source_definition)
        normalized_sql = self._apply_row_limit(request.sql, row_limit=request.row_limit)

        try:
            started_at = time.perf_counter()
            with engine.connect() as connection:
                result = connection.execute(text(normalized_sql))
                rows = [dict(row._mapping) for row in result]
            latency_ms = int((time.perf_counter() - started_at) * 1000)
        except Exception as exc:  # pragma: no cover - 底层执行异常兜底
            raise SQLGatewayExecutionError(
                "SQL MCP Server 执行失败",
                error_code="sql_mcp_server_execute_failed",
                detail=self.build_error_payload(
                    error_code="sql_mcp_server_execute_failed",
                    message=str(exc),
                    data_source=source_definition.key,
                    trace_id=request.trace_id,
                    run_id=request.run_id,
                ).__dict__,
            ) from exc

        columns = list(rows[0].keys()) if rows else []
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
                "server_mode": "inprocess_sql_mcp_server",
            },
        )

    def healthcheck(self, request: SQLHealthcheckRequest | None = None) -> SQLHealthcheckResponse:
        """执行最小健康检查。"""

        request = request or SQLHealthcheckRequest()
        source_definition = self.schema_registry.get_data_source(request.data_source)
        engine = self._get_engine(source_definition)
        started_at = time.perf_counter()

        try:
            with engine.connect() as connection:
                row = connection.execute(text("SELECT 1 AS ok")).first()
            healthy = bool(row and row._mapping.get("ok") == 1)
        except Exception as exc:  # pragma: no cover - 健康检查失败保护
            raise SQLGatewayExecutionError(
                "SQL MCP Server 健康检查失败",
                error_code="sql_mcp_server_healthcheck_failed",
                detail=self.build_error_payload(
                    error_code="sql_mcp_server_healthcheck_failed",
                    message=str(exc),
                    data_source=source_definition.key,
                    trace_id=request.trace_id,
                    run_id=request.run_id,
                ).__dict__,
            ) from exc

        latency_ms = int((time.perf_counter() - started_at) * 1000)
        return SQLHealthcheckResponse(
            healthy=healthy,
            data_source=source_definition.key,
            db_type=source_definition.db_type,
            latency_ms=latency_ms,
            trace_id=request.trace_id,
            run_id=request.run_id,
            metadata={
                "server_mode": "inprocess_sql_mcp_server",
            },
        )

    def build_error_payload(
        self,
        *,
        error_code: str,
        message: str,
        data_source: str,
        trace_id: str | None,
        run_id: str | None,
    ) -> SQLMCPError:
        """构造统一错误结构。

        这里先在 server 侧把错误形状固定下来，
        后续无论 transport 是进程内调用、HTTP 还是标准 MCP，都可以复用同一错误 payload。
        """

        return SQLMCPError(
            error_code=error_code,
            message=message,
            detail={
                "data_source": data_source,
                "trace_id": trace_id,
                "run_id": run_id,
            },
        )

    def _get_engine(self, source_definition: DataSourceDefinition) -> Engine:
        """按数据源获取或创建 SQLAlchemy Engine。"""

        if source_definition.key in self._engines:
            return self._engines[source_definition.key]

        if source_definition.connection_uri:
            engine = create_engine(source_definition.connection_uri, future=True)
        else:
            engine = create_engine(
                "sqlite://",
                future=True,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
            self._bootstrap_local_analytics_source(engine)

        self._engines[source_definition.key] = engine
        return engine

    def _bootstrap_local_analytics_source(self, engine: Engine) -> None:
        """初始化本地经营分析样例数据源。

        当前阶段保留本地样例源有两个现实价值：
        1. 没有真实业务库时，研发和测试仍能完整联调经营分析闭环；
        2. SQL MCP contract、SQL Guard、AnalyticsService 的回归测试能稳定运行；
        3. 一旦企业环境提供真实只读库，只需要通过配置切默认 data_source。
        """

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS analytics_metrics_daily (
                        biz_date TEXT NOT NULL,
                        metric_code TEXT NOT NULL,
                        metric_name TEXT NOT NULL,
                        region_name TEXT NOT NULL,
                        station_name TEXT NOT NULL,
                        metric_value REAL NOT NULL
                    )
                    """
                )
            )
            row_count = connection.execute(
                text("SELECT COUNT(1) AS cnt FROM analytics_metrics_daily")
            ).scalar_one()
            if row_count:
                return
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
            for row in sample_rows:
                connection.execute(
                    text(
                        """
                        INSERT INTO analytics_metrics_daily (
                            biz_date,
                            metric_code,
                            metric_name,
                            region_name,
                            station_name,
                            metric_value
                        ) VALUES (
                            :biz_date,
                            :metric_code,
                            :metric_name,
                            :region_name,
                            :station_name,
                            :metric_value
                        )
                        """
                    ),
                    {
                        "biz_date": row[0],
                        "metric_code": row[1],
                        "metric_name": row[2],
                        "region_name": row[3],
                        "station_name": row[4],
                        "metric_value": row[5],
                    },
                )

    def _apply_row_limit(self, sql: str, *, row_limit: int) -> str:
        """确保 SQL 有明确的返回行数上限。"""

        upper_sql = sql.upper()
        if " LIMIT " in upper_sql:
            return sql
        return f"{sql} LIMIT {row_limit}"
