"""
SQL MCP Server - 基于 python_a2a.mcp.FastMCP 的标准化 MCP 服务

使用 FastMCP 装饰器定义工具，通过 HTTP 提供 SQL 查询能力。

启动方式：
```bash
python -m core.tools.mcp.sql_mcp_server
# 或
uvicorn core.tools.mcp.sql_mcp_server:app --host 0.0.0.0 --port 5001
```

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import asdict

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

logger = logging.getLogger(__name__)

# ============================================================================
# FastMCP Server（参考 agent_learn 风格）
# ============================================================================

from python_a2a.mcp import FastMCP, create_fastapi_app

# 创建 FastMCP Server
mcp = FastMCP(
    name="SQL MCPTools",
    description="提供 SQL 查询工具 - 支持只读查询经营分析数据",
    version="1.0.0"
)


# ============================================================================
# MCP 工具定义（使用 @mcp.tool 装饰器）
# ============================================================================

# 全局 Schema Registry（懒加载）
_schema_registry: SchemaRegistry | None = None
_engines: dict[str, Engine] = {}


def _get_schema_registry() -> SchemaRegistry:
    """获取 Schema Registry 实例"""
    global _schema_registry
    if _schema_registry is None:
        _schema_registry = SchemaRegistry()
    return _schema_registry


def _get_engine(source_definition: DataSourceDefinition) -> Engine:
    """获取或创建 SQLAlchemy Engine"""
    global _engines

    if source_definition.key in _engines:
        return _engines[source_definition.key]

    if source_definition.connection_uri:
        engine = create_engine(source_definition.connection_uri, future=True)
        if source_definition.db_type == "sqlite":
            _bootstrap_local_analytics_source(engine)
    else:
        engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        _bootstrap_local_analytics_source(engine)

    _engines[source_definition.key] = engine
    return engine


def _bootstrap_local_analytics_source(engine: Engine) -> None:
    """初始化本地经营分析样例数据源"""
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
                    department_code TEXT NOT NULL,
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
            ("2024-03-01", "generation", "发电量", "新疆区域", "哈密电站", "analytics-center", 1200.0),
            ("2024-03-02", "generation", "发电量", "新疆区域", "哈密电站", "analytics-center", 1350.0),
            ("2024-03-03", "generation", "发电量", "新疆区域", "吐鲁番电站", "analytics-center", 980.0),
            ("2024-03-04", "generation", "发电量", "北疆区域", "阿勒泰电站", "analytics-center", 760.0),
            ("2024-03-05", "generation", "发电量", "南疆区域", "和田电站", "analytics-center", 680.0),
            ("2024-03-01", "revenue", "收入", "新疆区域", "哈密电站", "analytics-center", 320.0),
            ("2024-03-02", "revenue", "收入", "新疆区域", "吐鲁番电站", "analytics-center", 305.0),
            ("2024-03-03", "cost", "成本", "新疆区域", "哈密电站", "analytics-center", 210.0),
            ("2024-03-04", "profit", "利润", "新疆区域", "哈密电站", "analytics-center", 110.0),
            ("2024-04-01", "generation", "发电量", "新疆区域", "哈密电站", "analytics-center", 1400.0),
            ("2024-04-02", "generation", "发电量", "新疆区域", "吐鲁番电站", "analytics-center", 1110.0),
            ("2024-03-01", "generation", "发电量", "北疆区域", "克拉玛依电站", "north-ops", 860.0),
            ("2024-03-02", "generation", "发电量", "北疆区域", "阿勒泰电站", "north-ops", 920.0),
        ]
        for row in sample_rows:
            connection.execute(
                text(
                    """
                    INSERT INTO analytics_metrics_daily (
                        biz_date, metric_code, metric_name, region_name,
                        station_name, department_code, metric_value
                    ) VALUES (
                        :biz_date, :metric_code, :metric_name, :region_name,
                        :station_name, :department_code, :metric_value
                    )
                    """
                ),
                {
                    "biz_date": row[0],
                    "metric_code": row[1],
                    "metric_name": row[2],
                    "region_name": row[3],
                    "station_name": row[4],
                    "department_code": row[5],
                    "metric_value": row[6],
                },
            )


def _apply_row_limit(sql: str, row_limit: int = 100) -> str:
    """确保 SQL 有明确的返回行数上限"""
    upper_sql = sql.upper()
    if " LIMIT " in upper_sql:
        return sql
    return f"{sql} LIMIT {row_limit}"


# ============================================================================
# MCP 工具 1：execute_sql_query（执行只读 SQL 查询）
# ============================================================================

@mcp.tool(
    name="execute_sql_query",
    description="执行只读 SQL 查询，返回分析结果"
)
async def execute_sql_query(**kwargs) -> str:
    """
    执行只读 SQL 查询

    参数（通过 kwargs 传入）：
    - data_source: 数据源标识（默认 "analytics-db"）
    - sql: 要执行的 SQL 语句（必须是 SELECT）
    - row_limit: 返回行数限制（默认 100）
    - trace_id: 追踪 ID（可选）
    - run_id: 运行 ID（可选）

    返回：
    JSON 格式的查询结果
    """
    try:
        logger.info(f"[SQL MCP] execute_sql_query 调用，参数: {kwargs}")

        # 解析参数
        data_source = kwargs.get("data_source", "analytics-db")
        sql_query = kwargs.get("sql", "")
        row_limit = int(kwargs.get("row_limit", 100))
        trace_id = kwargs.get("trace_id")
        run_id = kwargs.get("run_id")

        if not sql_query:
            return '{"status": "error", "message": "SQL 查询语句不能为空"}'

        # 获取数据源
        schema_registry = _get_schema_registry()
        source_definition = schema_registry.get_data_source(data_source)
        engine = _get_engine(source_definition)

        # 规范化 SQL（添加 LIMIT）
        normalized_sql = _apply_row_limit(sql_query, row_limit=row_limit)

        # 执行查询
        started_at = time.perf_counter()
        with engine.connect() as connection:
            result = connection.execute(text(normalized_sql))
            rows = [dict(row._mapping) for row in result]
        latency_ms = int((time.perf_counter() - started_at) * 1000)

        columns = list(rows[0].keys()) if rows else []

        return f'''{{
    "status": "success",
    "data_source": "{data_source}",
    "db_type": "{source_definition.db_type}",
    "rows": {rows},
    "columns": {columns},
    "row_count": {len(rows)},
    "latency_ms": {latency_ms},
    "checked_sql": "{normalized_sql.replace('"', '\\"')}",
    "trace_id": "{trace_id or ""}",
    "run_id": "{run_id or ""}"
}}'''

    except Exception as e:
        logger.error(f"[SQL MCP] execute_sql_query 失败: {e}", exc_info=True)
        return f'{{"status": "error", "message": "{str(e)}"}}'


# ============================================================================
# MCP 工具 2：healthcheck（健康检查）
# ============================================================================

@mcp.tool(
    name="healthcheck",
    description="SQL MCP 服务健康检查"
)
async def healthcheck(**kwargs) -> str:
    """
    执行健康检查

    参数：
    - data_source: 数据源标识（默认 "analytics-db"）

    返回：
    JSON 格式的健康状态
    """
    try:
        logger.info(f"[SQL MCP] healthcheck 调用")

        data_source = kwargs.get("data_source", "analytics-db")
        schema_registry = _get_schema_registry()
        source_definition = schema_registry.get_data_source(data_source)
        engine = _get_engine(source_definition)

        started_at = time.perf_counter()
        with engine.connect() as connection:
            row = connection.execute(text("SELECT 1 AS ok")).first()
        healthy = bool(row and row._mapping.get("ok") == 1)
        latency_ms = int((time.perf_counter() - started_at) * 1000)

        return f'''{{
    "healthy": {str(healthy).lower()},
    "data_source": "{data_source}",
    "db_type": "{source_definition.db_type}",
    "latency_ms": {latency_ms}
}}'''

    except Exception as e:
        logger.error(f"[SQL MCP] healthcheck 失败: {e}", exc_info=True)
        return f'{{"healthy": false, "message": "{str(e)}"}}'


# ============================================================================
# FastAPI 应用（使用 create_fastapi_app）
# ============================================================================

def create_fastapi_app():
    """创建 FastAPI 应用（参考 agent_learn 风格）"""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(
        title="SQL MCP Server",
        description="SQL 查询 MCP 服务 - 基于 FastMCP",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 使用 FastMCP 的 create_fastapi_app（参考 agent_learn）
    return create_fastapi_app(mcp)


# 导出 app
app = create_fastapi_app()


# ============================================================================
# 启动入口
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("SQL_MCP_PORT", "5001"))
    host = os.environ.get("SQL_MCP_HOST", "0.0.0.0")

    logger.info(f"=== SQL MCP Server 信息 ===")
    logger.info(f"名称: {mcp.name}")
    logger.info(f"描述: {mcp.description}")
    logger.info(f"启动于 http://{host}:{port}")
    logger.info(f"MCP 端点: /mcp/v1/tools")

    # 使用 create_fastapi_app 启动（参考 agent_learn）
    app = create_fastapi_app(mcp)
    uvicorn.run(app, host=host, port=port)
