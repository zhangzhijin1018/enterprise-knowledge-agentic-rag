"""经营分析数据源注册中心。

为什么要从“纯代码注册”升级到“注册中心”：
1. 经营分析进入收官阶段后，数据源不再只会有一个本地样例库；
2. 企业环境里经常需要逐步接入多个只读库、数仓或中间层视图；
3. 单纯把 data source 全部硬编码在 SchemaRegistry 里，会导致启停、权限和连接信息难以演进。

为什么仍然保留默认内置回退：
1. 本地开发和测试不应该强依赖数据库配置；
2. 当数据库里还没有数据源注册记录时，系统仍然要能用默认样例源跑通；
3. 这样可以兼顾“生产级可配置”与“研发联调易用性”。
"""

from __future__ import annotations

from dataclasses import replace

from core.analytics.schema_registry import DataSourceDefinition, SchemaRegistry
from core.common.cache import RegistryCache, get_global_cache
from core.repositories.data_source_repository import DataSourceRepository


class DataSourceRegistry:
    """经营分析数据源注册中心。"""

    def __init__(
        self,
        *,
        schema_registry: SchemaRegistry,
        data_source_repository: DataSourceRepository | None = None,
        registry_cache: RegistryCache | None = None,
    ) -> None:
        self.schema_registry = schema_registry
        self.data_source_repository = data_source_repository
        self.registry_cache = registry_cache or get_global_cache()

    def get_default_data_source(self) -> DataSourceDefinition:
        """获取默认数据源定义。

        规则：
        - 如果 repository 中存在启用中的默认数据源覆盖，则优先用覆盖后的定义；
        - 否则继续回退到 SchemaRegistry 的内置默认定义。
        """

        default_source = self.schema_registry.get_default_data_source()
        return self.get_data_source(default_source.key)

    def get_data_source(self, key: str | None = None) -> DataSourceDefinition:
        """读取指定数据源定义，并优先应用注册中心覆盖。"""

        base_definition = self.schema_registry.get_data_source(key)
        override_signature = "no_repository"
        if self.data_source_repository is not None:
            override = self.data_source_repository.get_data_source(base_definition.key)
            if override is not None:
                override_signature = f"{override.get('key')}:{override.get('updated_at')}"

        cache_key = f"analytics:data_source:{base_definition.key}:{override_signature}"

        def _compute() -> DataSourceDefinition:
            override = None
            if self.data_source_repository is not None:
                override = self.data_source_repository.get_data_source(base_definition.key)

            if override is None:
                return base_definition
            if not override.get("enabled", True):
                return base_definition

            return replace(
                base_definition,
                description=override.get("description") or base_definition.description,
                db_type=override.get("db_type") or base_definition.db_type,
                connection_uri=override.get("connection_uri") or base_definition.connection_uri,
                required_permissions=list(override.get("required_permissions") or base_definition.required_permissions),
                allowed_roles=list(override.get("allowed_roles") or base_definition.allowed_roles),
            )

        return self.registry_cache.get_or_compute(
            cache_key,
            _compute,
        )

    def list_data_sources(self, *, only_enabled: bool = True) -> list[dict]:
        """列出当前可见数据源。

        返回结构采用扁平 dict，是因为：
        - 前端配置页/系统管理页通常更适合直接消费扁平对象；
        - 同时也便于测试验证“repository 覆盖是否生效”。
        """

        overrides = []
        if self.data_source_repository is not None:
            overrides = self.data_source_repository.list_data_sources(only_enabled=False)

        override_signature = tuple(
            sorted(f"{item['key']}:{item.get('updated_at')}:{item.get('enabled', True)}" for item in overrides)
        )
        cache_key = f"analytics:data_source:list:{only_enabled}:{override_signature}"

        def _compute() -> list[dict]:
            base_sources = {
                key: definition
                for key, definition in self.schema_registry._data_sources.items()  # noqa: SLF001
            }
            override_map = {item["key"]: item for item in overrides}

            merged_rows: list[dict] = []
            for key, _base_definition in base_sources.items():
                override = override_map.get(key)
                resolved = self.get_data_source(key)
                enabled = override.get("enabled", True) if override is not None else True
                merged_rows.append(
                    {
                        "key": resolved.key,
                        "description": resolved.description,
                        "db_type": resolved.db_type,
                        "connection_uri": resolved.connection_uri,
                        "required_permissions": list(resolved.required_permissions),
                        "allowed_roles": list(resolved.allowed_roles),
                        "enabled": enabled,
                        "source": "repository_override" if override is not None else "builtin_default",
                    }
                )

            for key, override in override_map.items():
                if key in base_sources:
                    continue
                if only_enabled and not override.get("enabled", True):
                    continue
                merged_rows.append(
                    {
                        "key": override["key"],
                        "description": override["description"],
                        "db_type": override["db_type"],
                        "connection_uri": override.get("connection_uri"),
                        "required_permissions": list(override.get("required_permissions") or []),
                        "allowed_roles": list(override.get("allowed_roles") or []),
                        "enabled": override.get("enabled", True),
                        "source": "repository_only",
                    }
                )

            if only_enabled:
                merged_rows = [row for row in merged_rows if row["enabled"]]
            return merged_rows

        return self.registry_cache.get_or_compute(cache_key, _compute)
