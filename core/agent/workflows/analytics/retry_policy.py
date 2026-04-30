"""经营分析 Workflow 节点级重试策略。

这一层的目标不是引入复杂通用重试框架，而是把当前经营分析 workflow
最需要的节点级策略收口清楚：

1. 哪些节点允许重试；
2. 哪些错误可以重试；
3. 哪些错误绝对不能通过重试绕过。

关键原则：
1. `SQL Guard blocked` 不能重试，因为这是治理拒绝，不是瞬时异常；
2. 指标权限 / 数据源权限失败不能重试，因为这是权限边界，不是连接抖动；
3. SQL Gateway 的超时、连接错误、临时执行异常可以做有限重试；
4. 重试只记录轻量摘要，不把完整异常堆栈写进 output_snapshot。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from core.common import error_codes
from core.common.exceptions import AppException
from core.tools.mcp import SQLGatewayExecutionError


@dataclass(slots=True)
class RetryPolicy:
    """节点级重试策略。

    字段说明：
    - `node_name`：当前策略服务哪个 workflow 节点；
    - `max_attempts`：最多尝试次数，包含第一次执行；
    - `backoff_ms`：每次失败后的固定退避时间；
    - `retryable_errors`：允许重试的异常类型集合。
    """

    node_name: str
    max_attempts: int
    backoff_ms: int
    retryable_errors: tuple[type[BaseException], ...]


class AnalyticsWorkflowRetryController:
    """经营分析 workflow 轻量重试控制器。"""

    _DEFAULT_POLICIES = {
        "analytics_build_sql": RetryPolicy(
            node_name="analytics_build_sql",
            max_attempts=2,
            backoff_ms=20,
            retryable_errors=(RuntimeError,),
        ),
        "analytics_execute_sql": RetryPolicy(
            node_name="analytics_execute_sql",
            max_attempts=2,
            backoff_ms=50,
            retryable_errors=(SQLGatewayExecutionError, TimeoutError, ConnectionError),
        ),
        "analytics_summarize": RetryPolicy(
            node_name="analytics_summarize",
            max_attempts=2,
            backoff_ms=20,
            retryable_errors=(RuntimeError,),
        ),
    }

    def get_policy(self, node_name: str) -> RetryPolicy | None:
        """读取节点对应的默认重试策略。"""

        return self._DEFAULT_POLICIES.get(node_name)

    def run(
        self,
        *,
        node_name: str,
        state: dict[str, Any],
        action: Callable[[], Any],
    ) -> Any:
        """在节点内部执行带重试的动作。

        说明：
        - 这里只负责“有限次重试 + 轻量摘要记录”；
        - 如果错误不允许重试，立即原样抛出；
        - 如果重试耗尽，则把最后一次异常抛给上层状态机。
        """

        policy = self.get_policy(node_name)
        if policy is None:
            return action()

        last_exc: BaseException | None = None
        for attempt in range(1, policy.max_attempts + 1):
            try:
                return action()
            except Exception as exc:  # noqa: PERF203 - 这里刻意按节点重试策略分流
                last_exc = exc
                if not self._is_retryable(exc=exc, policy=policy):
                    raise

                self._record_retry(
                    state=state,
                    node_name=node_name,
                    attempt=attempt,
                    exc=exc,
                )
                if attempt >= policy.max_attempts:
                    raise
                time.sleep(policy.backoff_ms / 1000)

        if last_exc is not None:  # pragma: no cover - 理论上不会走到这里
            raise last_exc
        return action()

    def _is_retryable(self, *, exc: BaseException, policy: RetryPolicy) -> bool:
        """判断异常是否允许重试。

        为什么要先挡掉 AppException：
        - `SQL_GUARD_BLOCKED`、权限失败、数据范围失败都属于治理或权限边界；
        - 这些错误如果允许重试，等于试图用“多试几次”绕过规则层，这是不允许的。
        """

        if isinstance(exc, AppException):
            return exc.error_code not in {
                error_codes.SQL_GUARD_BLOCKED,
                error_codes.ANALYTICS_METRIC_PERMISSION_DENIED,
                error_codes.ANALYTICS_DATA_SOURCE_PERMISSION_DENIED,
                error_codes.ANALYTICS_DATA_SCOPE_DENIED,
                error_codes.PERMISSION_DENIED,
            } and isinstance(exc, policy.retryable_errors)
        return isinstance(exc, policy.retryable_errors)

    def _record_retry(
        self,
        *,
        state: dict[str, Any],
        node_name: str,
        attempt: int,
        exc: BaseException,
    ) -> None:
        """记录轻量重试摘要。"""

        state.setdefault("retry_history", [])
        state["retry_history"].append(
            {
                "node_name": node_name,
                "attempt": attempt,
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
            }
        )
        state["retry_count"] = int(state.get("retry_count", 0)) + 1
