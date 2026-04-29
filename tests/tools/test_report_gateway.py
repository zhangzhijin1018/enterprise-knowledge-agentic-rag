"""Report Gateway 测试。"""

from __future__ import annotations

from pathlib import Path

from core.config.settings import Settings
from core.tools.mcp import ReportRenderRequest
from core.tools.report.report_gateway import ReportGateway


def test_report_gateway_healthcheck_and_render(tmp_path: Path) -> None:
    """Report Gateway 应能通过 contract 调用最小导出链路。"""

    settings = Settings(
        local_export_dir=str(tmp_path),
        analytics_report_gateway_transport_mode="inprocess_report_mcp_server",
    )
    gateway = ReportGateway(settings=settings)

    health = gateway.healthcheck()
    response = gateway.render_report(
        ReportRenderRequest(
            export_id="exp_report_gateway_test",
            run_id="run_report_gateway_test",
            export_type="json",
            summary="收入总体稳定。",
            insight_cards=[],
            report_blocks=[{"block_type": "overview", "title": "分析概览", "content": "收入总体稳定"}],
            chart_spec=None,
            tables=[
                {
                    "name": "main_result",
                    "columns": ["metric_name", "total_value"],
                    "rows": [["收入", 5200.0]],
                }
            ],
        )
    )

    assert health["healthy"] is True
    assert response.export_type == "json"
    assert response.metadata["server_mode"] == "inprocess_report_mcp_server"
    assert Path(response.artifact_path).exists()
