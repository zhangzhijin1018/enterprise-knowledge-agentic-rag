"""SQL MCP-compatible contracts。

注意：
- 当前实现还不是完整标准 MCP server；
- 这里定义的是“面向未来 SQL MCP server 的 client contract”；
- 当前内部 transport 仍然是本地 SQLite 样例数据；
- 但 AnalyticsService 已经围绕这些 request / response 对象工作，
  后续切真实 MCP transport 时不需要改 Service 层签名。
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


class SQLGatewayExecutionError(RuntimeError):
    """SQL Gateway 执行异常。"""

    def __init__(self, message: str, *, detail: dict | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}
