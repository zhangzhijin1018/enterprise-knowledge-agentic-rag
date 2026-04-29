"""经营分析报告块格式化器。

本模块的目标不是现在就导出 PDF / Word，
而是先把经营分析结果收敛成一组“可交付的结构化报告块”。

这样做的意义：
1. 前端可以先按 block 渲染报告式页面；
2. 后续导出 PDF / Word / PPT 时，可以直接消费这些结构块；
3. Service 层不需要把 overview / chart / recommendation 的拼装逻辑散在一起。
"""

from __future__ import annotations


class ReportFormatter:
    """最小经营分析报告格式化器。"""

    def build(
        self,
        *,
        summary: str,
        insight_cards: list[dict],
        tables: list[dict],
        chart_spec: dict | None,
    ) -> list[dict]:
        """构造最小 report_blocks。"""

        report_blocks = [
            {
                "block_type": "overview",
                "title": "分析概览",
                "content": summary,
            }
        ]

        if insight_cards:
            report_blocks.append(
                {
                    "block_type": "key_findings",
                    "title": "关键发现",
                    "content": insight_cards,
                }
            )

        for table in tables:
            report_blocks.append(
                {
                    "block_type": "data_table",
                    "title": table.get("name", "数据表"),
                    "content": table,
                }
            )

        if chart_spec is not None:
            report_blocks.append(
                {
                    "block_type": "chart",
                    "title": chart_spec.get("title", "图表"),
                    "content": chart_spec,
                }
            )

        report_blocks.append(
            {
                "block_type": "risk_note",
                "title": "风险提示",
                "content": "当前结果基于受控模板 SQL 与只读数据源生成，正式经营结论仍建议结合业务口径复核。",
            }
        )
        report_blocks.append(
            {
                "block_type": "recommendation",
                "title": "后续建议",
                "content": "如需更深入分析，可继续追问趋势、排名、同比环比或下钻到区域/电站维度。",
            }
        )
        return report_blocks
