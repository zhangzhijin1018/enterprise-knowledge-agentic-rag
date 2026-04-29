"""Report MCP Server 测试。"""

from __future__ import annotations

from pathlib import Path

from core.config.settings import Settings
from core.tools.mcp import ReportMCPServer, ReportRenderRequest


def test_report_mcp_server_renders_markdown_artifact(tmp_path: Path) -> None:
    """Report MCP Server 应能基于标准 contract 生成最小 markdown 导出产物。"""

    server = ReportMCPServer(settings=Settings(local_export_dir=str(tmp_path)))

    response = server.render_report(
        ReportRenderRequest(
            export_id="exp_report_server_test",
            run_id="run_report_server_test",
            export_type="markdown",
            summary="上个月新疆区域发电量总体上升。",
            insight_cards=[
                {
                    "title": "发电量趋势洞察",
                    "type": "trend",
                    "summary": "整体趋势向上。",
                    "evidence": {"points": 2},
                }
            ],
            report_blocks=[
                {"block_type": "overview", "title": "分析概览", "content": "总体向好"},
                {"block_type": "governance_note", "title": "治理说明", "content": {"masked_fields": []}},
            ],
            chart_spec={
                "chart_type": "line",
                "title": "发电量趋势",
                "x_field": "month",
                "y_field": "total_value",
                "series_field": None,
                "dataset_ref": "main_result",
                "data_mapping": {"primary_series": "total_value"},
            },
            tables=[
                {
                    "name": "main_result",
                    "columns": ["month", "total_value"],
                    "rows": [["2024-03", 1000.0], ["2024-04", 1200.0]],
                }
            ],
        )
    )

    assert response.export_id == "exp_report_server_test"
    assert response.filename.endswith(".md")
    assert response.metadata["server_mode"] == "inprocess_report_mcp_server"
    assert Path(response.artifact_path).exists()
    assert "经营分析报告" in Path(response.artifact_path).read_text(encoding="utf-8")


def test_report_mcp_server_supports_docx_placeholder_export(tmp_path: Path) -> None:
    """docx 导出当前阶段允许先走占位产物，但文件扩展名和状态应稳定。"""

    server = ReportMCPServer(settings=Settings(local_export_dir=str(tmp_path)))

    response = server.render_report(
        ReportRenderRequest(
            export_id="exp_docx_placeholder",
            run_id="run_docx_placeholder",
            export_type="docx",
            summary="测试 docx 占位导出。",
            insight_cards=[],
            report_blocks=[],
            chart_spec=None,
            tables=[],
        )
    )

    assert response.filename.endswith(".docx")
    assert response.metadata["placeholder_mode"] is True
    assert Path(response.artifact_path).exists()
