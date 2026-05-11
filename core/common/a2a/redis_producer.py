"""A2A Redis Streams 消息生产者。

将 TaskEnvelope 发送到 Redis Streams，实现跨 Agent 的异步消息传递。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

import redis

from core.config.settings import get_settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class A2ARedisProducer:
    """A2A Redis Streams 消息生产者。

    职责：
    - 将 TaskEnvelope 发送到 Redis Streams
    - 管理消息的生命周期
    - 提供消息状态查询

    设计原因：
    - Redis Streams 是 Redis 5.0+ 引入的持久化消息队列
    - 支持消费组，实现多 Worker 并行消费
    - 消息持久化，支持重复消费
    - 比 Redis Pub/Sub 更适合需要持久化的场景
    - 支持消息追踪和死信队列
    """

    def __init__(
        self,
        redis_url: str | None = None,
        stream_prefix: str | None = None,
    ) -> None:
        """初始化 A2A Redis 生产者。

        Args:
            redis_url: Redis 连接 URL
            stream_prefix: Stream 键前缀
        """

        settings = get_settings()
        self.redis_url = redis_url or settings.redis_url
        self.stream_prefix = stream_prefix or settings.redis_sse_stream_prefix

        self._client: redis.Redis | None = None

    @property
    def client(self) -> redis.Redis:
        """懒加载 Redis 客户端。"""
        if self._client is None:
            self._client = redis.from_url(
                self.redis_url,
                decode_responses=True,
            )
        return self._client

    def send_task(
        self,
        task_envelope: dict,
        target_agent: str,
        priority: int = 0,
    ) -> str:
        """发送任务到 Redis Streams。

        Args:
            task_envelope: 任务信封
            target_agent: 目标 Agent 名称
            priority: 优先级（0=普通, 1=高, 2=紧急）

        Returns:
            消息 ID
        """
        stream_key = self._get_stream_key(target_agent)

        # 构建消息
        message = {
            "task_envelope": json.dumps(task_envelope, ensure_ascii=False),
            "created_at": datetime.utcnow().isoformat(),
            "status": "pending",
            "priority": str(priority),
        }

        # 发送消息
        if priority > 0:
            # 高优先级消息使用 XADD with MAXLEN
            message_id = self.client.xadd(
                stream_key,
                message,
                maxlen=10000,
            )
        else:
            message_id = self.client.xadd(stream_key, message)

        logger.info(
            f"[A2A Producer] 任务已发送到 {stream_key}，消息 ID: {message_id}"
        )

        return message_id

    def send_task_batch(
        self,
        tasks: list[tuple[dict, str]],
    ) -> list[str]:
        """批量发送任务。

        Args:
            tasks: (task_envelope, target_agent) 元组列表

        Returns:
            消息 ID 列表
        """
        message_ids = []

        pipe = self.client.pipeline()
        for task_envelope, target_agent in tasks:
            stream_key = self._get_stream_key(target_agent)
            message = {
                "task_envelope": json.dumps(task_envelope, ensure_ascii=False),
                "created_at": datetime.utcnow().isoformat(),
                "status": "pending",
                "priority": "0",
            }
            pipe.xadd(stream_key, message)

        results = pipe.execute()
        message_ids.extend(results)

        logger.info(f"[A2A Producer] 批量发送 {len(message_ids)} 个任务")

        return message_ids

    def get_task_status(
        self,
        target_agent: str,
        message_id: str,
    ) -> dict | None:
        """查询任务状态。

        Args:
            target_agent: 目标 Agent
            message_id: 消息 ID

        Returns:
            任务状态信息
        """
        stream_key = self._get_stream_key(target_agent)

        result = self.client.xrange(stream_key, min=message_id, max=message_id)

        if result:
            _, data = result[0]
            return {
                "message_id": message_id,
                "status": data.get("status"),
                "created_at": data.get("created_at"),
                "priority": data.get("priority"),
            }

        return None

    def get_pending_tasks(
        self,
        target_agent: str,
        count: int = 10,
    ) -> list[dict]:
        """获取待处理任务。

        Args:
            target_agent: 目标 Agent
            count: 返回数量

        Returns:
            待处理任务列表
        """
        stream_key = self._get_stream_key(target_agent)

        results = self.client.xrange(
            stream_key,
            min="0-0",
            max="+",
            count=count,
        )

        tasks = []
        for message_id, data in results:
            if data.get("status") == "pending":
                tasks.append({
                    "message_id": message_id,
                    "task_envelope": json.loads(data.get("task_envelope", "{}")),
                    "created_at": data.get("created_at"),
                    "priority": int(data.get("priority", "0")),
                })

        return tasks

    def update_task_status(
        self,
        target_agent: str,
        message_id: str,
        status: str,
        result: dict | None = None,
    ) -> bool:
        """更新任务状态。

        Args:
            target_agent: 目标 Agent
            message_id: 消息 ID
            status: 新状态
            result: 任务结果

        Returns:
            是否成功
        """
        stream_key = self._get_stream_key(target_agent)

        # 创建一个新消息记录状态
        message = {
            "original_message_id": message_id,
            "status": status,
            "updated_at": datetime.utcnow().isoformat(),
        }

        if result:
            message["result"] = json.dumps(result, ensure_ascii=False)

        try:
            self.client.xadd(stream_key, message)
            return True
        except Exception as e:
            logger.error(f"更新任务状态失败: {e}")
            return False

    def get_stream_info(self, target_agent: str) -> dict:
        """获取 Stream 信息。

        Args:
            target_agent: 目标 Agent

        Returns:
            Stream 信息
        """
        stream_key = self._get_stream_key(target_agent)

        try:
            info = self.client.xinfo_stream(stream_key)
            return {
                "length": info.get("length", 0),
                "first_entry": info.get("first-entry"),
                "last_entry": info.get("last-entry"),
            }
        except redis.ResponseError:
            # Stream 不存在
            return {"length": 0, "first_entry": None, "last_entry": None}

    def _get_stream_key(self, target_agent: str) -> str:
        """获取 Stream 键名。

        Args:
            target_agent: Agent 名称

        Returns:
            Stream 键名
        """
        return f"{self.stream_prefix}:{target_agent}"

    def close(self) -> None:
        """关闭连接。"""
        if self._client:
            self._client.close()
            self._client = None
