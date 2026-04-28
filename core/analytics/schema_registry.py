"""经营分析 Schema Registry。

为什么经营分析不能只靠自由 SQL：
1. 企业经营库通常表多、字段多、口径多，直接自由拼 SQL 很容易查错表、用错字段；
2. 同一个“发电量”在不同数据源、不同表里可能有不同口径，必须先经过统一定义；
3. 未来即使引入 LLM 辅助 SQL，也应该先让模型在受控 schema 范围内工作，
   而不是让它凭空猜数据库结构。

Schema Registry 的作用：
- 统一定义当前可用数据源；
- 统一定义表、字段、时间列；
- 统一定义 group_by 维度到物理列/表达式的映射；
- 为 SQL Builder、SQL Gateway、后续 SQL MCP 适配提供稳定边界。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class GroupByRule:
    """分组维度规则。"""

    key: str
    description: str
    select_expression: str
    group_expression: str
    alias: str
    order_by_expression: str


@dataclass(slots=True)
class TableDefinition:
    """表定义。

    当前阶段先保留经营分析最小所需信息：
    - 表名
    - 时间列
    - 指标编码列
    - 指标名称列
    - 指标值列
    - 维度列映射
    - group_by 规则
    """

    name: str
    description: str
    time_column: str
    metric_code_column: str
    metric_name_column: str
    metric_value_column: str
    dimension_columns: dict[str, str] = field(default_factory=dict)
    group_by_rules: dict[str, GroupByRule] = field(default_factory=dict)


@dataclass(slots=True)
class DataSourceDefinition:
    """数据源定义。"""

    key: str
    description: str
    db_type: str
    default_table: str
    tables: dict[str, TableDefinition] = field(default_factory=dict)


class SchemaRegistry:
    """经营分析 Schema Registry。"""

    def __init__(self) -> None:
        self._data_sources = self._build_default_data_sources()

    def _build_default_data_sources(self) -> dict[str, DataSourceDefinition]:
        """构造当前阶段默认数据源定义。"""

        analytics_table = TableDefinition(
            name="analytics_metrics_daily",
            description="经营指标日粒度事实表",
            time_column="biz_date",
            metric_code_column="metric_code",
            metric_name_column="metric_name",
            metric_value_column="metric_value",
            dimension_columns={
                "region": "region_name",
                "station": "station_name",
            },
            group_by_rules={
                "month": GroupByRule(
                    key="month",
                    description="按月汇总",
                    select_expression="substr(biz_date, 1, 7)",
                    group_expression="substr(biz_date, 1, 7)",
                    alias="month",
                    order_by_expression="month ASC",
                ),
                "region": GroupByRule(
                    key="region",
                    description="按区域汇总",
                    select_expression="region_name",
                    group_expression="region_name",
                    alias="region",
                    order_by_expression="total_value DESC",
                ),
                "station": GroupByRule(
                    key="station",
                    description="按站点汇总",
                    select_expression="station_name",
                    group_expression="station_name",
                    alias="station",
                    order_by_expression="total_value DESC",
                ),
            },
        )

        return {
            "local_analytics": DataSourceDefinition(
                key="local_analytics",
                description="本地开发用经营分析样例数据源，后续可替换为真实 SQL MCP / PostgreSQL 只读库",
                db_type="sqlite",
                default_table=analytics_table.name,
                tables={
                    analytics_table.name: analytics_table,
                },
            )
        }

    def get_default_data_source(self) -> DataSourceDefinition:
        """获取默认数据源。"""

        return self._data_sources["local_analytics"]

    def get_data_source(self, data_source: str | None = None) -> DataSourceDefinition:
        """获取指定数据源定义。"""

        resolved_key = data_source or self.get_default_data_source().key
        return self._data_sources[resolved_key]

    def get_table_definition(
        self,
        *,
        table_name: str | None = None,
        data_source: str | None = None,
    ) -> TableDefinition:
        """获取表定义。"""

        source = self.get_data_source(data_source)
        resolved_table_name = table_name or source.default_table
        return source.tables[resolved_table_name]

    def get_group_by_rule(
        self,
        group_by: str,
        *,
        table_name: str | None = None,
        data_source: str | None = None,
    ) -> GroupByRule | None:
        """获取分组维度规则。"""

        table = self.get_table_definition(table_name=table_name, data_source=data_source)
        return table.group_by_rules.get(group_by)
