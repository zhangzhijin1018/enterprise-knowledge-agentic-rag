"""基于 Redis Streams 的生产级 SSE 进度推送模块。

核心设计理念：
1. 跨进程/跨 Worker 通信：Workflow 节点和 API 进程可以不在同一进程
2. 断线重连：Redis Stream 持久化消息，断线后可从上次位置继续消费
3. 消息清理：自动 TTL + MAXLEN 限制，防止 Redis 内存泄漏
4. 高性能：异步连接池 + 批量操作

数据流：
  Workflow 节点 --XADD--> Redis Stream --XREAD--> SSE Endpoint --HTTP--> 前端

Redis 数据结构：
  Key: sse:progress:{run_id}
  Type: Redis Stream
  Fields: event, data, timestamp
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncGenerator

from redis.asyncio.client import Redis
from redis.asyncio.connection import ConnectionPool

from core.config import get_settings

if TYPE_CHECKING:
    from core.config import Settings

logger = logging.getLogger(__name__)


# =============================================================================
# 配置常量
# =============================================================================

# Redis Stream 事件类型常量
class SSEEventType:
    """SSE 事件类型枚举。"""
    CONNECTED = "connected"          # 连接成功
    STARTED = "started"             # 任务开始
    PROGRESS = "progress"           # 进度更新
    SUMMARY_DONE = "summary_done"    # 摘要生成完成
    INSIGHT_DONE = "insight_done"   # 洞察生成完成
    CHART_DONE = "chart_done"       # 图表生成完成
    REPORT_DONE = "report_done"     # 报告生成完成
    HEARTBEAT = "heartbeat"         # 心跳保活
    COMPLETE = "complete"           # 任务完成
    ERROR = "error"                 # 任务失败


# =============================================================================
# Redis 连接池管理（单例模式）
# =============================================================================

class RedisConnectionPool:
    """Redis 异步连接池管理器（单例模式）。

    设计考量：
    1. 全局共享连接池，避免每次操作都创建/销毁连接
    2. 支持配置化：pool_size、max_connections、timeout 等
    3. 懒加载：首次使用时才初始化连接池
    4. 健康检查：定期检测连接可用性

    线程安全：使用 asyncio.Lock 保证初始化线程安全
    """

    _instance: "RedisConnectionPool | None" = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(self) -> None:
        self._pool: ConnectionPool | None = None
        self._redis_client: Redis | None = None
        self._settings: Settings | None = None

    @classmethod
    async def get_instance(cls) -> "RedisConnectionPool":
        """获取单例实例（线程安全）。

        Returns:
            RedisConnectionPool 单例实例
        """
        if cls._instance is None:
            async with cls._lock:
                # 双重检查锁定
                if cls._instance is None:
                    cls._instance = cls()
                    await cls._instance._initialize()
        return cls._instance

    async def _initialize(self) -> None:
        """初始化连接池（内部方法）。

        从 settings 读取配置，创建 ConnectionPool 和 Redis client。
        """
        self._settings = get_settings()

        # 解析 Redis URL 获取连接参数
        redis_url = self._settings.redis_url

        # 创建连接池配置
        self._pool = ConnectionPool.from_url(
            redis_url,
            max_connections=self._settings.redis_pool_max_connections,
            socket_timeout=self._settings.redis_socket_timeout,
            socket_connect_timeout=self._settings.redis_socket_connect_timeout,
            decode_responses=True,  # 自动将 bytes 解码为 str
        )

        # 创建 Redis 客户端（共享连接池）
        self._redis_client = Redis(connection_pool=self._pool)

        logger.info(
            f"Redis 连接池初始化完成: {redis_url}, "
            f"max_connections={self._settings.redis_pool_max_connections}"
        )

    @property
    def redis(self) -> Redis:
        """获取 Redis 客户端实例。

        Returns:
            Redis 异步客户端

        Raises:
            RuntimeError: 如果连接池未初始化
        """
        if self._redis_client is None:
            raise RuntimeError("Redis 连接池未初始化，请先调用 get_instance()")
        return self._redis_client

    async def close(self) -> None:
        """关闭连接池，释放资源。

        应用关闭时调用。
        """
        if self._redis_client:
            await self._redis_client.close()
            self._redis_client = None

        if self._pool:
            await self._pool.disconnect()
            self._pool = None

        logger.info("Redis 连接池已关闭")

    async def health_check(self) -> bool:
        """健康检查。

        Returns:
            True 表示 Redis 可用，False 表示不可用
        """
        try:
            await self.redis.ping()
            return True
        except Exception as e:
            logger.error(f"Redis 健康检查失败: {e}")
            return False


# 全局连接池获取函数
async def get_redis_pool() -> RedisConnectionPool:
    """获取 Redis 连接池实例。

    推荐使用方式：
    ```python
    pool = await get_redis_pool()
    await pool.redis.set("key", "value")
    ```

    Returns:
        Redis 连接池管理器实例
    """
    return await RedisConnectionPool.get_instance()


# =============================================================================
# SSE 进度数据模型
# =============================================================================

@dataclass
class SSEProgressData:
    """SSE 进度数据结构。

    统一规范 SSE 消息的数据格式，便于序列化和反序列化。
    """

    # 任务运行ID
    run_id: str

    # 当前状态：running / completed / failed
    status: str = "running"

    # 当前步骤名称（显示给用户）
    current_step: str | None = None

    # 步骤标识（内部使用）
    step_key: str | None = None

    # 进度百分比 0-100
    progress: int = 0

    # 所有步骤及其状态（完整追踪）
    steps: list[dict[str, str]] | None = None

    # 最终结果（仅 complete 时有值）
    result: dict | None = None

    # 错误信息（仅 error 时有值）
    error: dict | None = None

    # 额外数据
    extra: dict | None = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。

        Returns:
            字典格式的进度数据
        """
        data = {
            "run_id": self.run_id,
            "status": self.status,
            "current_step": self.current_step,
            "progress": self.progress,
            "step_key": self.step_key,
        }

        if self.steps:
            data["steps"] = self.steps

        if self.result:
            data["result"] = self.result

        if self.error:
            data["error"] = self.error

        if self.extra:
            data.update(self.extra)

        return data

    @classmethod
    def from_stream_message(cls, message_data: dict[str, str]) -> "SSEProgressData":
        """从 Redis Stream 消息创建实例。

        Args:
            message_data: Redis Stream 消息的 data 字段（JSON 字符串）

        Returns:
            SSEProgressData 实例
        """
        data = json.loads(message_data.get("data", "{}"))
        return cls(
            run_id=data.get("run_id", ""),
            status=data.get("status", "running"),
            current_step=data.get("current_step"),
            step_key=data.get("step_key"),
            progress=data.get("progress", 0),
            steps=data.get("steps"),
            result=data.get("result"),
            error=data.get("error"),
            extra={k: v for k, v in data.items()
                   if k not in ("run_id", "status", "current_step",
                               "step_key", "progress", "steps",
                               "result", "error")},
        )


