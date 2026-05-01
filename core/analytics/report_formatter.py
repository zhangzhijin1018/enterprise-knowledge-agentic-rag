"""
经营分析报告块格式化器（结构化交付层）。

=================================================================
模块定位
=================================================================
本模块的目标不是直接导出 PDF / Word，而是先把经营分析结果收敛成
一组"可交付的结构化报告块"（report_blocks），供前端渲染或多格式导出消费。

这样做的意义：
1. 前端可以先按 block 渲染报告式页面（如概览区/图表区/洞察区/建议区）
2. 后续导出 PDF / Word / PPT 时，可以直接消费这些结构块，不必重新解析原始数据
3. Service 层不需要把 overview / chart / recommendation 的拼装逻辑散在一起
    ——这里统一收口，保证报告结构的一致性

=================================================================
报告块类型（block_type）说明
=================================================================
- overview         → 分析概览：一段总结性文本，放在报告最前面
- key_findings     → 关键发现：从 insight_cards 中提取的洞察列表
- trend            → 趋势分析：type="trend" 的洞察卡片
- ranking          → 排名分析：type="ranking" 的洞察卡片
- data_table       → 数据表：tables 中的每张结果表
- chart            → 图表：chart_spec 图表描述
- governance_note  → 治理说明：权限/脱敏/过滤等治理信息
- risk_note        → 风险提示：当前结果的风险声明（固定文本）
- recommendation   → 后续建议：引导用户下一步可以做什么（固定文本）

=================================================================
报告块生成顺序（即前端渲染顺序）
=================================================================
1. overview         → 分析概览（顶部）
2. key_findings     → 关键发现
3. trend            → 趋势分析（如果洞察中包含 trend 类型）
4. ranking          → 排名分析（如果洞察中包含 ranking 类型）
5. data_table (×N)  → 数据表（每张结果表一个 block）
6. chart            → 图表
7. governance_note  → 治理说明
8. risk_note        → 风险提示（固定）
9. recommendation   → 后续建议（固定）
"""

from __future__ import annotations


class ReportFormatter:
    """
    最小经营分析报告格式化器。

    职责：将分析结果（summary / insight_cards / tables / chart_spec / governance_note）
    组织为一组标准化的报告块列表。

    为什么 report_blocks 是 list 而不是 dict：
    列表保证顺序——前端按数组索引渲染，第一项在最上面。
    """

    # 标准报告块类型白名单
    # 用于最终过滤，确保不会输出未定义的 block_type 给前端
    STANDARD_BLOCK_TYPES = {
        "overview",         # 分析概览
        "key_findings",     # 关键发现
        "trend",            # 趋势分析
        "ranking",          # 排名分析
        "data_table",       # 数据表
        "chart",            # 图表
        "risk_note",        # 风险提示
        "recommendation",   # 后续建议
        "governance_note",  # 治理说明
    }

    def build(
        self,
        *,
        summary: str,
        insight_cards: list[dict],
        tables: list[dict],
        chart_spec: dict | None,
        governance_note: dict | None = None,
    ) -> list[dict]:
        """
        构造 report_blocks。

        参数：
        - summary：分析摘要文本（来自 _build_summary）
        - insight_cards：洞察卡片列表（来自 InsightBuilder.build()）
        - tables：结果表列表（脱敏后，格式 [{"name": "main_result", "columns": [...], "rows": [[...]]}]）
        - chart_spec：图表描述（来自 _build_chart_spec），可为 None
        - governance_note：治理说明（含权限/脱敏/过滤信息），可为 None

        返回：
        report_blocks 列表，按前端渲染顺序排列。
        """

        report_blocks = []

        # Block 1：分析概览（始终有，因为有 summary）
        report_blocks.append(
            {
                "block_type": "overview",
                "title": "分析概览",
                "content": summary,
            }
        )

        # Block 2：关键发现（有洞察卡片时才生成）
        if insight_cards:
            report_blocks.append(
                {
                    "block_type": "key_findings",
                    "title": "关键发现",
                    "content": insight_cards,
                }
            )

            # Block 3：趋势分析（从洞察卡片中筛出 trend 类型的卡片）
            # 单独成块，便于前端给趋势分析一个独立展示区
            trend_cards = [card for card in insight_cards if card.get("type") == "trend"]
            if trend_cards:
                report_blocks.append(
                    {
                        "block_type": "trend",
                        "title": "趋势分析",
                        "content": trend_cards,
                    }
                )

            # Block 4：排名分析（从洞察卡片中筛出 ranking 类型的卡片）
            # 单独成块，便于前端给排名分析一个独立展示区
            ranking_cards = [card for card in insight_cards if card.get("type") == "ranking"]
            if ranking_cards:
                report_blocks.append(
                    {
                        "block_type": "ranking",
                        "title": "排名分析",
                        "content": ranking_cards,
                    }
                )

        # Block 5-5+N：数据表（每张结果表一个 data_table block）
        for table in tables:
            report_blocks.append(
                {
                    "block_type": "data_table",
                    "title": table.get("name", "数据表"),
                    "content": table,  # 包含 columns 和 rows
                }
            )

        # Block 6+N：图表（有 chart_spec 时才生成）
        if chart_spec is not None:
            report_blocks.append(
                {
                    "block_type": "chart",
                    "title": chart_spec.get("title", "图表"),
                    "content": chart_spec,  # 包含 chart_type / x_field / y_field / data_mapping
                }
            )

        # Block 7+N：治理说明（有 governance_note 时才生成）
        if governance_note is not None:
            report_blocks.append(
                {
                    "block_type": "governance_note",
                    "title": "治理说明",
                    "content": governance_note,
                }
            )

        # Block 末尾-1：风险提示（固定块，始终生成）
        # 提醒用户当前结果是基于受控模板 SQL 生成的，正式结论需结合业务口径复核
        report_blocks.append(
            {
                "block_type": "risk_note",
                "title": "风险提示",
                "content": "当前结果基于受控模板 SQL 与只读数据源生成，正式经营结论仍建议结合业务口径复核。",
            }
        )

        # Block 末尾：后续建议（固定块，始终生成）
        # 引导用户下一步可以做什么：继续追问趋势/排名/同比/环比或下钻
        report_blocks.append(
            {
                "block_type": "recommendation",
                "title": "后续建议",
                "content": "如需更深入分析，可继续追问趋势、排名、同比环比或下钻到区域/电站维度。",
            }
        )

        # 最终过滤：只保留标准 block_type 白名单中的块
        # 这是防御性编程——防止新加的 block_type 还没定义就输出给前端
        return [block for block in report_blocks if block["block_type"] in self.STANDARD_BLOCK_TYPES]
