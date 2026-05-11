"""
Agent 事件生产者 - Redis Streams 写入

负责将 Agent 事件写入 Redis Streams，供 Supervisor 消费。

核心功能：
1. 事件发布到 Redis Stream
2. 自动管理 Stream 生命周期（TTL、长度限制）
3. 支持多 Agent 并行写入
4. 异步操作，不阻塞 Agent 执行

使用示例：
```python
from core.common.events import AgentEventProducer, create_progress_event

producer = AgentEventProducer()
await producer.connect()

# 发布进度事件
event = create_progress_event(
    run_id="run_123",
    agent_name="analytics-agent",
    stage="sql_build",
    progress=25,
    message="正在构建 SQL...",
)
await producer.publish(event)

# 完成时
await producer.publish_complete("run_123", "analytics-agent", {"answer": "..."})

await producer.close()
```

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Optional

from redis.asyncio.client import Redis
from redis.asyncio.connection import ConnectionPool

from core.config import get_settings
from core.common.events.schema import AgentEvent, EventType

if TYPE_CHECKING:
    from core.config import Settings

logger = logging.getLogger(__name__)


class AgentEventProducer:
    """
    Agent 事件生产者 - 写入 Redis Streams

    设计考量：
    1. 异步连接池：复用连接，高性能
    2. 自动 TTL：防止 Redis 内存泄漏
    3. 自动 MAXLEN：限制 Stream 长度
    4. 事件序列化：统一 JSON 格式

    Redis Stream Key 格式：
        events:{run_id}

    示例：
        events:run_abc123
    """

    # Stream 配置常量
    STREAM_KEY_PREFIX = "events"
    MAX_STREAM_LENGTH = 200      # 最大消息数
    STREAM_TTL_SECONDS = 7200    # 2 小时 TTL

    def __init__(
        self,
        redis_url: Optional[str] = None,
        stream_key_prefix: Optional[str] = None,
        max_stream_len: int = MAX_STREAM_LENGTH,
        stream_ttl_seconds: int = STREAM_TTL_SECONDS,
    ) -> None:
        """初始化事件生产者。

        Args:
            redis_url: Redis 连接 URL（默认从配置读取）
            stream_key_prefix: Stream Key 前缀
            max_stream_len: Stream 最大消息数
            stream_ttl_seconds: Stream TTL（秒）
        """
        settings = get_settings()
        self.redis_url = redis_url or settings.redis_url
        self.stream_key_prefix = stream_key_prefix or self.STREAM_KEY_PREFIX
        self.max_stream_len = max_stream_len
        self.stream_ttl_seconds = stream_ttl_seconds

        self._pool: Optional[ConnectionPool] = None
        self._client: Optional[Redis] = None
        self._connected = False

    async def connect(self) -> None:
        """建立 Redis 连接。

        使用懒加载模式，首次使用时才创建连接。
        """
        if self._connected:
            return

        settings = get_settings()

        self._pool = ConnectionPool.from_url(
            self.redis_url,
            max_connections=settings.redis_pool_max_connections,
            socket_timeout=settings.redis_socket_timeout,
            socket_connect_timeout=settings.redis_socket_connect_timeout,
            decode_responses=True,
        )

        self._client = Redis(connection_pool=self._pool)

        # 测试连接
        await self._client.ping()

        self._connected = True
        logger.info(f"AgentEventProducer 已连接: {self.redis_url}")

    async def close(self) -> None:
        """关闭 Redis 连接。"""
        if self._client:
            await self._client.close()
            self._client = None

        if self._pool:
            await self._pool.disconnect()
            self._pool = None

        self._connected = False
        logger.info("AgentEventProducer 已关闭")

    @property
    def client(self) -> Redis:
        """获取 Redis 客户端。

        Returns:
            Redis 异步客户端

        Raises:
            RuntimeError: 如果未连接
        """
        if not self._client:
            raise RuntimeError("未连接 Redis，请先调用 connect()")
        return self._client

    def _get_stream_key(self, run_id: str) -> str:
        """获取 Stream Key。

        Args:
            run_id: 任务运行 ID

        Returns:
            Stream Key，格式：events:{run_id}
        """
        return f"{self.stream_key_prefix}:{run_id}"

    async def _ensure_stream_ttl(self, stream_key: str) -> None:
        """确保 Stream 设置了 TTL。

        Redis Stream 不需要预先创建，但我们可以确保 TTL 被设置。

        Args:
            stream_key: Stream Key
        """
        try:
            ttl = await self.client.ttl(stream_key)
            if ttl == -1:  # -1 表示没有设置过期时间
                await self.client.expire(stream_key, self.stream_ttl_seconds)
        except Exception as e:
            logger.warning(f"设置 Stream TTL 失败: {stream_key}, {e}")

    async def publish(self, event: AgentEvent) -> str:
        """发布事件到 Redis Stream。

        Args:
            event: Agent 事件

        Returns:
            Redis Stream 消息 ID，格式为 "timestamp-seqnum"

        Raises:
            RuntimeError: 如果未连接
        """
        if not self._connected:
            await self.connect()

        stream_key = self._get_stream_key(event.run_id)

        # 确保 TTL 已设置
        await self._ensure_stream_ttl(stream_key)

        # 序列化事件
        payload = {
            "event": event.to_json(),
            "timestamp": str(event.timestamp),
        }

        # XADD 自动创建 Stream，MAXLEN ~ 近似裁剪
        message_id = await self.client.xadd(
            stream_key,
            payload,
            maxlen=self.max_stream_len,
            approximate=True,
        )

        logger.debug(
            f"发布事件: run_id={event.run_id}, "
            f"agent={event.agent_name}, "
            f"event_type={event.event_type}, "
            f"message_id={message_id}"
        )

        return message_id

    async def publish_progress(
        self,
        run_id: str,
        agent_name: str,
        stage: str,
        progress: int,
        message: str,
        *,
        trace_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        **extra_data: Any,
    ) -> str:
        """快捷方法：发布进度事件。

        Args:
            run_id: 任务运行 ID
            agent_name: Agent 名称
            stage: 当前阶段
            progress: 进度百分比
            message: 消息
            trace_id: 追踪 ID
            conversation_id: 会话 ID
            **extra_data: 额外数据

        Returns:
            消息 ID
        """
        from core.common.events.schema import create_progress_event

        event = create_progress_event(
            run_id=run_id,
            agent_name=agent_name,
            stage=stage,
            progress=progress,
            message=message,
            trace_id=trace_id,
            conversation_id=conversation_id,
            **extra_data,
        )

        return await self.publish(event)

    async def publish_complete(
        self,
        run_id: str,
        agent_name: str,
        message: str = "任务完成",
        *,
        trace_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        **result_data: Any,
    ) -> str:
        """快捷方法：发布完成事件。

        Args:
            run_id: 任务运行 ID
            agent_name: Agent 名称
            message: 消息
            trace_id: 追踪 ID
            conversation_id: 会话 ID
            **result_data: 结果数据

        Returns:
            消息 ID
        """
        from core.common.events.schema import create_complete_event

        event = create_complete_event(
            run_id=run_id,
            agent_name=agent_name,
            message=message,
            trace_id=trace_id,
            conversation_id=conversation_id,
            **result_data,
        )

        return await self.publish(event)

    async def publish_error(
        self,
        run_id: str,
        agent_name: str,
        error_code: str,
        error_message: str,
        *,
        trace_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> str:
        """快捷方法：发布错误事件。

        Args:
            run_id: 任务运行 ID
            agent_name: Agent 名称
            error_code: 错误码
            error_message: 错误信息
            trace_id: 追踪 ID
            conversation_id: 会话 ID

        Returns:
            消息 ID
        """
        from core.common.events.schema import create_error_event

        event = create_error_event(
            run_id=run_id,
            agent_name=agent_name,
            error_code=error_code,
            error_message=error_message,
            trace_id=trace_id,
            conversation_id=conversation_id,
        )

        return await self.publish(event)

    async def cleanup(self, run_id: str) -> None:
        """清理 Stream（删除）。

        任务结束后可选调用，释放 Redis 内存。
        通常依赖 TTL 自动清理。

        Args:
            run_id: 任务运行 ID
        """
        stream_key = self._get_stream_key(run_id)
        await self.client.delete(stream_key)
        logger.debug(f"清理 Stream: {stream_key}")


# =============================================================================
# 全局单例生产者
# =============================================================================

_producer_instance: Optional[AgentEventProducer] = None
_producer_lock = asyncio.Lock()


async def get_event_producer() -> AgentEventProducer:
    """获取全局事件生产者单例。

    Returns:
        AgentEventProducer 单例实例
    """
    global _producer_instance

    async with _producer_lock:
        if _producer_instance is None:
            _producer_instance = AgentEventProducer()
            await _producer_instance.connect()

        return _producer_instance


async def close_event_producer() -> None:
    """关闭全局事件生产者。"""
    global _producer_instance

    async with _producer_lock:
        if _producer_instance:
            await _producer_instance.close()
            _producer_instance = None
