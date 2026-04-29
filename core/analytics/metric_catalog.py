"""经营分析 Metric Catalog。

Metric Catalog 的作用不是把指标名字硬编码到业务逻辑里，
而是把“业务指标”与“物理存储字段”解耦：
- 用户说“发电量”；
- 系统知道它映射到哪个 `metric_code`；
- SQL Builder 再根据这个映射去构造受控 SQL。

这样做的价值：
1. 支持指标别名 / 同义词；
2. 支持未来一个指标映射到不同数据源、不同事实表；
3. 让 Planner 与 Builder 都围绕统一指标定义工作，避免逻辑分散。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class MetricDefinition:
    """业务指标定义。"""

    name: str
    metric_code: str
    description: str
    aliases: list[str] = field(default_factory=list)
    data_source: str = "local_analytics"
    table_name: str = "analytics_metrics_daily"
    aggregation: str = "SUM"
    # required_permissions 用于声明“想查这个指标至少需要哪些权限”。
    # 这里和 data_source 权限是两层不同治理：
    # 1. metric 权限约束“能不能查这个业务口径”；
    # 2. data_source 权限约束“能不能访问这个底层库/数仓”。
    # 经营分析不能把所有指标默认视为等价，因为收入、成本、利润等指标通常更敏感。
    required_permissions: list[str] = field(default_factory=lambda: ["analytics:query"])
    # allowed_roles 用于预留角色级治理。
    # 当前阶段不做完整权限中心，但先让结构具备角色约束能力。
    allowed_roles: list[str] = field(default_factory=list)
    # allowed_departments 用于预留部门级治理。
    # 某些指标未来可能只允许经营管理部、财务部等特定部门访问。
    allowed_departments: list[str] = field(default_factory=list)
    # sensitivity_level 用于标记指标敏感等级，便于前端展示、审计和后续 Human Review 扩展。
    sensitivity_level: str = "normal"


class MetricCatalog:
    """经营分析指标目录。"""

    def __init__(
        self,
        *,
        default_data_source: str = "local_analytics",
        default_table_name: str = "analytics_metrics_daily",
    ) -> None:
        self.default_data_source = default_data_source
        self.default_table_name = default_table_name
        self._metrics = self._build_default_metrics()
        self._alias_index = self._build_alias_index()

    def _build_default_metrics(self) -> dict[str, MetricDefinition]:
        """构造当前阶段默认指标定义。"""

        return {
            "发电量": MetricDefinition(
                name="发电量",
                metric_code="generation",
                description="新能源电站发电量指标",
                aliases=["发电", "发电总量", "发电情况", "发电表现"],
                data_source=self.default_data_source,
                table_name=self.default_table_name,
                required_permissions=["analytics:query", "analytics:metric:generation"],
                allowed_roles=["employee", "manager", "analyst", "admin"],
                sensitivity_level="internal",
            ),
            "收入": MetricDefinition(
                name="收入",
                metric_code="revenue",
                description="经营收入指标",
                aliases=["营收", "营业收入", "收入情况", "收入表现"],
                data_source=self.default_data_source,
                table_name=self.default_table_name,
                required_permissions=["analytics:query", "analytics:metric:revenue"],
                allowed_roles=["manager", "analyst", "finance", "admin"],
                allowed_departments=["analytics-center", "finance-center"],
                sensitivity_level="restricted",
            ),
            "成本": MetricDefinition(
                name="成本",
                metric_code="cost",
                description="经营成本指标",
                aliases=["成本情况", "支出成本", "成本表现"],
                data_source=self.default_data_source,
                table_name=self.default_table_name,
                required_permissions=["analytics:query", "analytics:metric:cost"],
                allowed_roles=["manager", "analyst", "finance", "admin"],
                allowed_departments=["analytics-center", "finance-center"],
                sensitivity_level="restricted",
            ),
            "利润": MetricDefinition(
                name="利润",
                metric_code="profit",
                description="利润指标",
                aliases=["利润情况", "盈利", "利润表现"],
                data_source=self.default_data_source,
                table_name=self.default_table_name,
                required_permissions=["analytics:query", "analytics:metric:profit"],
                allowed_roles=["manager", "analyst", "finance", "admin"],
                allowed_departments=["analytics-center", "finance-center"],
                sensitivity_level="restricted",
            ),
            "产量": MetricDefinition(
                name="产量",
                metric_code="output",
                description="产量指标",
                aliases=["生产量", "产出量", "产量情况"],
                data_source=self.default_data_source,
                table_name=self.default_table_name,
                required_permissions=["analytics:query", "analytics:metric:output"],
                allowed_roles=["employee", "manager", "analyst", "admin"],
                sensitivity_level="internal",
            ),
        }

    def _build_alias_index(self) -> dict[str, MetricDefinition]:
        """构建指标别名索引。"""

        alias_index: dict[str, MetricDefinition] = {}
        for definition in self._metrics.values():
            alias_index[definition.name] = definition
            for alias in definition.aliases:
                alias_index[alias] = definition
        return alias_index

    def resolve_metric(self, raw_metric_text: str | None) -> MetricDefinition | None:
        """根据原始指标文本解析标准指标定义。"""

        if not raw_metric_text:
            return None
        normalized_text = raw_metric_text.strip()
        if not normalized_text:
            return None
        return self._alias_index.get(normalized_text)

    def find_metric_in_query(self, query: str) -> MetricDefinition | None:
        """在整句问题中查找指标定义。"""

        for alias, definition in self._alias_index.items():
            if alias in query:
                return definition
        return None

    def list_metric_names(self) -> list[str]:
        """返回当前可用指标名。"""

        return list(self._metrics.keys())
