"""A2A 消息总线模块包。

提供基于 Redis Streams 的 A2A 消息传递功能。
"""

from core.common.a2a.redis_producer import A2ARedisProducer
from core.common.a2a.redis_consumer import A2ARedisConsumer

__all__ = [
    "A2ARedisProducer",
    "A2ARedisConsumer",
]
