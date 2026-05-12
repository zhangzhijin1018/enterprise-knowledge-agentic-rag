"""Milvus 版本管理器。

版本管理核心概念：
1. 文档版本：每次更新创建一个新版本
2. 版本激活：只有激活的版本才参与检索
3. 版本回滚：可以回滚到历史版本
4. 版本历史：保留所有版本的变更记录

版本状态：
- creating: 创建中
- active: 已激活（当前生效）
- superseded: 已废弃（被新版本取代）
- deleted: 已删除
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DocumentVersionStatus(str, Enum):
    """文档版本状态。"""

    CREATING = "creating"  # 创建中
    ACTIVE = "active"  # 已激活（当前生效）
    SUPERSEDED = "superseded"  # 已废弃
    DELETED = "deleted"  # 已删除


@dataclass
class DocumentVersion:
    """文档版本。

    Attributes:
        version_id: 版本 ID
        document_id: 文档 ID
        version_number: 版本号
        status: 状态
        created_by: 创建人
        created_at: 创建时间
        activated_at: 激活时间
        changelog: 变更说明
        milvus_primary_keys: Milvus 主键列表
        chunk_count: chunk 数量
    """

    version_id: str
    document_id: str
    version_number: int
    status: DocumentVersionStatus = DocumentVersionStatus.CREATING
    created_by: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    activated_at: Optional[datetime] = None
    changelog: str = ""
    milvus_primary_keys: list[str] = field(default_factory=list)
    chunk_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "version_id": self.version_id,
            "document_id": self.document_id,
            "version_number": self.version_number,
            "status": self.status.value,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
            "changelog": self.changelog,
            "milvus_primary_keys": self.milvus_primary_keys,
            "chunk_count": self.chunk_count,
        }


class MilvusVersionManager:
    """Milvus 版本管理器。

    版本管理流程：
    1. 创建版本 → creating
    2. 更新 Milvus → 获取主键
    3. 激活版本 → active
    4. 新版本激活 → 旧版本变为 superseded

    版本切换示意图：
    v1 (active) → v2 (creating) → v2 (active), v1 (superseded)
    """

    def __init__(
        self,
        version_store,  # 版本存储（PostgreSQL/Redis）
        milvus_client,  # Milvus 客户端
    ):
        """初始化版本管理器。

        Args:
            version_store: 版本存储（实现版本持久化）
            milvus_client: Milvus 客户端
        """
        self.version_store = version_store
        self.milvus = milvus_client
        self._version_cache: dict[str, DocumentVersion] = {}

    def create_version(
        self,
        document_id: str,
        user_id: str,
        changelog: str = "",
    ) -> DocumentVersion:
        """创建新版本。

        Args:
            document_id: 文档 ID
            user_id: 创建人 ID
            changelog: 变更说明

        Returns:
            新版本对象
        """
        # 获取当前最新版本号
        current_version = self._get_latest_version(document_id)
        new_version_number = (current_version.version_number + 1) if current_version else 1

        # 生成版本 ID
        import uuid
        version_id = f"ver_{document_id}_{new_version_number}_{uuid.uuid4().hex[:8]}"

        # 创建版本对象
        version = DocumentVersion(
            version_id=version_id,
            document_id=document_id,
            version_number=new_version_number,
            status=DocumentVersionStatus.CREATING,
            created_by=user_id,
            created_at=datetime.now(),
            changelog=changelog,
        )

        # 持久化
        self.version_store.save(version)

        # 更新缓存
        self._version_cache[version_id] = version

        logger.info(
            f"创建版本: doc={document_id}, version={new_version_number}, "
            f"ver_id={version_id}"
        )

        return version

    def activate_version(
        self,
        version_id: str,
        milvus_primary_keys: list[str],
        chunk_count: int = 0,
    ) -> DocumentVersion:
        """激活版本。

        激活版本后：
        1. 该版本状态变为 active
        2. 该文档的其他版本状态变为 superseded

        Args:
            version_id: 版本 ID
            milvus_primary_keys: Milvus 主键列表
            chunk_count: chunk 数量

        Returns:
            激活后的版本对象
        """
        # 获取版本
        version = self._get_version(version_id)
        if not version:
            raise ValueError(f"版本不存在: {version_id}")

        # 更新版本信息
        version.milvus_primary_keys = milvus_primary_keys
        version.chunk_count = chunk_count
        version.status = DocumentVersionStatus.ACTIVE
        version.activated_at = datetime.now()

        # 持久化
        self.version_store.save(version)

        # 将同一文档的其他版本标记为 superseded
        all_versions = self.version_store.get_by_document_id(version.document_id)
        for v in all_versions:
            if v.version_id != version_id and v.status == DocumentVersionStatus.ACTIVE:
                v.status = DocumentVersionStatus.SUPERSEDED
                self.version_store.save(v)

        # 更新缓存
        self._version_cache[version_id] = version

        logger.info(
            f"激活版本: ver_id={version_id}, doc={version.document_id}, "
            f"chunks={chunk_count}"
        )

        return version

    def rollback_version(
        self,
        version_id: str,
    ) -> DocumentVersion:
        """回滚到指定版本。

        回滚实际上是：
        1. 获取历史版本的 Milvus 主键
        2. 创建新版本，关联到相同的 Milvus 数据
        3. 激活新版本

        Args:
            version_id: 要回滚到的版本 ID

        Returns:
            新版本（关联到历史 Milvus 数据）
        """
        # 获取要回滚的版本
        source_version = self._get_version(version_id)
        if not source_version:
            raise ValueError(f"要回滚的版本不存在: {version_id}")

        # 创建新版本
        new_version = self.create_version(
            document_id=source_version.document_id,
            user_id="system",  # 回滚操作
            changelog=f"回滚到版本 {source_version.version_number}",
        )

        # 激活新版本（使用历史版本的 Milvus 主键）
        self.activate_version(
            version_id=new_version.version_id,
            milvus_primary_keys=source_version.milvus_primary_keys,
            chunk_count=source_version.chunk_count,
        )

        logger.info(
            f"回滚完成: doc={source_version.document_id}, "
            f"from={source_version.version_id}, to={new_version.version_id}"
        )

        return new_version

    def get_active_version(self, document_id: str) -> Optional[DocumentVersion]:
        """获取文档的当前激活版本。

        Args:
            document_id: 文档 ID

        Returns:
            当前激活版本，如果没有则返回 None
        """
        return self._get_latest_version(document_id, status=DocumentVersionStatus.ACTIVE)

    def get_version_history(
        self,
        document_id: str,
        limit: int = 10,
    ) -> list[DocumentVersion]:
        """获取文档版本历史。

        Args:
            document_id: 文档 ID
            limit: 返回数量限制

        Returns:
            版本历史列表（按时间倒序）
        """
        all_versions = self.version_store.get_by_document_id(document_id)

        # 按版本号倒序排序
        sorted_versions = sorted(
            all_versions,
            key=lambda v: v.version_number,
            reverse=True,
        )

        return sorted_versions[:limit]

    def soft_delete_version(self, version_id: str) -> DocumentVersion:
        """软删除版本。

        Args:
            version_id: 版本 ID

        Returns:
            删除后的版本对象
        """
        version = self._get_version(version_id)
        if not version:
            raise ValueError(f"版本不存在: {version_id}")

        version.status = DocumentVersionStatus.DELETED
        self.version_store.save(version)

        logger.info(f"软删除版本: ver_id={version_id}")

        return version

    def get_version(self, version_id: str) -> Optional[DocumentVersion]:
        """获取指定版本。

        Args:
            version_id: 版本 ID

        Returns:
            版本对象
        """
        return self._get_version(version_id)

    def _get_version(self, version_id: str) -> Optional[DocumentVersion]:
        """从缓存或存储获取版本。

        Args:
            version_id: 版本 ID

        Returns:
            版本对象
        """
        # 先从缓存获取
        if version_id in self._version_cache:
            return self._version_cache[version_id]

        # 从存储获取
        version = self.version_store.get(version_id)
        if version:
            self._version_cache[version_id] = version

        return version

    def _get_latest_version(
        self,
        document_id: str,
        status: Optional[DocumentVersionStatus] = None,
    ) -> Optional[DocumentVersion]:
        """获取文档的最新版本。

        Args:
            document_id: 文档 ID
            status: 版本状态过滤

        Returns:
            最新版本
        """
        all_versions = self.version_store.get_by_document_id(document_id)

        if not all_versions:
            return None

        # 按版本号排序
        sorted_versions = sorted(
            all_versions,
            key=lambda v: v.version_number,
            reverse=True,
        )

        # 如果指定了状态，过滤
        if status:
            for v in sorted_versions:
                if v.status == status:
                    return v
            return None

        return sorted_versions[0]

    def clear_cache(self) -> None:
        """清空版本缓存。"""
        self._version_cache.clear()


class InMemoryVersionStore:
    """内存版本存储（测试用）。

    实际项目应使用 PostgreSQL 持久化。
    """

    def __init__(self):
        """初始化内存存储。"""
        self._versions: dict[str, DocumentVersion] = {}
        self._doc_versions: dict[str, list[str]] = {}

    def save(self, version: DocumentVersion) -> None:
        """保存版本。

        Args:
            version: 版本对象
        """
        self._versions[version.version_id] = version

        # 更新文档版本索引
        if version.document_id not in self._doc_versions:
            self._doc_versions[version.document_id] = []
        if version.version_id not in self._doc_versions[version.document_id]:
            self._doc_versions[version.document_id].append(version.version_id)

    def get(self, version_id: str) -> Optional[DocumentVersion]:
        """获取版本。

        Args:
            version_id: 版本 ID

        Returns:
            版本对象
        """
        return self._versions.get(version_id)

    def get_by_document_id(self, document_id: str) -> list[DocumentVersion]:
        """根据文档 ID 获取所有版本。

        Args:
            document_id: 文档 ID

        Returns:
            版本列表
        """
        version_ids = self._doc_versions.get(document_id, [])
        return [self._versions[v] for v in version_ids if v in self._versions]

    def delete(self, version_id: str) -> None:
        """删除版本。

        Args:
            version_id: 版本 ID
        """
        if version_id in self._versions:
            version = self._versions[version_id]
            del self._versions[version_id]

            # 从索引中移除
            doc_versions = self._doc_versions.get(version.document_id, [])
            if version_id in doc_versions:
                doc_versions.remove(version_id)
