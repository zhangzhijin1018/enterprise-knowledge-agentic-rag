"""经营分析指标解析器（MetricResolver）。

核心职责：
1. 接收 LLM 解析后的 metric_code
2. 根据 metric_code 映射到对应的数据源、表、字段等元数据
3. 不做语义理解，只做确定性查表

设计原则：
- 纯本地代码实现，不调用 LLM
- 指标元数据与 LLM prompt 分离
- 新增指标只需修改 METRIC_METADATA 配置
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(slots=True)
class MetricMetadata:
    """指标元数据。

    描述某个指标对应的物理存储信息。
    """

    # 指标代码（LLM 输出的唯一标识）
    metric_code: str

    # 指标中文名称
    metric_name: str

    # 关联的数据源 key（对应 DataSourceDefinition.key）
    data_source_key: str

    # 物理表名
    table_name: str

    # 指标值字段名
    metric_value_column: str

    # 指标代码字段名（用于 WHERE 条件）
    metric_code_column: str | None = None

    # 时间列字段名
    time_column: str = "biz_date"

    # 维度列映射（逻辑名 → 物理列名）
    dimension_columns: dict[str, str] = field(default_factory=dict)

    # 业务域（用于权限过滤）
    business_domain: str | None = None

    # 额外过滤条件（如产品类型过滤）
    extra_filters: dict[str, str] = field(default_factory=dict)

    # 指标描述
    description: str = ""

    # 是否支持同比
    support_yoy: bool = True

    # 是否支持环比
    support_mom: bool = True


# =============================================================================
# 指标元数据注册表
# =============================================================================

# 注意：这里的 metric_code 必须与 LLM prompt 中的指标列表保持一致！
METRIC_METADATA: dict[str, MetricMetadata] = {

    # -------------------------------------------------------------------------
    # 新能源相关指标
    # -------------------------------------------------------------------------
    "generation": MetricMetadata(
        metric_code="generation",
        metric_name="发电量",
        data_source_key="enterprise_readonly",
        table_name="analytics_metrics_daily",
        metric_value_column="metric_value",
        metric_code_column="metric_code",
        dimension_columns={
            "region": "region_name",
            "station": "station_name",
        },
        business_domain="new_energy",
        description="光伏/风电场的总发电量（单位：万kWh）",
    ),

    "online": MetricMetadata(
        metric_code="online",
        metric_name="上网电量",
        data_source_key="enterprise_readonly",
        table_name="analytics_metrics_daily",
        metric_value_column="metric_value",
        metric_code_column="metric_code",
        dimension_columns={
            "region": "region_name",
            "station": "station_name",
        },
        business_domain="new_energy",
        description="销售给电网的电量（单位：万kWh）",
    ),

    "sales": MetricMetadata(
        metric_code="sales",
        metric_name="售电量",
        data_source_key="enterprise_readonly",
        table_name="analytics_metrics_daily",
        metric_value_column="metric_value",
        metric_code_column="metric_code",
        dimension_columns={
            "region": "region_name",
            "station": "station_name",
        },
        business_domain="new_energy",
        description="对外销售的电量（单位：万kWh）",
    ),

    # -------------------------------------------------------------------------
    # 化工贸易相关指标
    # -------------------------------------------------------------------------
    "chemical_sales_volume": MetricMetadata(
        metric_code="chemical_sales_volume",
        metric_name="化工产品销售量",
        data_source_key="enterprise_trade",
        table_name="chemical_product_sales_daily",
        metric_value_column="sales_volume",
        metric_code_column="product_type",
        dimension_columns={
            "region": "region_name",
            "product": "product_type",
        },
        business_domain="chemical",
        extra_filters={
            "product_type": "聚乙烯",
        },
        description="聚乙烯等化工产品的销售量（单位：吨）",
    ),

    "chemical_sales_revenue": MetricMetadata(
        metric_code="chemical_sales_revenue",
        metric_name="化工产品销售收入",
        data_source_key="enterprise_trade",
        table_name="chemical_product_sales_daily",
        metric_value_column="sales_revenue",
        metric_code_column="product_type",
        dimension_columns={
            "region": "region_name",
            "product": "product_type",
        },
        business_domain="chemical",
        extra_filters={
            "product_type": "聚乙烯",
        },
        description="聚乙烯等化工产品的销售收入（单位：万元）",
    ),

    # -------------------------------------------------------------------------
    # 财务相关指标
    # -------------------------------------------------------------------------
    "revenue": MetricMetadata(
        metric_code="revenue",
        metric_name="收入",
        data_source_key="enterprise_readonly",
        table_name="analytics_metrics_daily",
        metric_value_column="metric_value",
        metric_code_column="metric_code",
        dimension_columns={
            "region": "region_name",
        },
        business_domain="finance",
        description="营业收入（单位：万元）",
    ),

    "cost": MetricMetadata(
        metric_code="cost",
        metric_name="成本",
        data_source_key="enterprise_readonly",
        table_name="analytics_metrics_daily",
        metric_value_column="metric_value",
        metric_code_column="metric_code",
        dimension_columns={
            "region": "region_name",
        },
        business_domain="finance",
        description="营业成本（单位：万元）",
    ),

    "profit": MetricMetadata(
        metric_code="profit",
        metric_name="利润",
        data_source_key="enterprise_readonly",
        table_name="analytics_metrics_daily",
        metric_value_column="metric_value",
        metric_code_column="metric_code",
        dimension_columns={
            "region": "region_name",
        },
        business_domain="finance",
        description="营业利润（单位：万元）",
    ),
}


class MetricResolver:
    """指标解析器。

    根据 LLM 输出的 metric_code，解析出对应的数据源和表信息。

    使用示例：
        resolver = MetricResolver()
        metadata = resolver.resolve("generation")

        # 获取 SQL 所需信息
        print(metadata.data_source_key)  # enterprise_readonly
        print(metadata.table_name)        # analytics_metrics_daily
        print(metadata.metric_value_column)  # metric_value
    """

    def __init__(self, custom_metadata: dict[str, MetricMetadata] | None = None) -> None:
        """初始化解析器。

        Args:
            custom_metadata: 自定义指标元数据（用于扩展或覆盖默认配置）
        """
        self._metadata = dict(METRIC_METADATA)
        if custom_metadata:
            self._metadata.update(custom_metadata)

    def resolve(self, metric_code: str) -> MetricMetadata:
        """根据指标代码获取元数据。

        Args:
            metric_code: 指标代码（如 "generation", "chemical_sales_volume"）

        Returns:
            指标元数据

        Raises:
            ValueError: 当指标代码不存在时
        """
        if metric_code not in self._metadata:
            raise ValueError(
                f"未知的指标代码: {metric_code}。"
                f"可选的指标代码: {', '.join(sorted(self._metadata.keys()))}"
            )
        return self._metadata[metric_code]

    def resolve_or_none(self, metric_code: str | None) -> MetricMetadata | None:
        """根据指标代码获取元数据（安全版本）。

        Args:
            metric_code: 指标代码

        Returns:
            指标元数据，如果 metric_code 为 None 则返回 None
        """
        if metric_code is None:
            return None
        try:
            return self.resolve(metric_code)
        except ValueError:
            return None

    def resolve_multiple(self, metric_codes: list[str]) -> list[MetricMetadata]:
        """根据多个指标代码获取元数据列表。

        Args:
            metric_codes: 指标代码列表

        Returns:
            指标元数据列表（只包含成功解析的指标）
        """
        results = []
        for code in metric_codes:
            metadata = self.resolve_or_none(code)
            if metadata is not None:
                results.append(metadata)
        return results

    def list_metrics(self) -> list[MetricMetadata]:
        """列出所有可用指标。

        Returns:
            所有指标的元数据列表
        """
        return list(self._metadata.values())

    def list_metrics_by_domain(self, business_domain: str) -> list[MetricMetadata]:
        """根据业务域列出指标。

        Args:
            business_domain: 业务域代码

        Returns:
            属于指定业务域的指标列表
        """
        return [
            m for m in self._metadata.values()
            if m.business_domain == business_domain
        ]

    def get_data_sources_for_metrics(self, metric_codes: list[str]) -> set[str]:
        """获取指标列表涉及的所有数据源。

        Args:
            metric_codes: 指标代码列表

        Returns:
            数据源 key 集合
        """
        data_sources = set()
        for code in metric_codes:
            metadata = self.resolve_or_none(code)
            if metadata is not None:
                data_sources.add(metadata.data_source_key)
        return data_sources

    def build_metric_catalog_for_llm(self) -> str:
        """构建供 LLM 使用的指标目录摘要。

        这个摘要只包含指标名称和代码，不包含数据源等内部信息。
        这样可以保持 LLM prompt 的简洁性。

        Returns:
            格式化的指标目录字符串
        """
        lines = ["## 可用指标目录\n"]

        # 按业务域分组
        domains: dict[str, list[MetricMetadata]] = {}
        for metadata in self._metadata.values():
            domain = metadata.business_domain or "other"
            if domain not in domains:
                domains[domain] = []
            domains[domain].append(metadata)

        domain_names = {
            "new_energy": "新能源",
            "chemical": "化工贸易",
            "finance": "财务",
            "other": "其他",
        }

        for domain, metrics in sorted(domains.items()):
            domain_display = domain_names.get(domain, domain)
            lines.append(f"\n### {domain_display}\n")
            for m in sorted(metrics, key=lambda x: x.metric_code):
                lines.append(f"- {m.metric_name}（代码：{m.metric_code}）")

        return "".join(lines)


# =============================================================================
# 全局单例
# =============================================================================

_global_resolver: MetricResolver | None = None


def get_global_metric_resolver() -> MetricResolver:
    """获取全局指标解析器单例。"""
    global _global_resolver
    if _global_resolver is None:
        _global_resolver = MetricResolver()
    return _global_resolver
