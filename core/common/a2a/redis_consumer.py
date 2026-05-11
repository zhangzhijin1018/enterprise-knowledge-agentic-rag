"""A2A Redis Streams 消息消费者。

从 Redis Streams 消费任务，实现 Agent 的异步处理。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import TYPE_CHECKING, Any, Callable

import redis

from core.config.settings import get_settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class A2ARedisConsumer:
    """A2A Redis Streams 消息消费者。

    职责：
    - 从 Redis Streams 消费任务
    - 调用目标 Agent 处理
    - 更新任务状态
    - 支持消费组实现多 Worker 并行

    设计原因：
    - 消费组（Consumer Group）支持多 Worker 并行消费
    - 支持消息确认（XACK），确保消息被处理
    - 支持 Pending 消息重新投递
    - 支持消息追踪和死信处理
    """

    def __init__(
        self,
        redis_url: str | None = None,
        stream_prefix: str | None = None,
        consumer_group_prefix: str | None = None,
    ) -> None:
        """初始化 A2A Redis 消费者。

        Args:
            redis_url: Redis 连接 URL
            stream_prefix: Stream 键前缀
            consumer_group_prefix: 消费组前缀
        """

        settings = get_settings()
        self.redis_url = redis_url or settings.redis_url
        self.stream_prefix = stream_prefix or settings.redis_sse_stream_prefix
        self.consumer_group_prefix = consumer_group_prefix or "cg"

        self._client: redis.Redis | None = None
        self._running: bool = False

    @property
    def client(self) -> redis.Redis:
        """懒加载 Redis 客户端。"""
        if self._client is None:
            self._client = redis.from_url(
                self.redis_url,
                decode_responses=True,
            )
        return self._client

    def start_consuming(
        self,
        agent_name: str,
        handler: Callable[[dict], dict],
        block_ms: int = 5000,
        max_retries: int = 3,
    ) -> None:
        """开始消费任务。

        Args:
            agent_name: Agent 名称
            handler: 处理函数，接收 task_envelope，返回 result
            block_ms: 阻塞等待时间（毫秒）
            max_retries: 最大重试次数
        """
        stream_key = self._get_stream_key(agent_name)
        consumer_group = self._get_consumer_group(agent_name)
        consumer_name = f"{agent_name}_consumer_{os.getpid()}"

        logger.info(
            f"[A2A Consumer] 开始消费 | agent={agent_name} | "
            f"group={consumer_group} | consumer={consumer_name}"
        )

        # 确保消费组存在
        self._ensure_consumer_group(stream_key, consumer_group)

        self._running = True

        while self._running:
            try:
                # 阻塞读取新消息
                messages = self.client.xreadgroup(
                    consumer_group,
                    consumer_name,
                    {stream_key: ">"},  # 只读未处理的新消息
                    count=1,
                    block=block_ms,
                )

                if not messages:
                    continue

                for stream, msg_list in messages:
                    for message_id, data in msg_list:
                        self._process_message(
                            message_id=message_id,
                            data=data,
                            stream_key=stream_key,
                            consumer_group=consumer_group,
                            handler=handler,
                            max_retries=max_retries,
                        )

            except redis.ConnectionError as e:
                logger.error(f"[A2A Consumer] Redis 连接错误: {e}")
                time.sleep(5)  # 等待重连

            except Exception as e:
                logger.error(f"[A2A Consumer] 消费循环异常: {e}", exc_info=True)
                time.sleep(1)

    def _process_message(
        self,
        message_id: str,
        data: dict,
        stream_key: str,
        consumer_group: str,
        handler: Callable[[dict], dict],
        max_retries: int,
    ) -> None:
        """处理单条消息。

        Args:
            message_id: 消息 ID
            data: 消息数据
            stream_key: Stream 键
            consumer_group: 消费组
            handler: 处理函数
            max_retries: 最大重试次数
        """
        task_envelope = json.loads(data.get("task_envelope", "{}"))
        task_id = task_envelope.get("task_id", message_id)

        logger.info(f"[A2A Consumer] 处理任务: {task_id}")

        try:
            # 调用处理函数
            start_time = time.time()
            result = handler(task_envelope)
            elapsed_ms = int((time.time() - start_time) * 1000)

            # 更新状态为完成
            self._update_task_completed(
                stream_key=stream_key,
                original_message_id=message_id,
                result=result,
                elapsed_ms=elapsed_ms,
            )

            # 确认消息
            self.client.xack(stream_key, consumer_group, message_id)

            logger.info(
                f"[A2A Consumer] 任务完成: {task_id} | 耗时: {elapsed_ms}ms"
            )

        except Exception as e:
            logger.error(f"[A2A Consumer] 任务处理失败: {task_id} | 错误: {e}")

            # 更新状态为失败
            self._update_task_failed(
                stream_key=stream_key,
                original_message_id=message_id,
                error=str(e),
            )

            # 确认消息（避免无限重试）
            self.client.xack(stream_key, consumer_group, message_id)

    def _ensure_consumer_group(self, stream_key: str, consumer_group: str) -> None:
        """确保消费组存在。

        Args:
            stream_key: Stream 键
            consumer_group: 消费组名
        """
        try:
            self.client.xgroup_create(
                stream_key,
                consumer_group,
                id="0",  # 从头开始消费
                mkstream=True,  # Stream 不存在时创建
            )
            logger.info(f"[A2A Consumer] 创建消费组: {consumer_group}")
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                # 消费组已存在
                pass
            else:
                raise

    def _update_task_completed(
        self,
        stream_key: str,
        original_message_id: str,
        result: dict,
        elapsed_ms: int,
    ) -> None:
        """更新任务为完成状态。

        Args:
            stream_key: Stream 键
            original_message_id: 原消息 ID
            result: 处理结果
            elapsed_ms: 处理耗时
        """
        message = {
            "original_message_id": original_message_id,
            "status": "completed",
            "result": json.dumps(result, ensure_ascii=False),
            "elapsed_ms": str(elapsed_ms),
            "completed_at": self._get_timestamp(),
        }

        self.client.xadd(stream_key, message)

    def _update_task_failed(
        self,
        stream_key: str,
        original_message_id: str,
        error: str,
    ) -> None:
        """更新任务为失败状态。

        Args:
            stream_key: Stream 键
            original_message_id: 原消息 ID
            error: 错误信息
        """
        message = {
            "original_message_id": original_message_id,
            "status": "failed",
            "error": error,
            "failed_at": self._get_timestamp(),
        }

        self.client.xadd(stream_key, message)

    def _get_stream_key(self, agent_name: str) -> str:
        """获取 Stream 键名。"""
        return f"{self.stream_prefix}:{agent_name}"

    def _get_consumer_group(self, agent_name: str) -> str:
        """获取消费组名。"""
        return f"{self.consumer_group_prefix}:{agent_name}"

    def _get_timestamp(self) -> str:
        """获取当前时间戳。"""
        from datetime import datetime
        return datetime.utcnow().isoformat()

    def stop_consuming(self) -> None:
        """停止消费。"""
        logger.info("[A2A Consumer] 停止消费")
        self._running = False

    def get_pending_messages(
        self,
        agent_name: str,
        count: int = 10,
    ) -> list[dict]:
        """获取 Pending 消息（未确认的消息）。

        Args:
            agent_name: Agent 名称
            count: 返回数量

        Returns:
            Pending 消息列表
        """
        stream_key = self._get_stream_key(agent_name)
        consumer_group = self._get_consumer_group(agent_name)

        try:
            # 获取消费组的 Pending 信息
            pending_info = self.client.xpending(stream_key, consumer_group)

            if not pending_info or not pending_info["pending"]:
                return []

            # 获取 Pending 消息详情
            messages = self.client.xrange(
                stream_key,
                min="-",
                max="+",
                count=count,
            )

            # 过滤出属于当前消费组的 Pending 消息
            pending_messages = []
            for msg_id, data in messages:
                # 检查是否是 Pending 消息
                # 这里简化处理，实际应查询 XPENDING
                if data.get("status") == "pending":
                    pending_messages.append({
                        "message_id": msg_id,
                        "task_envelope": json.loads(data.get("task_envelope", "{}")),
                        "created_at": data.get("created_at"),
                    })

            return pending_messages[:count]

        except redis.ResponseError as e:
            logger.warning(f"获取 Pending 消息失败: {e}")
            return []

    def retry_pending_messages(
        self,
        agent_name: str,
        min_idle_time_ms: int = 60000,
    ) -> int:
        """重试 Pending 消息。

        Args:
            agent_name: Agent 名称
            min_idle_time_ms: 最小空闲时间（毫秒）

        Returns:
            重试的消息数量
        """
        stream_key = self._get_stream_key(agent_name)
        consumer_group = self._get_consumer_group(agent_name)

        try:
            # claim 命令重试超过 min_idle_time_ms 未处理的消息
            messages = self.client.xautoclaim(
                stream_key,
                consumer_group,
                consumer_name=f"{agent_name}_retry",
                min_idle_time=min_idle_time_ms,
                start_id="0-0",
                count=10,
            )

            if messages and len(messages) >= 2:
                next_start_id = messages[0]
                messages = messages[1] if len(messages) > 1 else []

                count = 0
                for msg_id, data in messages:
                    # 重新发送消息
                    self.client.xadd(stream_key, data)
                    # 删除原消息
                    self.client.xdel(stream_key, msg_id)
                    count += 1

                logger.info(f"[A2A Consumer] 重试了 {count} 条 Pending 消息")
                return count

        except Exception as e:
            logger.error(f"重试 Pending 消息失败: {e}")

        return 0

    def close(self) -> None:
        """关闭连接。"""
        self.stop_consuming()
        if self._client:
            self._client.close()
            self._client = None
