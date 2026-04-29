"""DataSourceRegistry 测试。"""

from __future__ import annotations

from core.analytics.data_source_registry import DataSourceRegistry
from core.analytics.schema_registry import SchemaRegistry
from core.config.settings import Settings
from core.repositories.data_source_repository import DataSourceRepository, reset_in_memory_data_source_store


def test_data_source_registry_returns_builtin_default_source() -> None:
    """未配置 repository 覆盖时，应返回内置默认数据源。"""

    reset_in_memory_data_source_store()
    registry = DataSourceRegistry(
        schema_registry=SchemaRegistry(settings=Settings()),
        data_source_repository=DataSourceRepository(session=None),
    )

    data_source = registry.get_default_data_source()

    assert data_source.key == "local_analytics"
    assert data_source.db_type == "sqlite"
    reset_in_memory_data_source_store()


def test_data_source_registry_can_be_overridden_by_repository() -> None:
    """配置化数据源应能覆盖默认内置数据源定义。"""

    reset_in_memory_data_source_store()
    repository = DataSourceRepository(session=None)
    repository.upsert_data_source(
        key="local_analytics",
        description="被覆盖的本地样例数据源",
        db_type="postgresql",
        connection_uri="postgresql://readonly@localhost:5432/analytics",
        required_permissions=["analytics:query", "analytics:query:enterprise"],
        allowed_roles=["analyst"],
        enabled=True,
        metadata={"managed_by": "test"},
    )
    registry = DataSourceRegistry(
        schema_registry=SchemaRegistry(settings=Settings()),
        data_source_repository=repository,
    )

    data_source = registry.get_data_source("local_analytics")

    assert data_source.db_type == "postgresql"
    assert data_source.connection_uri == "postgresql://readonly@localhost:5432/analytics"
    assert "analytics:query:enterprise" in data_source.required_permissions
    reset_in_memory_data_source_store()
