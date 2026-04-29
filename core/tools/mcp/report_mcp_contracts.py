"""Report MCP-compatible contracts。

注意：
- 当前实现还不是最终远端 Report MCP 服务；
- 这里先把导出链路的 request / response contract 定稳；
- 这样 AnalyticsExportService、ReportGateway、ReportMCPServer 都围绕同一契约工作；
- 后续如果把导出切到远端服务或独立 worker，不需要再改业务层接口。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ReportRenderRequest:
    """报告导出请求契约。"""

    export_id: str
    run_id: str
    export_type: str
    summary: str | None
    insight_cards: list[dict]
    report_blocks: list[dict]
    chart_spec: dict | None
    tables: list[dict]
    trace_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class ReportRenderResponse:
    """报告导出响应契约。"""

    export_id: str
    run_id: str
    export_type: str
    filename: str
    artifact_path: str
    file_uri: str
    content_preview: str | None
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class ReportHealthcheckResponse:
    """Report MCP 健康检查响应。"""

    healthy: bool
    server_mode: str
    metadata: dict = field(default_factory=dict)


class ReportGatewayExecutionError(RuntimeError):
    """Report Gateway 执行异常。"""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "report_gateway_execution_error",
        detail: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.detail = detail or {}
