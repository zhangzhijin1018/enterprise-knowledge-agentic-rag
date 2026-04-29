"""经营分析报告模板。

当前阶段不做复杂自然语言写作引擎，
而是先把 weekly_report / monthly_report 两类常见经营分析交付模板固化为结构化 block。

这样做的价值：
1. 周报/月报可以稳定复用同一套结构；
2. 导出链路可以更像正式分析产物，而不是简单把 JSON 原样吐出去；
3. 后续如果要做 Word / PDF / PPT 正式排版，输入结构已经稳定。
"""

from __future__ import annotations


class ReportTemplateEngine:
    """经营分析报告模板引擎。"""

    SUPPORTED_TEMPLATES = {"weekly_report", "monthly_report"}

    def build(
        self,
        *,
        export_template: str,
        summary: str,
        insight_cards: list[dict],
        report_blocks: list[dict],
        chart_spec: dict | None,
        tables: list[dict],
        governance_note: dict | None = None,
    ) -> list[dict]:
        """按模板生成更接近交付物的报告块。"""

        normalized_template = export_template.strip().lower()
        if normalized_template not in self.SUPPORTED_TEMPLATES:
            return report_blocks

        trend_cards = [card for card in insight_cards if card.get("type") == "trend"]
        ranking_cards = [card for card in insight_cards if card.get("type") == "ranking"]
        other_cards = [card for card in insight_cards if card.get("type") not in {"trend", "ranking"}]

        title_prefix = "周报" if normalized_template == "weekly_report" else "月报"
        templated_blocks: list[dict] = [
            {
                "block_type": "overview",
                "title": f"{title_prefix}概览",
                "content": summary,
            },
            {
                "block_type": "key_findings",
                "title": f"{title_prefix}关键发现",
                "content": other_cards or insight_cards,
            },
        ]

        if trend_cards or chart_spec is not None:
            templated_blocks.append(
                {
                    "block_type": "trend",
                    "title": f"{title_prefix}趋势分析",
                    "content": {
                        "insight_cards": trend_cards,
                        "chart_spec": chart_spec,
                    },
                }
            )

        if ranking_cards:
            templated_blocks.append(
                {
                    "block_type": "ranking",
                    "title": f"{title_prefix}排名分析",
                    "content": ranking_cards,
                }
            )

        for table in tables:
            templated_blocks.append(
                {
                    "block_type": "data_table",
                    "title": table.get("name", "数据表"),
                    "content": table,
                }
            )

        templated_blocks.append(
            {
                "block_type": "risk_note",
                "title": "风险提示",
                "content": "当前分析结果基于受控模板 SQL、治理校验与只读数据源生成，正式对外使用前建议复核业务口径。",
            }
        )
        templated_blocks.append(
            {
                "block_type": "recommendation",
                "title": "后续建议",
                "content": "建议结合同比、环比、区域/电站下钻与治理说明，进一步形成正式经营结论。",
            }
        )
        if governance_note is not None:
            templated_blocks.append(
                {
                    "block_type": "governance_note",
                    "title": "治理说明",
                    "content": governance_note,
                }
            )
        return templated_blocks
