"""
经营分析洞察构造器（规则驱动，轻量且可解释）。

=================================================================
为什么需要洞察卡片
=================================================================
1. 表格只表达"查到了什么"，但不表达"最值得关注的点是什么"
2. 真实业务用户往往先看结论和异常，再决定是否下钻明细
3. insight_cards 是系统从"能查数"走向"会辅助分析"的关键一步

=================================================================
设计策略：规则优先，LLM 润色可选
=================================================================
当前阶段采用规则/模板生成洞察卡片，原因：
- 保证稳定、可测、可解释（确定性输出，不受 LLM 幻觉影响）
- 不依赖大模型也能输出最小分析结果
- 后续可在此基础上叠加 LLM 润色或更复杂的统计规则

=================================================================
洞察类型（type）说明
=================================================================
- trend：趋势洞察   → 时间序列数据（按月分组），描述变化趋势
- ranking：排名洞察 → 按维度分组（电站/区域），指出排名第一的维度
- comparison：对比洞察 → 有 compare_target（同比/环比）时，对比两期数据
- anomaly：异常提醒   → 结果中存在 <= 0 的值，或结果为空

=================================================================
生成规则详解
=================================================================
1. 如果 rows 为空 → 返回 anomaly 卡（"查询结果为空"）
2. 如果有 compare_target（mom/yoy）→ 返回 comparison 卡（当前值 vs 对比值）
3. 如果 group_by=month → 返回 trend 卡（时间序列趋势洞察）
4. 如果 group_by=region/station → 返回 ranking 卡（排名第一的维度）
5. 如果只有一行且无对比/排名/趋势 → 返回 comparison/trend 卡（核心结果）
6. 额外检查：如果存在 <= 0 的值 → 追加 anomaly 卡（异常值提醒）

=================================================================
后续升级方向
=================================================================
- 统计规则增强：同比异常检测（超过均值 ± 2σ 的值标记为异常）
- LLM 润色：在规则结论的基础上，用 LLM 生成更自然的描述文本
- 多指标洞察：当支持多指标查询时，分析指标间的相关性
"""

from __future__ import annotations


class InsightBuilder:
    """
    经营分析最小洞察构造器。

    职责：根据查询结果的结构化信息（rows / slots / row_count），
    生成一组可直接在前端展示的洞察卡片。

    输入：
    - slots：规划结果中的槽位信息（metric、group_by、compare_target）
    - rows：脱敏后的查询结果行数据
    - row_count：查询结果总行数
    """

    def build(self, *, slots: dict, rows: list[dict], row_count: int) -> list[dict]:
        """
        根据当前结果生成 insight_cards。

        返回结构：
        [
            {
                "title": "洞察卡片标题（前端用作卡片 header）",
                "type": "趋势/排名/对比/异常提醒",
                "summary": "洞察摘要（前端用作卡片 body）",
                "evidence": { ... }  // 支撑洞察的证据数据
            },
            ...
        ]

        设计说明：
        - 每次调用可能返回多张卡片（如一张 ranking + 一张 anomaly）
        - 卡片顺序有意义：最重要的洞察排在最前面
        """

        metric = slots.get("metric", "指标")
        compare_target = slots.get("compare_target")
        group_by = slots.get("group_by")

        # 边界条件 1：结果为空
        # 不给用户显示空白页，而是明确告知"当前条件下无数据"
        if not rows:
            return [
                {
                    "title": "查询结果为空",
                    "type": "anomaly",
                    "summary": "当前筛选条件下未查询到任何经营数据。",
                    "evidence": {
                        "metric": metric,
                        "row_count": row_count,
                    },
                }
            ]

        insights: list[dict] = []
        first_row = rows[0]

        # 规则 2：检查是否有对比（同比/环比）
        # 如果 SQL 查询了 current_value 和 compare_value，生成对比洞察
        if compare_target in {"mom", "yoy"}:
            current_value = first_row.get("current_value", 0) or 0
            compare_value = first_row.get("compare_value", 0) or 0
            delta = current_value - compare_value
            insights.append(
                {
                    "title": f"{metric}{'环比' if compare_target == 'mom' else '同比'}对比",
                    "type": "comparison",
                    "summary": (
                        f"当前值为 {current_value}，对比值为 {compare_value}，"
                        f"差值为 {delta}。"
                    ),
                    "evidence": {
                        "current_value": current_value,
                        "compare_value": compare_value,
                        "delta": delta,
                        "compare_target": compare_target,
                    },
                }
            )

        # 规则 3/4：检查分组维度
        # 按月分组 → 时间序列趋势
        if group_by == "month":
            # 提取趋势数据点供前端渲染折线图
            trend_points = [
                {
                    "x": row.get("month"),  # X 轴：月份标签
                    "y": row.get("current_value", row.get("total_value")),  # Y 轴：指标值
                }
                for row in rows
            ]
            insights.append(
                {
                    "title": f"{metric}趋势洞察",
                    "type": "trend",
                    "summary": f"当前结果已形成 {len(trend_points)} 个时间点，可用于趋势判断。",
                    "evidence": {
                        "points": trend_points,
                    },
                }
            )
        elif group_by in {"region", "station"}:
            # 按区域/电站分组 → 排名洞察（取第一行作为排名第一）
            key_name = group_by  # 维度名称：region 或 station
            top_row = first_row
            top_value = top_row.get("current_value", top_row.get("total_value"))
            insights.append(
                {
                    "title": f"{metric}{group_by}排名洞察",
                    "type": "ranking",
                    "summary": f"当前排名第一的是 {top_row.get(key_name)}，数值为 {top_value}。",
                    "evidence": {
                        "dimension": top_row.get(key_name),
                        "value": top_value,
                        "row_count": row_count,
                    },
                }
            )

        # 规则 5：兜底——只有一行且无明显维度/对比时，生成核心结果卡
        if len(rows) == 1 and not insights:
            total_value = first_row.get("current_value", first_row.get("total_value"))
            insights.append(
                {
                    "title": f"{metric}核心结果",
                    "type": "comparison" if compare_target else "trend",
                    "summary": f"当前核心指标结果为 {total_value}。",
                    "evidence": {
                        "value": total_value,
                        "metric": metric,
                    },
                }
            )

        # 规则 6：异常检测——搜索负值或零值
        # 当前阶段用简单规则：只要存在 <= 0 的值就提醒
        # 后续升级方向：
        # - 历史分布法：计算过去 N 期的均值和标准差，标记超过 2σ 的值
        # - 同比异常法：与去年同期对比，变化超过阈值标记异常
        # - 阈值法：按指标设置绝对阈值（如发电量 < 1000 MWh 标为异常）
        anomaly_rows = [
            row
            for row in rows
            if (row.get("current_value", row.get("total_value")) or 0) <= 0
        ]
        if anomaly_rows:
            insights.append(
                {
                    "title": "异常值提醒",
                    "type": "anomaly",
                    "summary": "结果集中存在小于等于 0 的值，建议进一步核查口径或源数据。",
                    "evidence": {
                        "anomaly_count": len(anomaly_rows),
                    },
                }
            )

        return insights
