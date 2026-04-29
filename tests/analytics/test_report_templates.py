"""ReportTemplateEngine 测试。"""

from __future__ import annotations

from core.analytics.report_templates import ReportTemplateEngine


def test_weekly_report_template_can_generate_structured_blocks() -> None:
    """weekly_report 模板应能生成最小结构化报告块。"""

    engine = ReportTemplateEngine()

    blocks = engine.build(
        export_template="weekly_report",
        summary="本周新疆区域发电量总体上升。",
        insight_cards=[
            {"title": "趋势洞察", "type": "trend", "summary": "整体趋势向上", "evidence": {"points": 2}},
            {"title": "排名洞察", "type": "ranking", "summary": "哈密电站表现较好", "evidence": {"top_n": 3}},
        ],
        report_blocks=[],
        chart_spec={"chart_type": "line", "title": "发电量趋势"},
        tables=[{"name": "main_result", "columns": ["month", "total_value"], "rows": [["2024-04", 1200.0]]}],
        governance_note={"masked_fields": []},
    )

    block_types = [block["block_type"] for block in blocks]
    assert "overview" in block_types
    assert "trend" in block_types
    assert "ranking" in block_types
    assert "governance_note" in block_types


def test_monthly_report_template_can_generate_structured_blocks() -> None:
    """monthly_report 模板应能生成最小结构化报告块。"""

    engine = ReportTemplateEngine()

    blocks = engine.build(
        export_template="monthly_report",
        summary="本月收入总体稳定。",
        insight_cards=[],
        report_blocks=[],
        chart_spec=None,
        tables=[],
        governance_note={"effective_filters": {"department_code": "analytics-center"}},
    )

    block_types = [block["block_type"] for block in blocks]
    assert "overview" in block_types
    assert "key_findings" in block_types
    assert "risk_note" in block_types
    assert "recommendation" in block_types
