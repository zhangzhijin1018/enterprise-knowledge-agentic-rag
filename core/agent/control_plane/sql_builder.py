"""规则式 SQL 构造器。

当前阶段刻意不做“自由 NL2SQL”，而是先做模板化 SQL：
1. 先由 Planner 把自然语言收敛成结构化槽位；
2. 再由 SQL Builder 根据槽位选择少量稳定模板；
3. 最后必须经过 SQL Guard 才能执行。

这样做的原因是：
- 经营分析结果会直接影响业务判断，错误 SQL 风险高；
- 模板式 SQL 更容易测试、审计和讲解；
- 后续接 LLM 辅助 SQL 生成时，也应该把“自由生成”限制在模板边界内。
"""

from __future__ import annotations


class SQLBuilder:
    """最小规则式 SQL 构造器。"""

    TABLE_NAME = "analytics_metrics_daily"
    METRIC_CODE_MAP = {
        "发电量": "generation",
        "收入": "revenue",
        "成本": "cost",
        "利润": "profit",
        "产量": "output",
    }

    def build(self, slots: dict) -> dict:
        """根据槽位构造最小 SQL 和解释信息。"""

        metric = slots["metric"]
        metric_code = self.METRIC_CODE_MAP.get(metric, metric)
        time_range = slots["time_range"]
        org_scope = slots.get("org_scope")
        group_by = slots.get("group_by")
        compare_target = slots.get("compare_target")

        where_clauses = [
            f"metric_code = '{metric_code}'",
            f"biz_date >= '{time_range['start_date']}'",
            f"biz_date <= '{time_range['end_date']}'",
        ]

        if org_scope:
            if org_scope["type"] == "region":
                where_clauses.append(f"region_name = '{org_scope['value']}'")
            elif org_scope["type"] == "station":
                where_clauses.append(f"station_name = '{org_scope['value']}'")

        select_fields = []
        group_by_fields = []
        order_by_clause = ""

        if group_by == "month":
            # SQLite 环境下使用 substr 兼容最小月度聚合；
            # 生产 PostgreSQL 后续可以替换成 date_trunc('month', biz_date)。
            select_fields.append("substr(biz_date, 1, 7) AS month")
            group_by_fields.append("substr(biz_date, 1, 7)")
            order_by_clause = " ORDER BY month ASC"
        elif group_by == "region":
            select_fields.append("region_name AS region")
            group_by_fields.append("region_name")
            order_by_clause = " ORDER BY total_value DESC"
        elif group_by == "station":
            select_fields.append("station_name AS station")
            group_by_fields.append("station_name")
            order_by_clause = " ORDER BY total_value DESC"

        select_fields.extend(
            [
                "metric_name",
                "SUM(metric_value) AS total_value",
            ]
        )

        sql = f"SELECT {', '.join(select_fields)} FROM {self.TABLE_NAME} WHERE {' AND '.join(where_clauses)}"
        if group_by_fields:
            sql += f" GROUP BY {', '.join(group_by_fields + ['metric_name'])}"
        else:
            # 不做 group by 时，返回一行汇总结果。
            sql += " GROUP BY metric_name"
        sql += order_by_clause

        return {
            "generated_sql": sql,
            "metric_scope": metric,
            "builder_metadata": {
                "group_by": group_by,
                "compare_target": compare_target,
                "time_range_label": time_range.get("label"),
                "org_scope": org_scope,
                "sql_template_version": "analytics_v1",
            },
        }
