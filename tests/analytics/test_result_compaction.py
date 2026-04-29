"""经营分析结果轻量化测试。"""

from __future__ import annotations

from core.analytics.analytics_result_model import AnalyticsResult


def test_analytics_result_lightweight_snapshot_excludes_heavy_content() -> None:
    """轻快照不应继续塞入 tables / insight / report / chart 等重内容。"""

    result = AnalyticsResult(
        run_id="run_test",
        trace_id="trace_test",
        summary="测试摘要",
        sql_preview="SELECT 1",
        row_count=3,
        latency_ms=15,
        data_source="local_analytics",
        metric_scope="发电量",
        compare_target="yoy",
        group_by="month",
        slots={"metric": "发电量"},
        rows=[{"month": "2024-03", "total_value": 10}],
        masked_rows=[{"month": "2024-03", "total_value": 10}],
        columns=["month", "total_value"],
        masked_columns=["month", "total_value"],
        chart_spec={"chart_type": "line"},
        insight_cards=[{"title": "洞察"}],
        report_blocks=[{"block_type": "overview"}],
        timing_breakdown={"sql_execute_ms": 12.5},
    )

    lightweight_snapshot = result.to_lightweight_snapshot()
    heavy_result = result.to_heavy_result()

    assert lightweight_snapshot["summary"] == "测试摘要"
    assert lightweight_snapshot["has_heavy_result"] is True
    assert "chart_spec" not in lightweight_snapshot
    assert "insight_cards" not in lightweight_snapshot
    assert "report_blocks" not in lightweight_snapshot
    assert "tables" not in lightweight_snapshot
    assert lightweight_snapshot["timing_breakdown"]["sql_execute_ms"] == 12.5

    assert heavy_result["chart_spec"]["chart_type"] == "line"
    assert heavy_result["insight_cards"]
    assert heavy_result["report_blocks"]
    assert heavy_result["tables"]
