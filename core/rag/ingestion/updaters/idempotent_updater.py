"""幂等性增量更新器。

幂等性 = 同一操作执行多次，结果都一样

幂等性保障手段：
1. 请求级别去重：用 request_id 防止重复请求
2. 状态检查：更新前检查是否已完成
3. 版本号控制：用版本号确保顺序更新
4. 原子操作：用事务保证要么全成功要么全失败
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from core.vectorstore.base import BaseVectorStore

logger = logging.getLogger(__name__)


class IdempotentIncrementalUpdater:
    """具备幂等性的增量更新器。

    幂等性保障机制：

    1. request_id 去重
       - 同一个 request_id 只处理一次
       - 重复请求直接返回缓存结果

    2. Redis 锁
       - 同一文档同时只有一个更新在执行
       - 防止并发更新导致数据竞争

    3. 版本号控制
       - expected_version 检查
       - 防止旧请求覆盖新数据

    4. upsert 代替 insert
       - 重复执行结果一样
       - 不会产生垃圾数据
    """

    def __init__(
        self,
        vector_store: "BaseVectorStore",
        redis_client,  # Redis 客户端
        chunk_detector,  # ChunkChangeDetector
    ):
        """初始化幂等性更新器。

        Args:
            vector_store: 向量存储
            redis_client: Redis 客户端
            chunk_detector: Chunk 变化检测器
        """
        self.vector_store = vector_store
        self.redis = redis_client
        self.detector = chunk_detector

    async def update_with_idempotency(
        self,
        document_id: str,
        new_document_text: str,
        request_id: str,
        expected_version: Optional[int] = None,
    ) -> dict[str, Any]:
        """幂等的增量更新。

        Args:
            document_id: 文档 ID
            new_document_text: 新版文档内容
            request_id: 请求唯一标识（用于去重）
            expected_version: 期望的版本号（用于乐观锁）

        Returns:
            更新结果
        """
        # =================================================================
        # Step 1: 请求去重（幂等性保障第一层）
        # =================================================================
        dedup_key = f"idempotent:update:{document_id}:{request_id}"

        existing_result = await self.redis.get(dedup_key)
        if existing_result:
            logger.info(f"请求已处理过，直接返回缓存结果: {request_id}")
            return json.loads(existing_result)

        # =================================================================
        # Step 2: 获取分布式锁（幂等性保障第二层）
        # =================================================================
        lock_key = f"lock:update:{document_id}"
        lock_acquired = await self.redis.set(
            lock_key,
            request_id,
            nx=True,  # 只有不存在时才设置
            ex=60,  # 60 秒超时
        )

        if not lock_acquired:
            logger.info(f"等待锁释放: {document_id}")
            await self._wait_for_lock(lock_key)

            # 等待期间可能已完成，直接返回结果
            existing_result = await self.redis.get(dedup_key)
            if existing_result:
                return json.loads(existing_result)

        try:
            # =================================================================
            # Step 3: 版本检查（幂等性保障第三层）
            # =================================================================
            current_version = await self._get_document_version(document_id)

            if expected_version is not None and current_version > expected_version:
                logger.warning(
                    f"版本过期: expected={expected_version}, actual={current_version}"
                )
                return {
                    "status": "stale_request",
                    "reason": "文档已被更新，请获取最新版本后重试",
                    "current_version": current_version,
                }

            # =================================================================
            # Step 4: 执行增量更新
            # =================================================================
            result = await self._do_update(document_id, new_document_text)

            # =================================================================
            # Step 5: 保存结果（用于后续幂等查询）
            # =================================================================
            await self.redis.set(
                dedup_key,
                json.dumps(result),
                ex=86400 * 7,  # 保留 7 天
            )

            return result

        finally:
            # 释放锁
            await self.redis.delete(lock_key)

    async def _do_update(
        self,
        document_id: str,
        new_document_text: str,
    ) -> dict[str, Any]:
        """执行实际的更新逻辑。

        Args:
            document_id: 文档 ID
            new_document_text: 新版文档内容

        Returns:
            更新结果
        """
        # 1. 获取旧 chunks（需要从外部传入或查询）
        # 这里假设外部已处理好
        old_chunks = getattr(self, "_old_chunks", [])

        # 2. 检测变化
        changes = self.detector.detect_changes(old_chunks, new_document_text)

        if self._no_changes(changes):
            return {
                "status": "no_changes",
                "changes": changes.summary,
            }

        # 3. 应用变化（使用 upsert 保证幂等）
        await self._apply_changes_atomically(changes)

        # 4. 更新版本号
        new_version = await self._increment_version(document_id)

        logger.info(
            f"增量更新完成: doc={document_id}, "
            f"version={new_version}, changes={changes.summary}"
        )

        return {
            "status": "success",
            "version": new_version,
            "changes": changes.summary,
        }

    async def _apply_changes_atomically(self, changes) -> None:
        """原子性应用变化。

        关键点：使用 Milvus upsert 而不是 insert
        - insert：重复执行会创建多条记录
        - upsert：重复执行只会更新到最新值

        Args:
            changes: 变化检测结果
        """
        # 删除（幂等：删已删除的不报错）
        if changes.deleted:
            chunk_ids = [c.chunk_id for c in changes.deleted]
            await self.vector_store.delete_by_chunk_ids(chunk_ids)
            logger.info(f"删除 chunks: {len(chunk_ids)} 个")

        # upsert = insert or update（幂等：重复执行结果一样）
        chunks_to_upsert = changes.modified + changes.new
        if chunks_to_upsert:
            # 转换为字典格式
            chunk_dicts = [c.__dict__ for c in chunks_to_upsert]
            await self.vector_store.upsert_chunks(chunk_dicts)
            logger.info(f"Upsert chunks: {len(chunk_dicts)} 个")

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

    async def _wait_for_lock(self, lock_key: str, max_wait: int = 60) -> None:
        """等待锁释放。

        Args:
            lock_key: 锁 key
            max_wait: 最大等待时间（秒）
        """
        import asyncio

        wait_time = 0
        while wait_time < max_wait:
            locked = await self.redis.exists(lock_key)
            if not locked:
                return

            await asyncio.sleep(1)
            wait_time += 1

        raise TimeoutError(f"等待锁释放超时: {lock_key}")

    async def _get_document_version(self, document_id: str) -> int:
        """获取文档当前版本号。

        Args:
            document_id: 文档 ID

        Returns:
            当前版本号
        """
        version_key = f"doc:version:{document_id}"
        version = await self.redis.get(version_key)
        return int(version) if version else 0

    async def _increment_version(self, document_id: str) -> int:
        """递增版本号（原子操作）。

        Args:
            document_id: 文档 ID

        Returns:
            新版本号
        """
        version_key = f"doc:version:{document_id}"
        return await self.redis.incr(version_key)


class IdempotentOperation:
    """幂等操作包装器。

    将任意操作包装为幂等操作。
    """

    def __init__(self, redis_client, ttl: int = 86400 * 7):
        """初始化幂等操作包装器。

        Args:
            redis_client: Redis 客户端
            ttl: 结果保留时间（秒），默认 7 天
        """
        self.redis = redis_client
        self.ttl = ttl

    async def execute(
        self,
        operation_id: str,
        operation_func,
        *args,
        **kwargs,
    ) -> tuple[dict[str, Any], bool]:
        """执行幂等操作。

        Args:
            operation_id: 操作唯一 ID
            operation_func: 操作函数（async）
            *args: 操作函数参数
            **kwargs: 操作函数关键字参数

        Returns:
            (结果, 是否已执行过)
        """
        cache_key = f"idempotent:op:{operation_id}"

        # 检查是否已执行
        cached = await self.redis.get(cache_key)
        if cached:
            return json.loads(cached), True

        # 执行操作
        result = await operation_func(*args, **kwargs)

        # 缓存结果
        await self.redis.set(cache_key, json.dumps(result), ex=self.ttl)

        return result, False

    async def get_cached_result(self, operation_id: str) -> dict[str, Any] | None:
        """获取缓存的操作结果。

        Args:
            operation_id: 操作 ID

        Returns:
            缓存结果，如果不存在返回 None
        """
        cache_key = f"idempotent:op:{operation_id}"
        cached = await self.redis.get(cache_key)
        return json.loads(cached) if cached else None

    async def is_executed(self, operation_id: str) -> bool:
        """检查操作是否已执行过。

        Args:
            operation_id: 操作 ID

        Returns:
            是否已执行
        """
        cache_key = f"idempotent:op:{operation_id}"
        return await self.redis.exists(cache_key)
