"""SQL Gateway。

当前阶段这里不再直接操作 sqlite3，而是正式收口为“SQL MCP-compatible client”：
- Service 层只知道自己要发起一个只读 SQL 请求；
- Gateway 负责把 request 发给 SQL MCP server 风格执行层；
- 当前 transport 先用“进程内 server 调用”落地；
- 后续如果切成远端 SQL MCP server，只需要替换 Gateway 内部 transport。

为什么必须做这一层：
1. 经营分析要逐步接近真实企业可用，不能让业务代码直接耦合某个本地数据库实现；
2. SQL 执行契约需要稳定，才能承接后续 PostgreSQL / MySQL / 数仓 / SQL MCP server；
3. Gateway 是 data_source routing、超时、row_limit、错误归一化的天然边界。
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
    """SQL MCP-compatible SQL Gateway。"""

    def __init__(
        self,
        *,
        schema_registry: SchemaRegistry,
        settings: Settings | None = None,
        server: SQLMCPServer | None = None,
    ) -> None:
        self.schema_registry = schema_registry
        self.settings = settings or get_settings()
        self.server = server or SQLMCPServer(schema_registry=schema_registry)

    def execute_readonly_query(self, request: SQLReadQueryRequest) -> SQLReadQueryResponse:
        """执行只读 SQL。

        当前阶段的 transport 决策：
        - 默认使用 `inprocess_mcp_server`；
        - 也就是 Gateway 不自己执行 SQL，而是把请求发给进程内 SQL MCP Server；
        - 后续如果切成 HTTP / gRPC / 真正 MCP transport，这里的方法签名不需要变。
        """

        if self.settings.analytics_sql_gateway_transport_mode != "inprocess_mcp_server":
            raise SQLGatewayExecutionError(
                "当前仅支持 inprocess_mcp_server transport",
                error_code="sql_gateway_transport_unsupported",
                detail={
                    "transport_mode": self.settings.analytics_sql_gateway_transport_mode,
                    "data_source": request.data_source,
                },
            )
        return self.server.execute_readonly_query(request)

    def healthcheck(self, data_source: str | None = None) -> dict:
        """执行最小健康检查。"""

        response = self.server.healthcheck(SQLHealthcheckRequest(data_source=data_source))
        return asdict(response)
