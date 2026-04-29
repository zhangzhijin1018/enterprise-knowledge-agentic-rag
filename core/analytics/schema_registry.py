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

from core.config.settings import Settings, get_settings


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
    - 表级白名单
    - 字段级白名单预留
    - 部门范围过滤预留
    - 敏感字段遮罩预留
    """

    name: str
    description: str
    time_column: str
    metric_code_column: str
    metric_name_column: str
    metric_value_column: str
    dimension_columns: dict[str, str] = field(default_factory=dict)
    group_by_rules: dict[str, GroupByRule] = field(default_factory=dict)
    allowed_permissions: list[str] = field(default_factory=list)
    field_whitelist: list[str] = field(default_factory=list)
    # visible_fields 表示结果层允许直接返回给前端的字段集合。
    # 它不是数据库层字段白名单的替代，而是“结果可见性治理”的补充边界。
    visible_fields: list[str] = field(default_factory=list)
    sensitive_fields: list[str] = field(default_factory=list)
    # masked_fields 表示即使字段可见，也需要在缺少敏感可见权限时进行脱敏的字段。
    masked_fields: list[str] = field(default_factory=list)
    department_filter_column: str | None = None


@dataclass(slots=True)
class DataSourceDefinition:
    """数据源定义。"""

    key: str
    description: str
    db_type: str
    default_table: str
    connection_uri: str | None = None
    required_permissions: list[str] = field(default_factory=list)
    allowed_roles: list[str] = field(default_factory=list)
    supports_mcp_server: bool = True
    tables: dict[str, TableDefinition] = field(default_factory=dict)


class SchemaRegistry:
    """经营分析 Schema Registry。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
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
            allowed_permissions=["analytics:query"],
            field_whitelist=[
                "biz_date",
                "metric_code",
                "metric_name",
                "region_name",
                "station_name",
                "department_code",
                "metric_value",
            ],
            visible_fields=[
                "metric_name",
                "month",
                "region",
                "station",
                "total_value",
                "current_value",
                "compare_value",
            ],
            # 这里把站点视为当前阶段最小敏感字段样例：
            # - 对普通经营查询来说，站点级结果可能涉及更细颗粒度经营表现；
            # - 因此即使允许返回，也要为后续脱敏策略预留明确边界。
            sensitive_fields=["station"],
            masked_fields=["station"],
            department_filter_column="department_code",
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
        data_sources = {
            "local_analytics": DataSourceDefinition(
                key="local_analytics",
                description="本地开发用经营分析样例数据源，后续可替换为真实 SQL MCP / PostgreSQL 只读库",
                db_type="sqlite",
                connection_uri=None,
                default_table=analytics_table.name,
                required_permissions=["analytics:query"],
                supports_mcp_server=True,
                tables={
                    analytics_table.name: analytics_table,
                },
            ),
        }

        # 当前阶段开始支持“真实只读数据源配置化接入”。
        # 这里不直接假设一定是 PostgreSQL，也不把连接信息硬编码在代码里，
        # 而是只要环境变量提供了连接串，就把它注册成一个正式 data source。
        #
        # 这样做的好处：
        # 1. 本地没有真实库时，仍然可以用 local_analytics 跑 demo；
        # 2. 测试环境或企业内网提供只读库后，只改配置即可；
        # 3. SQL Builder / Guard / Gateway / AnalyticsService 都围绕同一个 registry 工作，
        #    不会再出现“某层知道真实库、某层还以为只有 demo 库”的错位。
        if self.settings.analytics_real_data_source_url:
            real_data_source_key = self.settings.analytics_real_data_source_key
            db_type = self._infer_db_type_from_uri(self.settings.analytics_real_data_source_url)
            data_sources[real_data_source_key] = DataSourceDefinition(
                key=real_data_source_key,
                description="通过环境变量注册的真实只读经营分析数据源",
                db_type=db_type,
                connection_uri=self.settings.analytics_real_data_source_url,
                default_table=analytics_table.name,
                required_permissions=[
                    permission
                    for permission in [
                        "analytics:query",
                        self.settings.analytics_real_data_source_required_permission,
                    ]
                    if permission
                ],
                supports_mcp_server=True,
                tables={
                    analytics_table.name: analytics_table,
                },
            )
        return data_sources

    def get_default_data_source(self) -> DataSourceDefinition:
        """获取默认数据源。

        规则：
        - 如果已经配置了真实只读数据源，则优先把它作为默认数据源；
        - 否则回退到本地样例数据源。

        这样经营分析在企业环境里可以自然优先使用真实库，
        同时本地开发和测试依然不受影响。
        """

        if self.settings.analytics_real_data_source_url:
            return self._data_sources[self.settings.analytics_real_data_source_key]
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

    def get_allowed_tables(self, *, data_source: str | None = None) -> list[str]:
        """获取某个数据源允许访问的表白名单。"""

        source = self.get_data_source(data_source)
        return list(source.tables.keys())

    def get_table_field_whitelist(
        self,
        *,
        table_name: str | None = None,
        data_source: str | None = None,
    ) -> list[str]:
        """获取表字段白名单。

        当前阶段先把字段白名单能力放到 registry 中，
        SQL Guard 可以按需启用；
        这样后续接真实业务库时，可以逐步从“表级白名单”升级到“字段级治理”。
        """

        table = self.get_table_definition(table_name=table_name, data_source=data_source)
        return list(table.field_whitelist)

    def get_table_visible_fields(
        self,
        *,
        table_name: str | None = None,
        data_source: str | None = None,
    ) -> list[str]:
        """获取结果层可见字段集合。"""

        table = self.get_table_definition(table_name=table_name, data_source=data_source)
        return list(table.visible_fields)

    def get_table_sensitive_fields(
        self,
        *,
        table_name: str | None = None,
        data_source: str | None = None,
    ) -> list[str]:
        """获取结果层敏感字段集合。"""

        table = self.get_table_definition(table_name=table_name, data_source=data_source)
        return list(table.sensitive_fields)

    def get_table_masked_fields(
        self,
        *,
        table_name: str | None = None,
        data_source: str | None = None,
    ) -> list[str]:
        """获取缺少敏感字段权限时需要脱敏的字段集合。"""

        table = self.get_table_definition(table_name=table_name, data_source=data_source)
        return list(table.masked_fields)

    def _infer_db_type_from_uri(self, uri: str) -> str:
        """根据连接串粗略推断数据库类型。"""

        normalized_uri = uri.lower()
        if normalized_uri.startswith("postgresql"):
            return "postgresql"
        if normalized_uri.startswith("mysql"):
            return "mysql"
        if normalized_uri.startswith("sqlite"):
            return "sqlite"
        return "unknown"
