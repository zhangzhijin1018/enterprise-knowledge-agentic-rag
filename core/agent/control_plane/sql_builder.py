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

from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry


class SQLBuilder:
    """Schema-aware 规则式 SQL 构造器。

    当前阶段仍坚持“规则模板优先”，但模板的元信息不再散落在类常量里，
    而是统一从 `SchemaRegistry` 和 `MetricCatalog` 读取。

    这样做的好处：
    - SQL Builder 知道自己能查哪些表、哪些字段；
    - 指标别名和口径映射不会分散在多个模块；
    - 后续接多数据源、SQL MCP、更多维度时，扩展成本更低。
    """

    def __init__(
        self,
        *,
        schema_registry: SchemaRegistry | None = None,
        metric_catalog: MetricCatalog | None = None,
    ) -> None:
        self.schema_registry = schema_registry or SchemaRegistry()
        self.metric_catalog = metric_catalog or MetricCatalog()

    def build(self, slots: dict) -> dict:
        """根据槽位构造最小 SQL 和解释信息。"""

        metric = slots["metric"]
        metric_definition = self.metric_catalog.resolve_metric(metric)
        if metric_definition is None:
            raise ValueError(f"未知指标定义：{metric}")

        data_source = metric_definition.data_source
        table_definition = self.schema_registry.get_table_definition(
            table_name=metric_definition.table_name,
            data_source=data_source,
        )
        time_range = slots["time_range"]
        org_scope = slots.get("org_scope")
        group_by = slots.get("group_by")
        compare_target = slots.get("compare_target")

        where_clauses = [
            f"{table_definition.metric_code_column} = '{metric_definition.metric_code}'",
            f"{table_definition.time_column} >= '{time_range['start_date']}'",
            f"{table_definition.time_column} <= '{time_range['end_date']}'",
        ]

        if org_scope:
            if org_scope["type"] == "region":
                where_clauses.append(
                    f"{table_definition.dimension_columns['region']} = '{org_scope['value']}'"
                )
            elif org_scope["type"] == "station":
                where_clauses.append(
                    f"{table_definition.dimension_columns['station']} = '{org_scope['value']}'"
                )

        select_fields = []
        group_by_fields = []
        order_by_clause = ""

        group_by_rule = None
        if group_by:
            group_by_rule = self.schema_registry.get_group_by_rule(
                group_by,
                table_name=table_definition.name,
                data_source=data_source,
            )
        if group_by_rule is not None:
            select_fields.append(f"{group_by_rule.select_expression} AS {group_by_rule.alias}")
            group_by_fields.append(group_by_rule.group_expression)
            order_by_clause = f" ORDER BY {group_by_rule.order_by_expression}"

        select_fields.extend(
            [
                table_definition.metric_name_column,
                f"{metric_definition.aggregation}({table_definition.metric_value_column}) AS total_value",
            ]
        )

        sql = (
            f"SELECT {', '.join(select_fields)} "
            f"FROM {table_definition.name} "
            f"WHERE {' AND '.join(where_clauses)}"
        )
        if group_by_fields:
            sql += f" GROUP BY {', '.join(group_by_fields + [table_definition.metric_name_column])}"
        else:
            # 不做 group by 时，返回一行汇总结果。
            sql += f" GROUP BY {table_definition.metric_name_column}"
        sql += order_by_clause

        return {
            "generated_sql": sql,
            "metric_scope": metric,
            "data_source": data_source,
            "builder_metadata": {
                "group_by": group_by,
                "compare_target": compare_target,
                "time_range_label": time_range.get("label"),
                "org_scope": org_scope,
                "table_name": table_definition.name,
                "db_type": self.schema_registry.get_data_source(data_source).db_type,
                "metric_code": metric_definition.metric_code,
                "sql_template_version": "analytics_v2",
            },
        }
