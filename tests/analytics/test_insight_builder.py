"""InsightBuilder 测试。"""

from __future__ import annotations

from core.analytics.insight_builder import InsightBuilder


def test_insight_builder_generates_trend_and_comparison_cards() -> None:
    """趋势 + 对比场景应能生成最小洞察卡片。"""

    builder = InsightBuilder()

    cards = builder.build(
        slots={
            "metric": "发电量",
            "group_by": "month",
            "compare_target": "mom",
        },
        rows=[
            {"month": "2024-03", "current_value": 1200.0, "compare_value": 1100.0},
            {"month": "2024-04", "current_value": 1400.0, "compare_value": 1200.0},
        ],
        row_count=2,
    )

    assert any(card["type"] == "trend" for card in cards)
    assert any(card["type"] == "comparison" for card in cards)


def test_insight_builder_generates_ranking_card() -> None:
    """排名场景应返回 ranking 洞察。"""

    builder = InsightBuilder()

    cards = builder.build(
        slots={"metric": "收入", "group_by": "station"},
        rows=[
            {"station": "哈密电站", "total_value": 320.0},
            {"station": "吐鲁番电站", "total_value": 305.0},
        ],
        row_count=2,
    )

    assert any(card["type"] == "ranking" for card in cards)
