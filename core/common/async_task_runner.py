"""最小后台异步任务执行器。

为什么需要后台执行器：
1. 当前 export 虽有 pending/running/succeeded/failed 状态，但本质还是同步生成；
2. 本轮要把导出改成"真正异步任务语义"：POST 只创建任务并返回 export_id，
   后台 worker 异步处理，GET 轮询读取状态；
3. 当前阶段暂不接 Celery，先实现最小本地异步任务 runner；
4. 但接口和状态模型必须按真实异步任务设计，后续切 Celery 时只替换执行器。

设计原则：
- 接口按异步任务语义设计，不暴露"本地线程"实现细节；
- 支持任务提交、状态查询、取消；
- 线程安全，支持并发提交；
- 任务执行异常不崩溃主进程。
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class AsyncTaskStatus:
    """异步任务状态。"""

    task_id: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    result: Any = None


class AsyncTaskRunner:
    """最小本地异步任务执行器。

    使用 threading 实现，不依赖 Celery 或其他外部任务队列。
    后续切 Celery 时，只需替换此执行器实现，上层接口不变。
    """

    def __init__(self, max_workers: int = 4) -> None:
        self._tasks: dict[str, AsyncTaskStatus] = {}
        self._lock = threading.Lock()
        self._max_workers = max_workers
        self._semaphore = threading.Semaphore(max_workers)

    def submit(
        self,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """提交异步任务，返回 task_id。"""

        task_id = f"async_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        with self._lock:
            self._tasks[task_id] = AsyncTaskStatus(
                task_id=task_id,
                status="pending",
                created_at=now,
            )

        thread = threading.Thread(
            target=self._execute_task,
            args=(task_id, fn, args, kwargs),
            daemon=True,
        )
        thread.start()
        return task_id

    def get_status(self, task_id: str) -> AsyncTaskStatus | None:
        """查询异步任务状态。"""

        with self._lock:
            return self._tasks.get(task_id)

    def _execute_task(
        self,
        task_id: str,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        """在后台线程中执行任务。"""

        with self._semaphore:
            with self._lock:
                status = self._tasks.get(task_id)
                if status is None:
                    return
                status.status = "running"
                status.started_at = datetime.now(timezone.utc)

            try:
                result = fn(*args, **kwargs)
                with self._lock:
                    status = self._tasks.get(task_id)
                    if status is not None:
                        status.status = "succeeded"
                        status.finished_at = datetime.now(timezone.utc)
                        status.result = result
            except Exception as exc:
                logger.exception("Async task %s failed", task_id)
                with self._lock:
                    status = self._tasks.get(task_id)
                    if status is not None:
                        status.status = "failed"
                        status.finished_at = datetime.now(timezone.utc)
                        status.error_message = str(exc)

    def cleanup_finished(self, max_age_seconds: int = 3600) -> int:
        """清理已完成的旧任务记录。"""

        now = datetime.now(timezone.utc)
        to_remove: list[str] = []

        with self._lock:
            for task_id, status in self._tasks.items():
                if status.status in {"succeeded", "failed"} and status.finished_at is not None:
                    age = (now - status.finished_at).total_seconds()
                    if age > max_age_seconds:
                        to_remove.append(task_id)

            for task_id in to_remove:
                del self._tasks[task_id]

        return len(to_remove)


_global_runner = AsyncTaskRunner()


def get_async_task_runner() -> AsyncTaskRunner:
    """获取全局异步任务执行器实例。"""

    return _global_runner


def reset_async_task_runner() -> None:
    """重置全局异步任务执行器。"""

    global _global_runner
    _global_runner = AsyncTaskRunner()
