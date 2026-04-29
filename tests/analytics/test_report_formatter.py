"""ReportFormatter 测试。"""

from __future__ import annotations

from core.analytics.report_formatter import ReportFormatter


def test_report_formatter_generates_minimal_report_blocks() -> None:
    """报告格式化器应生成最小结构化报告块。"""

    formatter = ReportFormatter()

    blocks = formatter.build(
        summary="上个月新疆区域发电量总体上升。",
        insight_cards=[
            {
                "title": "发电量趋势洞察",
                "type": "trend",
                "summary": "发电量呈上升趋势。",
                "evidence": {"points": 2},
            }
        ],
        tables=[
            {
                "name": "main_result",
                "columns": ["month", "total_value"],
                "rows": [["2024-03", 1200.0], ["2024-04", 1400.0]],
            }
        ],
        chart_spec={
            "chart_type": "line",
            "title": "发电量按月趋势",
            "x_field": "month",
            "y_field": "total_value",
            "series_field": None,
            "dataset_ref": "main_result",
            "data_mapping": {"primary_series": "total_value"},
        },
    )

    block_types = [block["block_type"] for block in blocks]
    assert "overview" in block_types
    assert "key_findings" in block_types
    assert "data_table" in block_types
    assert "chart" in block_types
    assert "recommendation" in block_types
