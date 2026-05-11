"""
Agent 事件消费者 - Redis Streams 消费 + SSE 推送

负责从 Redis Streams 消费事件，通过 SSE 推送给前端。

核心功能：
1. 从 Redis Stream 消费事件
2. 转换为 SSE 格式推送给前端
3. 支持断线重连（从上次位置继续）
4. 心跳保活

使用示例：
```python
from core.common.events.consumer import AgentEventConsumer

consumer = AgentEventConsumer()
async for message in consumer.consume(run_id="run_123"):
    # message 是 SSE 格式的 bytes
    yield message
```

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any, AsyncGenerator, Optional

from redis.asyncio.client import Redis
from redis.asyncio.connection import ConnectionPool

from core.config import get_settings
from core.common.events.schema import AgentEvent, EventType

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AgentEventConsumer:
    """
    Agent 事件消费者 - 从 Redis Streams 消费并转为 SSE

    设计考量：
    1. XREADGROUP 支持消费组，多个 SSE 连接可以各自消费
    2. 从指定位置开始读，支持断线重连
    3. 心跳机制防止连接超时
    4. 优雅关闭

    Redis Stream Key 格式：
        events:{run_id}

    SSE 消息格式：
        event: {event_type}
        data: {json_data}

        (空行结束)
    """

    # 配置常量
    STREAM_KEY_PREFIX = "events"
    HEARTBEAT_INTERVAL = 30  # 心跳间隔（秒）
    READ_BLOCK_MS = 5000    # XREAD 阻塞时间（毫秒）
    MAX_MESSAGES_PER_READ = 100  # 每次最多读取消息数

    def __init__(
        self,
        redis_url: Optional[str] = None,
        stream_key_prefix: Optional[str] = None,
        consumer_id: Optional[str] = None,
        heartbeat_interval: int = HEARTBEAT_INTERVAL,
    ) -> None:
        """初始化事件消费者。

        Args:
            redis_url: Redis 连接 URL（默认从配置读取）
            stream_key_prefix: Stream Key 前缀
            consumer_id: 消费者 ID（用于消费组标识）
            heartbeat_interval: 心跳间隔（秒）
        """
        settings = get_settings()
        self.redis_url = redis_url or settings.redis_url
        self.stream_key_prefix = stream_key_prefix or self.STREAM_KEY_PREFIX
        self.consumer_id = consumer_id or f"consumer_{id(self)}"
        self.heartbeat_interval = heartbeat_interval

        self._pool: Optional[ConnectionPool] = None
        self._client: Optional[Redis] = None
        self._running = False

    async def connect(self) -> None:
        """建立 Redis 连接。"""
        if self._client:
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
        await self._client.ping()

        logger.info(f"AgentEventConsumer 已连接: {self.redis_url}")

    async def close(self) -> None:
        """关闭 Redis 连接。"""
        if self._client:
            await self._client.close()
            self._client = None

        if self._pool:
            await self._pool.disconnect()
            self._pool = None

        self._running = False
        logger.info("AgentEventConsumer 已关闭")

    @property
    def client(self) -> Redis:
        """获取 Redis 客户端。"""
        if not self._client:
            raise RuntimeError("未连接 Redis，请先调用 connect()")
        return self._client

    def _get_stream_key(self, run_id: str) -> str:
        """获取 Stream Key。"""
        return f"{self.stream_key_prefix}:{run_id}"

    def _format_sse(self, event: AgentEvent) -> bytes:
        """格式化 SSE 消息。

        Args:
            event: Agent 事件

        Returns:
            SSE 格式的字节串
        """
        json_data = event.to_json()
        return f"event: {event.event_type}\ndata: {json_data}\n\n".encode("utf-8")

    def _format_sse_raw(self, event_type: str, data: dict) -> bytes:
        """格式化 SSE 消息（原始数据）。

        Args:
            event_type: 事件类型
            data: 数据字典

        Returns:
            SSE 格式的字节串
        """
        json_data = json.dumps(data, ensure_ascii=False)
        return f"event: {event_type}\ndata: {json_data}\n\n".encode("utf-8")

    async def _send_heartbeat(self) -> bytes:
        """生成心跳消息。"""
        return self._format_sse_raw(
            EventType.HEARTBEAT.value,
            {"time": int(time.time() * 1000), "consumer_id": self.consumer_id}
        )

    async def _send_connected(self, run_id: str) -> bytes:
        """生成连接成功消息。"""
        return self._format_sse_raw(
            EventType.CONNECTED.value,
            {"run_id": run_id, "consumer_id": self.consumer_id}
        )

    async def _send_error(self, run_id: str, message: str) -> bytes:
        """生成错误消息。"""
        return self._format_sse_raw(
            EventType.ERROR.value,
            {"run_id": run_id, "message": message}
        )

    async def consume(self, run_id: str) -> AsyncGenerator[bytes, None]:
        """消费 Redis Stream，生成 SSE 事件。

        这是一个异步生成器，yield SSE 格式的字节消息。

        Args:
            run_id: 任务运行 ID

        Yields:
            SSE 格式的字节消息

        终止条件：
        1. 收到 COMPLETED 或 ERROR 事件
        2. 外部取消（break）
        3. Redis Stream 不存在或超时
        """
        await self.connect()
        self._running = True

        stream_key = self._get_stream_key(run_id)

        # 检查 Stream 是否存在
        stream_exists = await self.client.exists(stream_key)
        if not stream_exists:
            logger.warning(f"Stream 不存在: {stream_key}")
            yield await self._send_error(run_id, "Task not found or expired")
            return

        # 发送连接成功
        yield await self._send_connected(run_id)

        # 记录最后消息 ID
        last_message_id = "0"

        # 主循环
        while self._running:
            try:
                # XREAD 阻塞读取新消息
                messages = await self.client.xread(
                    {stream_key: last_message_id},
                    count=self.MAX_MESSAGES_PER_READ,
                    block=self.READ_BLOCK_MS,
                )

                if not messages:
                    # 超时，发送心跳
                    yield await self._send_heartbeat()
                    continue

                for stream, message_list in messages:
                    for message_id, fields in message_list:
                        last_message_id = message_id

                        # 解析事件
                        try:
                            event_data = fields.get("event", "{}")
                            event = AgentEvent.from_json(event_data)
                        except Exception:
                            # 兼容旧格式或其他格式
                            event = AgentEvent(
                                run_id=run_id,
                                agent_name=fields.get("agent", "unknown"),
                                event_type=fields.get("event", "message"),
                                message=fields.get("data", "{}"),
                            )

                        # 发送 SSE 事件
                        yield self._format_sse(event)

                        # 完成或错误，退出
                        if event.event_type in (
                            EventType.COMPLETED.value,
                            EventType.ERROR.value,
                        ):
                            self._running = False
                            return

            except asyncio.CancelledError:
                logger.debug(f"SSE Consumer 取消: run_id={run_id}")
                self._running = False
                raise

            except Exception as e:
                logger.error(f"SSE Consumer 错误: run_id={run_id}, error={e}")
                yield await self._send_error(run_id, str(e))
                self._running = False
                return

    def stop(self) -> None:
        """停止消费。"""
        self._running = False


# =============================================================================
# 便捷函数
# =============================================================================

async def sse_event_stream(
    run_id: str,
    consumer_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """SSE 事件流生成器（供 FastAPI 使用）。

    Args:
        run_id: 任务运行 ID
        consumer_id: 消费者 ID

    Yields:
        SSE 格式的字符串
    """
    consumer = AgentEventConsumer(consumer_id=consumer_id)

    try:
        async for message in consumer.consume(run_id):
            yield message.decode("utf-8")
    finally:
        await consumer.close()