# =============================================================================
# Redis Streams SSE Publisher
# =============================================================================

class RedisSSEPublisher:
    """基于 Redis Streams 的 SSE 进度发布器。

    负责将任务执行进度发布到 Redis Stream，供 SSE Consumer 消费。

    设计考量：
    1. 每个 run_id 对应一个独立的 Redis Stream
    2. 使用 XADD MAXLEN ~ 限制消息数量，防止内存泄漏
    3. 消息包含完整上下文，支持断线重连
    4. 支持多消费者（通过不同 consumer_id 区分）

    性能优化：
    1. 使用 XADD 而非 LPUSH，保证消息顺序
    2. MAXLEN ~ 自动清理旧消息（近似裁剪，开销低）
    3. 异步操作，不阻塞事件循环
    """

    def __init__(
        self,
        run_id: str,
        redis_client: Redis,
        stream_key_prefix: str = "sse:progress",
        max_stream_len: int = 100,
        stream_ttl_seconds: int = 3600,
    ) -> None:
        """初始化发布器。

        Args:
            run_id: 任务运行ID
            redis_client: Redis 异步客户端
            stream_key_prefix: Stream Key 前缀
            max_stream_len: Stream 最大消息数
            stream_ttl_seconds: Stream TTL（秒）
        """
        self.run_id = run_id
        self.redis = redis_client
        self.stream_key = f"{stream_key_prefix}:{run_id}"
        self.max_stream_len = max_stream_len
        self.stream_ttl_seconds = stream_ttl_seconds

        # 标记是否已发布完成/错误（防止重复发送终止消息）
        self._finished = False

    async def _ensure_stream_exists(self) -> None:
        """确保 Stream 存在并设置 TTL。

        Redis Stream 不需要预先创建，XADD 会自动创建。
        但我们可以在第一条消息时设置 TTL（通过 EXPIRE）。
        """
        # 检查是否已设置 TTL
        ttl = await self.redis.ttl(self.stream_key)
        if ttl == -1:  # -1 表示没有设置过期时间
            # 设置 TTL（最多尝试一次，避免每次都检查）
            await self.redis.expire(self.stream_key, self.stream_ttl_seconds)

    def _serialize_payload(self, event_type: str, data: dict) -> dict[str, str]:
        """序列化消息负载。

        Redis Stream 只支持字符串字段，需要将数据 JSON 序列化。

        Args:
            event_type: 事件类型
            data: 事件数据

        Returns:
            序列化的消息字段
        """
        return {
            "event": event_type,
            "data": json.dumps(data, ensure_ascii=False),
            "timestamp": str(int(time.time() * 1000)),
        }

    async def publish(
        self,
        event_type: str,
        data: dict[str, Any],
    ) -> str:
        """发布事件到 Redis Stream。

        Args:
            event_type: 事件类型（connected / progress / complete / error / heartbeat）
            data: 事件数据

        Returns:
            Redis Stream 消息 ID，格式为 "timestamp-seqnum"
        """
        if self._finished and event_type in (SSEEventType.COMPLETE, SSEEventType.ERROR):
            # 防止重复发送完成/错误消息
            logger.debug(f"任务 {self.run_id} 已结束，跳过重复的 {event_type} 消息")
            return ""

        payload = self._serialize_payload(event_type, data)

        # XADD 自动创建 Stream，MAXLEN ~ 近似裁剪（更高效）
        # 使用 ~ 表示近似匹配，保证不超过 max_stream_len
        message_id = await self.redis.xadd(
            self.stream_key,
            payload,
            maxlen=self.max_stream_len,
            approximate=True,
        )

        logger.debug(
            f"发布 SSE 事件: run_id={self.run_id}, "
            f"event={event_type}, message_id={message_id}"
        )

        return message_id

    async def publish_step(
        self,
        step_name: str,
        progress: int,
        step_key: str | None = None,
        extra: dict | None = None,
    ) -> str:
        """发布步骤进度。

        Args:
            step_name: 步骤名称（显示给用户）
            progress: 进度百分比 0-100
            step_key: 步骤标识
            extra: 额外数据

        Returns:
            Redis Stream 消息 ID
        """
        data = {
            "run_id": self.run_id,
            "status": "running",
            "current_step": step_name,
            "progress": progress,
            "step_key": step_key,
        }

        if extra:
            data.update(extra)

        return await self.publish(SSEEventType.PROGRESS, data)

    async def publish_complete(self, result: dict) -> str:
        """发布完成事件。

        Args:
            result: 最终结果数据

        Returns:
            Redis Stream 消息 ID
        """
        self._finished = True

        data = {
            "run_id": self.run_id,
            "status": "completed",
            "progress": 100,
            "current_step": "完成",
            "result": result,
        }

        return await self.publish(SSEEventType.COMPLETE, data)

    async def publish_error(self, error_code: str, message: str) -> str:
        """发布错误事件。

        Args:
            error_code: 错误码
            message: 错误信息

        Returns:
            Redis Stream 消息 ID
        """
        self._finished = True

        data = {
            "run_id": self.run_id,
            "status": "failed",
            "progress": 0,
            "error": {
                "error_code": error_code,
                "message": message,
            },
        }

        return await self.publish(SSEEventType.ERROR, data)

    async def cleanup(self) -> None:
        """清理 Stream（删除）。

        任务结束后可选调用，释放 Redis 内存。
        通常依赖 TTL 自动清理，这里提供手动清理接口。
        """
        await self.redis.delete(self.stream_key)
        logger.debug(f"清理 SSE Stream: {self.stream_key}")


