"""
SQL Gateway（SQL MCP-compatible 执行入口 / 传输抽象层）。

=================================================================
模块定位
=================================================================
当前阶段不再直接操作 sqlite3，而是正式收口为"SQL MCP-compatible client"：
- Service 层（analytics_service.py）只知道自己要发起一个只读 SQL 请求
- Gateway 负责把请求发给 SQL MCP Server 风格的执行层
- 当前 transport 先用"进程内 server 调用（inprocess_mcp_server）"落地
- 后续如果切成远端 SQL MCP Server（HTTP/gRPC），只需要替换 Gateway 内部 transport

=================================================================
为什么必须有这一层（传输抽象层的价值）
=================================================================
1. 经营分析要逐步接近真实企业可用，不能让业务代码直接耦合某个本地数据库实现
   → 如果 analytics_service.py 直接 import sqlite3，后续切 PostgreSQL 要改所有调用方
2. SQL 执行契约（SQLReadQueryRequest / SQLReadQueryResponse）需要稳定
    → 不管底层是 SQLite/PostgreSQL/MySQL/数仓，契约不变
3. Gateway 是 data_source routing、超时、row_limit、错误归一化的天然边界
   → 在这里统一处理：超时 → 重试；行数超限 → 截断；连接失败 → 归一化错误码

=================================================================
当前阶段 transport 策略
=================================================================
默认使用 inprocess_mcp_server：Gateway 不自己执行 SQL，而是把请求发给进程内
SQL MCP Server（core/tools/mcp/sql_mcp_server.py）执行。

这样做的好处：
- Gateway 和 Server 之间的接口是 MCP 契约（SQLReadQueryRequest / SQLReadQueryResponse）
- 后续切到远端 MCP Server 时，只需把 inprocess 调用换成 HTTP/gRPC client
- 不需要改动 analytics_service.py 或任何上游代码

=================================================================
数据流转
=================================================================
analytics_service.py
  → sql_gateway.execute_readonly_query(request)
    → 校验 transport_mode（当前仅 inprocess_mcp_server）
    → server.execute_readonly_query(request)  ← 实际执行
      → 根据 data_source 路由到对应数据库连接
      → 执行 SQL（只读）
      → 返回 SQLReadQueryResponse {columns, rows, row_count, latency_ms}
"""

from __future__ import annotations

from dataclasses import asdict

from core.analytics.schema_registry import SchemaRegistry
from core.config.settings import Settings, get_settings
from core.tools.mcp import (
    SQLGatewayExecutionError,
    SQLHealthcheckRequest,
    SQLMCPServer,
    SQLReadQueryRequest,
    SQLReadQueryResponse,
)


class SQLGateway:
    """
    SQL MCP-compatible 执行网关（传输抽象层）。

    职责：
    - 接收上游（analytics_service.py）的只读 SQL 请求
    - 校验 transport_mode 配置
    - 把请求委托给 SQL MCP Server 执行
    - 返回标准化的 SQLReadQueryResponse

    不负责：
    - 不直接执行 SQL（交给 SQLMCPServer）
    - 不做安全检查（SQL Guard 在上游已完成）
    - 不做 SQL 生成（SQLBuilder 在上游已完成）
    - 不做数据库连接管理（Server 负责）
    """

    def __init__(
        self,
        *,
        schema_registry: SchemaRegistry,
        settings: Settings | None = None,
        server: SQLMCPServer | None = None,
    ) -> None:
        """
        初始化 SQL Gateway。

        参数：
        - schema_registry：表结构/数据源定义，透传给 Server 用于 data_source routing
        - settings：应用配置（可选，默认 get_settings()）。核心配置项：
          analytics_sql_gateway_transport_mode：当前固定为 "inprocess_mcp_server"
        - server：SQL MCP Server 实例（可选，默认新建）。测试时可 Mock 替换

        依赖注入模式：所有外部依赖通过构造函数传入，方便单元测试。
        """

        self.schema_registry = schema_registry
        self.settings = settings or get_settings()
        self.server = server or SQLMCPServer(schema_registry=schema_registry)

    def execute_readonly_query(self, request: SQLReadQueryRequest) -> SQLReadQueryResponse:
        """
        执行只读 SQL 查询。

        当前阶段的 transport 决策：
        - 默认使用 inprocess_mcp_server：进程内调用 SQL MCP Server
        - 后续如果切成 HTTP/gRPC/真正 MCP transport，这里的方法签名不需要变
          → 只需在 Server 层替换 transport 实现

        参数：
        - request.data_source：数据源标识（如 "local_analytics"），Server 据此路由到对应 DB
        - request.sql：已通过 SQL Guard 校验的只读 SQL（含 LIMIT）
        - request.timeout_ms：超时时间（毫秒），默认 3000
        - request.row_limit：最大返回行数，默认 500
        - request.trace_id/run_id：用于全链路追踪

        返回：
        SQLReadQueryResponse {columns, rows, row_count, latency_ms, data_source, db_type, query_status}

        异常：
        - transport_mode 不是 inprocess_mcp_server → SQLGatewayExecutionError
        - Server 执行超时 → SQLGatewayExecutionError（上游可重试）
        - Server 执行 SQL 错误 → SQLGatewayExecutionError（不可重试）

        重试策略说明（由上游 analytics_service.py 决定）：
        - TimeoutError → 可重试一次（临时网络/负载问题，重试可能成功）
        - SQL 语法错误 → 不可重试（SQL 本身的问题，重试无意义）
        - 连接失败 → 可重试一次（数据库连接池临时耗尽）
        """

        # 当前阶段严格限制 transport_mode，只允许 inprocess_mcp_server
        # 这是防御性编程——防止配置错误导致 SQL 走到未初始化的 transport
        if self.settings.analytics_sql_gateway_transport_mode != "inprocess_mcp_server":
            raise SQLGatewayExecutionError(
                "当前仅支持 inprocess_mcp_server transport",
                error_code="sql_gateway_transport_unsupported",
                detail={
                    "transport_mode": self.settings.analytics_sql_gateway_transport_mode,
                    "data_source": request.data_source,
                },
            )

        # 委托给 SQL MCP Server 执行
        # Server 内部做：data_source routing → DB 连接 → SQL 执行 → 结果归一化
        return self.server.execute_readonly_query(request)

    def healthcheck(self, data_source: str | None = None) -> dict:
        """
        执行最小健康检查（用于监控和 readiness probe）。

        参数：
        - data_source：指定要检查的数据源（None 时检查所有数据源）

        返回：
        {"status": "healthy", "data_source": "...", "latency_ms": ...}
        或 {"status": "unhealthy", "error": "..."}
        """

        response = self.server.healthcheck(SQLHealthcheckRequest(data_source=data_source))
        return asdict(response)
