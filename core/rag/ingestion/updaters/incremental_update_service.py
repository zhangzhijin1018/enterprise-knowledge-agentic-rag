"""增量文档更新服务。

整合：变化检测 → 父子块同步 → 幂等保障 → Milvus 更新 → 版本记录

使用流程：
1. 用户上传新版本文档
2. 服务自动检测变化
3. 只更新变化的 chunks
4. 记录更新版本
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from core.vectorstore.base import BaseVectorStore
    from core.rag.ingestion.chunkers.change_detector import ChunkChangeDetector, ParentChildChangeDetector
    from core.rag.ingestion.updaters.version_manager import MilvusVersionManager

logger = logging.getLogger(__name__)


@dataclass
class UpdateResult:
    """更新结果。

    Attributes:
        status: 更新状态
        version: 版本号
        changes: 变化统计
        results: 详细结果
    """

    status: str  # "success" | "no_changes" | "stale_request" | "skipped"
    version: int = 0
    changes: dict[str, int] | None = None
    results: dict[str, Any] | None = None
    message: str = ""


class IncrementalDocumentUpdateService:
    """增量文档更新服务（生产级实现）。

    整合所有增量更新相关组件：
    - ChunkChangeDetector: 变化检测
    - ParentChildChangeDetector: 父子块同步
    - IdempotentIncrementalUpdater: 幂等性保障
    - MilvusVersionManager: 版本管理

    核心流程：
    1. 幂等性检查（request_id 去重）
    2. 获取旧 chunks（从数据库）
    3. 变化检测（position_index + content_hash）
    4. 父子块同步（子块变了，父块重建）
    5. 应用变化（upsert + delete）
    6. 版本管理（创建 + 激活）
    7. 持久化（元数据 + 版本记录）
    """

    def __init__(
        self,
        vector_store: "BaseVectorStore",
        chunk_detector: "ChunkChangeDetector",
        parent_child_detector: "ParentChildChangeDetector",
        version_manager: "MilvusVersionManager",
        document_repository,  # 文档仓库（PostgreSQL）
        redis_client,  # Redis 客户端
    ):
        """初始化增量更新服务。

        Args:
            vector_store: 向量存储
            chunk_detector: Chunk 变化检测器
            parent_child_detector: 父子块变化检测器
            version_manager: 版本管理器
            document_repository: 文档仓库
            redis_client: Redis 客户端
        """
        self.vector_store = vector_store
        self.chunk_detector = chunk_detector
        self.parent_child_detector = parent_child_detector
        self.version_manager = version_manager
        self.document_repo = document_repository
        self.redis = redis_client

    async def update_document(
        self,
        document_id: str,
        new_document_text: str,
        user_id: str,
        request_id: str,
        document_type: str = "general",
        expected_version: Optional[int] = None,
    ) -> UpdateResult:
        """执行增量更新（带幂等性保障）。

        Args:
            document_id: 文档 ID
            new_document_text: 新版文档内容
            user_id: 操作人
            request_id: 请求唯一 ID（幂等用）
            document_type: 文档类型
            expected_version: 期望的版本号

        Returns:
            更新结果
        """
        # =================================================================
        # Step 1: 幂等性检查
        # =================================================================
        idempotent_result = await self._check_idempotency(document_id, request_id)
        if idempotent_result:
            return idempotent_result

        # =================================================================
        # Step 2: 获取旧 chunks
        # =================================================================
        old_chunks = await self._get_old_chunks(document_id)

        if not old_chunks:
            # 文档首次入库，走全量流程
            return await self._full_index(
                document_id=document_id,
                document_text=new_document_text,
                user_id=user_id,
                request_id=request_id,
                document_type=document_type,
            )

        # =================================================================
        # Step 3: 变化检测
        # =================================================================
        changes = self.chunk_detector.detect_changes(old_chunks, new_document_text)

        if self._no_changes(changes):
            logger.info(f"文档无变化，跳过更新: {document_id}")
            return UpdateResult(
                status="no_changes",
                message="文档内容无变化",
                changes=changes.summary,
            )

        # =================================================================
        # Step 4: 版本检查
        # =================================================================
        if expected_version is not None:
            current_version = await self._get_current_version(document_id)
            if current_version > expected_version:
                return UpdateResult(
                    status="stale_request",
                    message=f"文档已被更新 (current={current_version}, expected={expected_version})",
                )

        # =================================================================
        # Step 5: 父子块同步（找出受影响的父块）
        # =================================================================
        affected_parent_positions = self._sync_parent_child(changes)

        # =================================================================
        # Step 6: 应用变化到 Milvus
        # =================================================================
        results = await self._apply_changes(
            document_id=document_id,
            changes=changes,
            affected_parent_positions=affected_parent_positions,
        )

        # =================================================================
        # Step 7: 版本管理
        # =================================================================
        new_version = await self._manage_version(
            document_id=document_id,
            user_id=user_id,
            milvus_primary_keys=results.get("milvus_primary_keys", []),
            chunk_count=results.get("chunk_count", 0),
            changelog=f"增量更新: {changes.summary}",
        )

        # =================================================================
        # Step 8: 保存 chunks 元数据到数据库
        # =================================================================
        await self._save_chunks_metadata(document_id, new_document_text, new_version)

        # =================================================================
        # Step 9: 记录更新结果（用于幂等查询）
        # =================================================================
        await self._cache_update_result(document_id, request_id, new_version, changes, results)

        logger.info(
            f"增量更新完成: doc={document_id}, version={new_version}, "
            f"changes={changes.summary}"
        )

        return UpdateResult(
            status="success",
            version=new_version,
            changes=changes.summary,
            results=results,
            message="更新成功",
        )

    async def _full_index(
        self,
        document_id: str,
        document_text: str,
        user_id: str,
        request_id: str,
        document_type: str,
    ) -> UpdateResult:
        """全量索引（新文档首次入库）。

        Args:
            document_id: 文档 ID
            document_text: 文档内容
            user_id: 操作人
            request_id: 请求 ID
            document_type: 文档类型

        Returns:
            索引结果
        """
        logger.info(f"全量索引: doc={document_id}")

        # 1. 分块
        chunks = self.chunk_detector._chunk_document(document_text)

        # 2. 生成父子块
        all_chunks = self._generate_parent_child_chunks(chunks)

        # 3. 插入 Milvus
        await self.vector_store.upsert_chunks(all_chunks)

        # 4. 版本管理
        milvus_primary_keys = [c.get("chunk_id", "") for c in all_chunks]
        new_version = await self._manage_version(
            document_id=document_id,
            user_id=user_id,
            milvus_primary_keys=milvus_primary_keys,
            chunk_count=len(all_chunks),
            changelog="全量索引",
        )

        # 5. 保存元数据
        await self._save_chunks_metadata(document_id, document_text, new_version)

        # 6. 缓存结果
        await self._cache_update_result(
            document_id=document_id,
            request_id=request_id,
            version=new_version,
            changes=None,
            results={"chunk_count": len(all_chunks), "full_index": True},
        )

        return UpdateResult(
            status="success",
            version=new_version,
            changes={"full_index": True, "chunk_count": len(all_chunks)},
            results={"full_index": True, "chunk_count": len(all_chunks)},
            message="全量索引完成",
        )

    async def _apply_changes(
        self,
        document_id: str,
        changes,
        affected_parent_positions: list[int],
    ) -> dict[str, Any]:
        """应用变化到 Milvus。

        Args:
            document_id: 文档 ID
            changes: 变化检测结果
            affected_parent_positions: 受影响的父块位置

        Returns:
            应用结果
        """
        results = {
            "deleted": 0,
            "updated": 0,
            "inserted": 0,
            "milvus_primary_keys": [],
            "chunk_count": 0,
        }

        # 1. 删除
        if changes.deleted:
            chunk_ids = [c.chunk_id for c in changes.deleted]
            await self.vector_store.delete_by_chunk_ids(chunk_ids)
            results["deleted"] = len(chunk_ids)
            logger.info(f"删除 chunks: {len(chunk_ids)} 个")

        # 2. 获取需要 upsert 的 chunks
        chunks_to_upsert = []

        # 修改的 chunk
        for c in changes.modified:
            chunks_to_upsert.append({
                "chunk_id": c.chunk_id,
                "position_index": c.position_index,
                "content": c.content,
                "content_hash": c.content_hash,
                "document_id": document_id,
                "chunk_type": "child",
            })
            results["updated"] += 1

        # 新增的 chunk
        for c in changes.new:
            chunks_to_upsert.append({
                "chunk_id": c.chunk_id,
                "position_index": c.position_index,
                "content": c.content,
                "content_hash": c.content_hash,
                "document_id": document_id,
                "chunk_type": "child",
            })
            results["inserted"] += 1

        # 3. 重建受影响的父块
        if affected_parent_positions:
            old_chunks = await self._get_old_chunks(document_id)
            parent_chunks = self._rebuild_affected_parents(
                old_chunks + chunks_to_upsert,
                affected_parent_positions,
                document_id,
            )
            chunks_to_upsert.extend(parent_chunks)
            results["updated"] += len(parent_chunks)

        # 4. Upsert
        if chunks_to_upsert:
            await self.vector_store.upsert_chunks(chunks_to_upsert)
            results["milvus_primary_keys"] = [c["chunk_id"] for c in chunks_to_upsert]
            results["chunk_count"] = len(chunks_to_upsert)

        return results

    def _generate_parent_child_chunks(
        self,
        child_chunks: list[dict[str, Any]],
        parent_chunk_size: int = 3,
    ) -> list[dict[str, Any]]:
        """生成父子块。

        Args:
            child_chunks: 子块列表
            parent_chunk_size: 每个父块包含的子块数量

        Returns:
            包含父子块的完整列表
        """
        all_chunks = list(child_chunks)  # 包含子块

        # 按位置分组生成父块
        for i in range(0, len(child_chunks), parent_chunk_size):
            parent = self._rebuild_parent_chunk(
                child_chunks, i, parent_chunk_size
            )
            if parent:
                all_chunks.append(parent)

        return all_chunks

    def _rebuild_parent_chunk(
        self,
        child_chunks: list[dict[str, Any]],
        parent_position: int,
        parent_chunk_size: int = 3,
    ) -> dict[str, Any] | None:
        """重建一个父块。

        Args:
            child_chunks: 子块列表
            parent_position: 父块位置
            parent_chunk_size: 每个父块包含的子块数量

        Returns:
            父块
        """
        return self.parent_child_detector.rebuild_parent_chunk(
            child_chunks, parent_position, parent_chunk_size
        )

    def _sync_parent_child(self, changes) -> list[int]:
        """同步父子块。

        Args:
            changes: 变化检测结果

        Returns:
            受影响的父块位置列表
        """
        # 合并新增和修改的子块
        changed_chunks = list(changes.modified) + list(changes.new)

        if not changed_chunks:
            return []

        # 调用父子块检测器
        affected_positions = self.parent_child_detector.sync_parent_child(
            changed_child_chunks=changed_chunks
        )

        logger.info(f"受影响的父块位置: {affected_positions}")

        return affected_positions

    def _rebuild_affected_parents(
        self,
        all_chunks: list[dict[str, Any]],
        affected_positions: list[int],
        document_id: str,
        parent_chunk_size: int = 3,
    ) -> list[dict[str, Any]]:
        """重建受影响的父块。

        Args:
            all_chunks: 所有 chunks
            affected_positions: 受影响的位置
            document_id: 文档 ID
            parent_chunk_size: 父块大小

        Returns:
            重建的父块列表
        """
        rebuilt_parents = []

        for pos in affected_positions:
            parent = self._rebuild_parent_chunk(
                all_chunks, pos, parent_chunk_size
            )
            if parent:
                parent["document_id"] = document_id
                parent["chunk_type"] = "parent"
                rebuilt_parents.append(parent)

        return rebuilt_parents

    async def _manage_version(
        self,
        document_id: str,
        user_id: str,
        milvus_primary_keys: list[str],
        chunk_count: int,
        changelog: str,
    ) -> int:
        """管理版本。

        Args:
            document_id: 文档 ID
            user_id: 操作人
            milvus_primary_keys: Milvus 主键
            chunk_count: chunk 数量
            changelog: 变更说明

        Returns:
            新版本号
        """
        # 创建新版本
        version = self.version_manager.create_version(
            document_id=document_id,
            user_id=user_id,
            changelog=changelog,
        )

        # 激活版本
        self.version_manager.activate_version(
            version_id=version.version_id,
            milvus_primary_keys=milvus_primary_keys,
            chunk_count=chunk_count,
        )

        return version.version_number

    async def _get_old_chunks(self, document_id: str) -> list[dict[str, Any]]:
        """获取旧 chunks。

        Args:
            document_id: 文档 ID

        Returns:
            旧 chunks 列表
        """
        # 从数据库获取
        if self.document_repo:
            return await self.document_repo.get_chunks(document_id)

        return []

    async def _save_chunks_metadata(
        self,
        document_id: str,
        document_text: str,
        version: int,
    ) -> None:
        """保存 chunks 元数据。

        Args:
            document_id: 文档 ID
            document_text: 文档内容
            version: 版本号
        """
        if self.document_repo:
            chunks = self.chunk_detector._chunk_document(document_text)
            await self.document_repo.save_chunks(document_id, chunks, version)

    async def _get_current_version(self, document_id: str) -> int:
        """获取当前版本号。

        Args:
            document_id: 文档 ID

        Returns:
            当前版本号
        """
        active_version = self.version_manager.get_active_version(document_id)
        return active_version.version_number if active_version else 0

    async def _check_idempotency(
        self,
        document_id: str,
        request_id: str,
    ) -> UpdateResult | None:
        """检查幂等性。

        Args:
            document_id: 文档 ID
            request_id: 请求 ID

        Returns:
            如果已处理过，返回结果；否则返回 None
        """
        dedup_key = f"idempotent:update:{document_id}:{request_id}"
        cached = await self.redis.get(dedup_key)

        if cached:
            import json
            result_data = json.loads(cached)
            return UpdateResult(
                status=result_data.get("status", "cached"),
                version=result_data.get("version", 0),
                changes=result_data.get("changes"),
                message="返回缓存结果",
            )

        return None

    async def _cache_update_result(
        self,
        document_id: str,
        request_id: str,
        version: int,
        changes,
        results: dict[str, Any],
    ) -> None:
        """缓存更新结果。

        Args:
            document_id: 文档 ID
            request_id: 请求 ID
            version: 版本号
            changes: 变化结果
            results: 详细结果
        """
        import json

        cache_key = f"idempotent:update:{document_id}:{request_id}"
        cache_data = {
            "status": "success",
            "version": version,
            "changes": changes.summary if hasattr(changes, "summary") else changes,
            "results": results,
        }

        await self.redis.set(cache_key, json.dumps(cache_data), ex=86400 * 7)

    def _no_changes(self, changes) -> bool:
        """检查是否有变化。

        Args:
            changes: 变化检测结果

        Returns:
            是否没有变化
        """
        return (
            len(changes.modified) == 0
            and len(changes.new) == 0
            and len(changes.deleted) == 0
        )


# =============================================================================
# 便捷工厂函数
# =============================================================================

def create_incremental_update_service(
    vector_store,
    redis_client,
    document_repository=None,
) -> IncrementalDocumentUpdateService:
    """创建增量更新服务（便捷工厂函数）。

    Args:
        vector_store: 向量存储
        redis_client: Redis 客户端
        document_repository: 文档仓库（可选）

    Returns:
        增量更新服务实例
    """
    from core.rag.ingestion.chunkers.change_detector import ChunkChangeDetector, ParentChildChangeDetector
    from core.rag.ingestion.updaters.version_manager import MilvusVersionManager, InMemoryVersionStore

    # 创建组件
    chunk_detector = ChunkChangeDetector()
    parent_child_detector = ParentChildChangeDetector()

    # 版本存储（实际项目用 PostgreSQL）
    version_store = InMemoryVersionStore()

    # Milvus 客户端（实际项目传入真实的 Milvus 客户端）
    milvus_client = None

    version_manager = MilvusVersionManager(
        version_store=version_store,
        milvus_client=milvus_client,
    )

    return IncrementalDocumentUpdateService(
        vector_store=vector_store,
        chunk_detector=chunk_detector,
        parent_child_detector=parent_child_detector,
        version_manager=version_manager,
        document_repository=document_repository,
        redis_client=redis_client,
    )