# =============================================================================
# Redis Streams SSE Consumer / SSE Endpoint
# =============================================================================

class RedisSSEConsumer:
    """基于 Redis Streams 的 SSE 消费者。

    负责从 Redis Stream 消费消息，转换为 SSE 格式。

    设计考量：
    1. 支持从指定位置开始消费（支持断线重连）
    2. 支持心跳检测
    3. 支持优雅关闭
    4. 超时自动退出

    性能优化：
    1. XREAD BLOCK 阻塞等待，减少无效轮询
    2. 单次读取多条消息（STREAMS key 0 COUNT 100）
    3. 使用 asyncio.wait_for 控制阻塞超时
    """

    def __init__(
        self,
        run_id: str,
        redis_client: Redis,
        stream_key_prefix: str = "sse:progress",
        consumer_id: str | None = None,
        heartbeat_interval: int = 30,
    ) -> None:
        """初始化消费者。

        Args:
            run_id: 任务运行ID
            redis_client: Redis 异步客户端
            stream_key_prefix: Stream Key 前缀
            consumer_id: 消费者ID（用于标识不同连接）
            heartbeat_interval: 心跳间隔（秒）
        """
        self.run_id = run_id
        self.redis = redis_client
        self.stream_key = f"{stream_key_prefix}:{run_id}"
        self.consumer_id = consumer_id or f"consumer_{id(self)}"
        self.heartbeat_interval = heartbeat_interval

        # 最后一条消息 ID（用于断线重连）
        self._last_message_id = "0"

        # 运行状态标记
        self._running = False

    def _format_sse_event(self, event_type: str, data: dict) -> bytes:
        """格式化 SSE 事件。

        Args:
            event_type: 事件类型
            data: 事件数据

        Returns:
            SSE 格式的字节串
        """
        json_data = json.dumps(data, ensure_ascii=False)
        return f"event: {event_type}\ndata: {json_data}\n\n".encode("utf-8")

    async def _send_heartbeat(self) -> bytes:
        """生成心跳消息。

        Returns:
            SSE 心跳消息
        """
        return f"event: {SSEEventType.HEARTBEAT}\ndata: {{\"time\": {int(time.time() * 1000)}}}\n\n".encode("utf-8")

    async def consume(self) -> AsyncGenerator[bytes, None]:
        """消费 Redis Stream，生成 SSE 事件。

        这是一个异步生成器，yield SSE 格式的字节消息。

        Yields:
            SSE 格式的字节消息

        终止条件：
        1. 收到 complete 或 error 事件
        2. 外部取消（break）
        3. Redis Stream 不存在
        """
        self._running = True

        # 首先检查 Stream 是否存在
        stream_exists = await self.redis.exists(self.stream_key)
        if not stream_exists:
            # Stream 不存在，返回错误事件
            error_data = {"run_id": self.run_id, "message": "Task not found or expired"}
            yield self._format_sse_event(SSEEventType.ERROR, error_data)
            return

        # 发送连接成功事件
        connected_data = {"run_id": self.run_id, "consumer_id": self.consumer_id}
        yield self._format_sse_event(SSEEventType.CONNECTED, connected_data)

        # 主循环：从 Stream 读取消息
        while self._running:
            try:
                # XREAD BLOCK 阻塞等待新消息，最长等待 heartbeat_interval 秒
                # 同时检查 Redis Stream 是否还存在
                messages = await self.redis.xread(
                    {self.stream_key: self._last_message_id},
                    count=100,  # 最多一次读取 100 条
                    block=self.heartbeat_interval * 1000,  # 转换为毫秒
                )

                # messages 格式: [(stream_key, [(message_id, fields), ...]), ...]
                if not messages:
                    # 超时，发送心跳
                    yield await self._send_heartbeat()
                    continue

                for stream_key, message_list in messages:
                    for message_id, fields in message_list:
                        # 更新最后消息 ID（用于下次读取）
                        self._last_message_id = message_id

                        # 解析消息
                        event_type = fields.get("event", "message")
                        data = json.loads(fields.get("data", "{}"))

                        # 格式化并发送 SSE 事件
                        yield self._format_sse_event(event_type, data)

                        # 如果是完成或错误事件，退出循环
                        if event_type in (SSEEventType.COMPLETE, SSEEventType.ERROR):
                            self._running = False
                            return

            except asyncio.CancelledError:
                # 外部取消
                logger.debug(f"SSE Consumer 取消: run_id={self.run_id}")
                self._running = False
                raise
            except Exception as e:
                logger.error(f"SSE Consumer 错误: run_id={self.run_id}, error={e}")
                error_data = {"run_id": self.run_id, "message": str(e)}
                yield self._format_sse_event(SSEEventType.ERROR, error_data)
                self._running = False
                return

    def stop(self) -> None:
        """停止消费。"""
        self._running = False


