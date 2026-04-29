"""进程内只读缓存模块。

为什么需要进程内缓存：
1. SchemaRegistry / MetricCatalog / DataSourceRegistry 等高频只读对象，
   每次请求都重新构造会导致不必要的 CPU 和内存开销；
2. 这些对象在进程生命周期内基本不变（metric 定义、表结构、数据源配置），
   适合做进程级常驻缓存；
3. 当前阶段不要求接 Redis，先把进程内只读缓存做好。

设计原则：
- 只缓存只读对象，不缓存业务运行态数据；
- 支持 TTL 过期，但默认不过期（进程生命周期内有效）；
- 支持手动 invalidate，用于配置变更时刷新；
- 线程安全。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    """缓存条目。"""

    value: T
    created_at: float
    ttl_seconds: float | None = None

    def is_expired(self) -> bool:
        """判断缓存条目是否已过期。"""

        if self.ttl_seconds is None:
            return False
        return (time.monotonic() - self.created_at) > self.ttl_seconds


class RegistryCache:
    """进程内只读对象缓存。

    适用场景：
    - metric definitions
    - data source definitions
    - table definitions
    - group_by rules
    - field whitelist / visible_fields / sensitive_fields

    不适用场景：
    - 业务运行态数据（task_run、export_task 等）
    - 需要跨进程共享的数据
    """

    def __init__(self) -> None:
        self._store: dict[str, CacheEntry[Any]] = {}
        self._lock = threading.Lock()

    def get_or_compute(
        self,
        key: str,
        compute_fn: Callable[[], T],
        ttl_seconds: float | None = None,
    ) -> T:
        """获取缓存值，不存在或过期时重新计算。"""

        with self._lock:
            entry = self._store.get(key)
            if entry is not None and not entry.is_expired():
                return entry.value

        value = compute_fn()

        with self._lock:
            self._store[key] = CacheEntry(
                value=value,
                created_at=time.monotonic(),
                ttl_seconds=ttl_seconds,
            )
        return value

    def invalidate(self, key: str) -> None:
        """手动失效指定缓存条目。"""

        with self._lock:
            self._store.pop(key, None)

    def invalidate_all(self) -> None:
        """手动失效全部缓存条目。"""

        with self._lock:
            self._store.clear()

    def has(self, key: str) -> bool:
        """判断缓存条目是否存在且未过期。"""

        with self._lock:
            entry = self._store.get(key)
            return entry is not None and not entry.is_expired()

    def size(self) -> int:
        """返回当前缓存条目数量。"""

        with self._lock:
            return len(self._store)


_global_cache = RegistryCache()


def get_global_cache() -> RegistryCache:
    """获取全局缓存实例。"""

    return _global_cache


def reset_global_cache() -> None:
    """重置全局缓存实例。"""

    global _global_cache
    _global_cache = RegistryCache()
