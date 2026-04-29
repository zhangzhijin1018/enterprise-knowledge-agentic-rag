"""经营分析洞察构造器。

为什么经营分析不能只返回数据表：
1. 表格只表达“查到了什么”，但不表达“最值得关注的点是什么”；
2. 真实业务用户往往先看结论和异常，再决定是否下钻明细；
3. insight_cards 是系统从“能查数”走向“会辅助分析”的关键一步。

当前阶段这里先采用规则/模板生成：
- 保证稳定、可测、可解释；
- 不依赖大模型也能输出最小分析结果；
- 后续可在此基础上叠加 LLM 润色或更复杂统计规则。
"""

from __future__ import annotations


class InsightBuilder:
    """经营分析最小洞察构造器。"""

    def build(self, *, slots: dict, rows: list[dict], row_count: int) -> list[dict]:
        """根据当前结果生成最小 insight_cards。"""

        metric = slots.get("metric", "指标")
        compare_target = slots.get("compare_target")
        group_by = slots.get("group_by")
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

        if group_by == "month":
            trend_points = [
                {
                    "x": row.get("month"),
                    "y": row.get("current_value", row.get("total_value")),
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
            key_name = group_by
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

        # 当前阶段的最小异常识别先用简单规则：
        # - 只要存在负值或 0 值，就返回 anomaly 提示；
        # - 后续可升级为历史分布、阈值、同比异常等更强规则。
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