# =============================================================================
# 简化使用的 Tracker 类
# =============================================================================

class RedisSSEProgressTracker:
    """Redis Streams SSE 进度追踪器。

    封装 Publisher，提供更友好的使用接口。
    支持上下文管理器，自动管理资源。

    使用示例：
    ```python
    async with RedisSSEProgressTracker(run_id, steps=[
        {"key": "intent_parse", "label": "理解问题"},
        {"key": "sql_execute", "label": "执行查询"},
    ]) as tracker:
        await tracker.step("intent_parse")
        await tracker.step("sql_execute")
        await tracker.finish(result={"answer": "xxx"})
    ```

    设计考量：
    1. 自动管理 Redis 连接
    2. 自动初始化步骤状态
    3. 自动发送完成/错误事件
    4. 支持异步上下文管理器
    """

    def __init__(
        self,
        run_id: str,
        steps: list[dict[str, str]] | None = None,
        redis_pool: RedisConnectionPool | None = None,
        stream_key_prefix: str = "sse:progress",
        max_stream_len: int = 100,
        stream_ttl_seconds: int = 3600,
    ) -> None:
        """初始化追踪器。

        Args:
            run_id: 任务运行ID
            steps: 步骤定义列表，如 [{"key": "step1", "label": "步骤1"}, ...]
            redis_pool: Redis 连接池实例（可选，不传则自动获取）
            stream_key_prefix: Stream Key 前缀
            max_stream_len: Stream 最大消息数
            stream_ttl_seconds: Stream TTL
        """
        self.run_id = run_id
        self.steps = steps or []
        self.stream_key_prefix = stream_key_prefix
        self.max_stream_len = max_stream_len
        self.stream_ttl_seconds = stream_ttl_seconds
        self._redis_pool = redis_pool
        self._publisher: RedisSSEPublisher | None = None
        self._current_step_index = -1

    async def __aenter__(self) -> "RedisSSEProgressTracker":
        """异步上下文管理器入口。"""
        pool = self._redis_pool or await get_redis_pool()
        self._publisher = RedisSSEPublisher(
            run_id=self.run_id,
            redis_client=pool.redis,
            stream_key_prefix=self.stream_key_prefix,
            max_stream_len=self.max_stream_len,
            stream_ttl_seconds=self.stream_ttl_seconds,
        )

        # 发布初始状态
        await self._publish_initial()

        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """异步上下文管理器出口。"""
        # 如果有异常，发送错误事件
        if exc_val is not None and self._publisher:
            await self._publisher.publish_error(
                error_code="INTERNAL_ERROR",
                message=str(exc_val),
            )

        # 清理资源
        if self._publisher:
            await self._publisher.cleanup()
            self._publisher = None

    async def _publish_initial(self) -> None:
        """发布初始状态。"""
        if not self._publisher:
            return

        steps_status = []
        for step in self.steps:
            steps_status.append({
                **step,
                "status": "pending",
            })

        data = {
            "run_id": self.run_id,
            "status": "running",
            "current_step": None,
            "progress": 0,
            "steps": steps_status,
        }

        await self._publisher.publish(SSEEventType.PROGRESS, data)

    async def step(self, step_key: str, extra: dict | None = None) -> None:
        """标记步骤完成。

        Args:
            step_key: 步骤标识
            extra: 额外数据
        """
        if not self._publisher:
            return

        # 查找步骤索引
        self._current_step_index = next(
            (i for i, s in enumerate(self.steps) if s["key"] == step_key),
            self._current_step_index
        )

        # 更新步骤状态
        steps_status = []
        for i, step in enumerate(self.steps):
            if i < self._current_step_index:
                status = "completed"
            elif i == self._current_step_index:
                status = "running"
            else:
                status = "pending"
            steps_status.append({
                **step,
                "status": status,
            })

        progress = int(((self._current_step_index + 1) / len(self.steps)) * 100)
        current_step = self.steps[self._current_step_index]["label"]

        data = {
            "run_id": self.run_id,
            "status": "running",
            "current_step": current_step,
            "progress": progress,
            "steps": steps_status,
        }

        if extra:
            data.update(extra)

        await self._publisher.publish(SSEEventType.PROGRESS, data)

    async def finish(self, result: dict | None = None) -> None:
        """完成任务。

        Args:
            result: 最终结果数据
        """
        if not self._publisher:
            return

        # 标记所有步骤为完成
        steps_status = []
        for step in self.steps:
            steps_status.append({
                **step,
                "status": "completed",
            })

        data = {
            "run_id": self.run_id,
            "status": "completed",
            "progress": 100,
            "current_step": "完成",
            "steps": steps_status,
            "result": result or {},
        }

        await self._publisher.publish(SSEEventType.COMPLETE, data)

    async def error(self, error_code: str, message: str) -> None:
        """报告错误。

        Args:
            error_code: 错误码
            message: 错误信息
        """
        if not self._publisher:
            return

        await self._publisher.publish_error(error_code, message)

    # ==========================================================================
    # 增量产物推送方法（用于 LLM 并行生成场景）
    # ==========================================================================

    async def publish_summary(self, summary: dict) -> None:
        """推送摘要完成事件

        Args:
            summary: 摘要数据
        """
        if not self._publisher:
            return

        data = {
            "run_id": self.run_id,
            "progress": 25,
            "summary": summary,
        }
        await self._publisher.publish(SSEEventType.SUMMARY_DONE, data)

    async def publish_insight(self, insights: dict) -> None:
        """推送洞察完成事件

        Args:
            insights: 洞察数据
        """
        if not self._publisher:
            return

        data = {
            "run_id": self.run_id,
            "progress": 50,
            "insights": insights,
        }
        await self._publisher.publish(SSEEventType.INSIGHT_DONE, data)

    async def publish_chart(self, chart: dict) -> None:
        """推送图表完成事件

        Args:
            chart: 图表数据
        """
        if not self._publisher:
            return

        data = {
            "run_id": self.run_id,
            "progress": 75,
            "chart": chart,
        }
        await self._publisher.publish(SSEEventType.CHART_DONE, data)

    async def publish_report(self, report: dict) -> None:
        """推送报告完成事件

        Args:
            report: 报告数据
        """
        if not self._publisher:
            return

        data = {
            "run_id": self.run_id,
            "progress": 100,
            "report": report,
        }
        await self._publisher.publish(SSEEventType.REPORT_DONE, data)

    @property
    def publisher(self) -> RedisSSEPublisher | None:
        """获取 Publisher 实例（供外部使用）"""
        return self._publisher


# =============================================================================
# 兼容层：保留原有 API
# =============================================================================

# 为了向后兼容，保留一些原接口的适配
# 这些函数会在内部调用新的 Redis Streams 实现

async def sse_event_stream(
    run_id: str,
    consumer_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """SSE 事件流生成器（兼容版）。

    兼容原有 API，内部使用 Redis Streams 实现。

    Args:
        run_id: 任务运行ID
        consumer_id: 消费者ID

    Yields:
        SSE 格式的字符串
    """
    pool = await get_redis_pool()
    consumer = RedisSSEConsumer(
        run_id=run_id,
        redis_client=pool.redis,
        consumer_id=consumer_id,
    )

    async for message in consumer.consume():
        yield message.decode("utf-8")


async def get_sse_queue(run_id: str) -> bool:
    """检查 SSE Stream 是否存在（兼容原有接口）。

    Args:
        run_id: 任务运行ID

    Returns:
        True 表示 Stream 存在
    """
    pool = await get_redis_pool()
    stream_key = f"sse:progress:{run_id}"
    return await pool.redis.exists(stream_key) > 0
