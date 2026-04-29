"""Report Gateway。

当前阶段这里不直接在 Service 层操作本地文件系统，
而是像 SQL Gateway 一样，先把导出链路收口为 Report MCP-compatible client：
- Service 只负责组织导出 payload；
- Gateway 负责把导出请求发给 Report MCP server 风格执行层；
- 当前 transport 先用“进程内 server 调用”；
- 后续若切远端 Report MCP 服务，不需要改 AnalyticsExportService 的方法签名。
"""

from __future__ import annotations

from dataclasses import asdict

from core.config.settings import Settings, get_settings
from core.tools.mcp import (
    ReportGatewayExecutionError,
    ReportHealthcheckResponse,
    ReportMCPServer,
    ReportRenderRequest,
    ReportRenderResponse,
)


class ReportGateway:
    """Report MCP-compatible Gateway。"""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        server: ReportMCPServer | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.server = server or ReportMCPServer(settings=self.settings)

    def render_report(self, request: ReportRenderRequest) -> ReportRenderResponse:
        """通过统一 contract 调用最小导出链路。"""

        if self.settings.analytics_report_gateway_transport_mode != "inprocess_report_mcp_server":
            raise ReportGatewayExecutionError(
                "当前仅支持 inprocess_report_mcp_server transport",
                error_code="report_gateway_transport_unsupported",
                detail={"transport_mode": self.settings.analytics_report_gateway_transport_mode},
            )
        return self.server.render_report(request)

    def healthcheck(self) -> dict:
        """执行最小健康检查。"""

        response: ReportHealthcheckResponse = self.server.healthcheck()
        return asdict(response)
