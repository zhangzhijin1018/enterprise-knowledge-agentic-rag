"""数据源注册 Repository。

当前阶段该 Repository 的职责非常克制：
1. 保存经营分析数据源注册配置；
2. 支持数据库优先、内存回退；
3. 为 DataSourceRegistry 提供“可配置覆盖默认数据源”的稳定读取边界。

注意：
- 这里不负责 SQL 执行；
- 不负责 schema 解析；
- 不负责权限决策；
- 只做数据源配置对象的最小持久化访问。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from core.database.models import DataSourceConfig

_DATA_SOURCE_CONFIGS: dict[str, dict] = {}


def _utcnow() -> datetime:
    """返回当前 UTC 时间。"""

    return datetime.now(timezone.utc)


def reset_in_memory_data_source_store() -> None:
    """重置内存版数据源注册表。"""

    _DATA_SOURCE_CONFIGS.clear()


class DataSourceRepository:
    """数据源注册数据访问层。"""

    def __init__(self, session: Session | None = None) -> None:
        self.session = session

    def _use_database(self) -> bool:
        """判断当前是否走数据库模式。"""

        return self.session is not None

    def _serialize_data_source(self, config: DataSourceConfig) -> dict:
        """把 ORM 数据源配置对象转换成统一字典结构。"""

        return {
            "key": config.key,
            "description": config.description,
            "db_type": config.db_type,
            "connection_uri": config.connection_uri,
            "required_permissions": list(config.required_permissions or []),
            "allowed_roles": list(config.allowed_roles or []),
            "enabled": config.enabled,
            "metadata": config.metadata_json or {},
            "created_at": config.created_at,
            "updated_at": config.updated_at,
        }

    def upsert_data_source(
        self,
        *,
        key: str,
        description: str,
        db_type: str,
        connection_uri: str | None,
        required_permissions: list[str] | None = None,
        allowed_roles: list[str] | None = None,
        enabled: bool = True,
        metadata: dict | None = None,
    ) -> dict:
        """创建或更新数据源配置。"""

        if self._use_database():
            statement = select(DataSourceConfig).where(DataSourceConfig.key == key)
            config = self.session.execute(statement).scalar_one_or_none()
            if config is None:
                config = DataSourceConfig(
                    key=key,
                    description=description,
                    db_type=db_type,
                    connection_uri=connection_uri,
                    required_permissions=required_permissions or [],
                    allowed_roles=allowed_roles or [],
                    enabled=enabled,
                    metadata_json=metadata or {},
                )
                self.session.add(config)
            else:
                config.description = description
                config.db_type = db_type
                config.connection_uri = connection_uri
                config.required_permissions = required_permissions or []
                config.allowed_roles = allowed_roles or []
                config.enabled = enabled
                config.metadata_json = metadata or {}
            self.session.flush()
            self.session.refresh(config)
            return self._serialize_data_source(config)

        now = _utcnow()
        record = {
            "key": key,
            "description": description,
            "db_type": db_type,
            "connection_uri": connection_uri,
            "required_permissions": list(required_permissions or []),
            "allowed_roles": list(allowed_roles or []),
            "enabled": enabled,
            "metadata": metadata or {},
            "created_at": _DATA_SOURCE_CONFIGS.get(key, {}).get("created_at", now),
            "updated_at": now,
        }
        _DATA_SOURCE_CONFIGS[key] = record
        return record

    def get_data_source(self, key: str) -> dict | None:
        """读取单个数据源配置。"""

        if self._use_database():
            statement = select(DataSourceConfig).where(DataSourceConfig.key == key)
            config = self.session.execute(statement).scalar_one_or_none()
            if config is None:
                return None
            return self._serialize_data_source(config)

        return _DATA_SOURCE_CONFIGS.get(key)

    def list_data_sources(self, *, only_enabled: bool = False) -> list[dict]:
        """列出数据源配置。"""

        if self._use_database():
            statement = select(DataSourceConfig).order_by(desc(DataSourceConfig.updated_at))
            rows = [self._serialize_data_source(item) for item in self.session.execute(statement).scalars()]
            if only_enabled:
                return [item for item in rows if item["enabled"]]
            return rows

        rows = sorted(_DATA_SOURCE_CONFIGS.values(), key=lambda item: item["updated_at"], reverse=True)
        if only_enabled:
            return [item for item in rows if item["enabled"]]
        return rows
