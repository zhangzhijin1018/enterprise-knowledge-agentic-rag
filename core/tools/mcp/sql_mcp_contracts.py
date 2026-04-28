"""SQL MCP-compatible contracts。

注意：
- 当前实现还不是完整标准 MCP server；
- 这里定义的是“面向未来 SQL MCP server 的 request / response contract”；
- 当前阶段既支持进程内 server 调用，也为后续 HTTP / gRPC / 真正 MCP transport 预留稳定对象；
- AnalyticsService、SQL Gateway、SQL MCP Server 都围绕这些对象工作，
  这样后续替换 transport 时不需要改业务层接口。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SQLReadQueryRequest:
    """只读 SQL 查询请求契约。"""

    data_source: str
    sql: str
    timeout_ms: int
    row_limit: int
    trace_id: str | None = None
    run_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class SQLReadQueryResponse:
    """只读 SQL 查询响应契约。"""

    data_source: str
    db_type: str
    rows: list[dict]
    columns: list[str]
    row_count: int
    latency_ms: int
    checked_sql: str
    trace_id: str | None = None
    run_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class SQLHealthcheckRequest:
    """SQL MCP 健康检查请求。

    当前阶段健康检查非常克制，只关注：
    - 目标数据源是谁；
    - 这次检查属于哪个 trace / run；
    - 是否要走相同 transport。

    这样做的好处是：
    1. 可以复用和执行 SQL 相同的数据源路由规则；
    2. 未来切到远端 SQL MCP server 时，调用方不需要重新定义 healthcheck 参数结构；
    3. 调试时也能把 trace_id / run_id 串到基础设施日志里。
    """

    data_source: str | None = None
    trace_id: str | None = None
    run_id: str | None = None


@dataclass(slots=True)
class SQLHealthcheckResponse:
    """SQL MCP 健康检查响应。"""

    healthy: bool
    data_source: str
    db_type: str
    latency_ms: int
    trace_id: str | None = None
    run_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class SQLMCPError:
    """SQL MCP 风格统一错误结构。

    当前阶段虽然还没有把 SQL MCP 独立部署成真正远端服务，
    但错误结构先统一下来有两个价值：
    1. Gateway / Server / API 可以围绕同一错误形状记录日志和返回错误；
    2. 后续如果接入远端 transport，不需要重新改一套异常序列化协议。
    """

    error_code: str
    message: str
    detail: dict = field(default_factory=dict)


class SQLGatewayExecutionError(RuntimeError):
    """SQL Gateway 执行异常。"""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "sql_gateway_execution_error",
        detail: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.detail = detail or {}
