"""Trace 上下文管理模块。

该模块使用 Python contextvars 提供线程安全、异步安全的 Trace 上下文管理。

为什么用 contextvars？
---------------------
传统的 ThreadLocal 在异步场景下有问题：
- 同一个线程处理多个请求时，上下文会混淆
- async/await 切换时，ThreadLocal 无法正确传递

contextvars 是 Python 3.7+ 引入的，专为异步场景设计：
- 每个异步任务有独立的上下文
- 自动在 await 点传递上下文
- 线程安全和协程安全

使用示例：
    # 设置上下文
    set_trace_context(trace_id="tr_abc123", run_id="run_xyz789")

    # 在任何地方获取
    trace_id = get_trace_id()  # "tr_abc123"
    run_id = get_run_id()      # "run_xyz789"

    # 清除上下文（请求结束时）
    clear_trace_context()

设计原理：
---------
1. 每个请求入口生成 trace_id 和 run_id
2. 整个调用链共享同一个 trace_id
3. 每次 Agent 执行生成新的 run_id
4. 所有日志、追踪、审计自动带上上下文
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# ============================================================================
# Context Variables - 核心上下文变量
# ============================================================================

# Trace ID：串联整个请求链路
# 格式：tr_ + 16位十六进制字符串
_trace_id_var: ContextVar[str | None] = ContextVar(
    "trace_id",
    default=None
)

# Run ID：标识一次 Agent 执行
# 格式：run_ + 16位十六进制字符串
_run_id_var: ContextVar[str | None] = ContextVar(
    "run_id",
    default=None
)

# Conversation ID：会话标识
_conversation_id_var: ContextVar[str | None] = ContextVar(
    "conversation_id",
    default=None
)

# User ID：用户标识
_user_id_var: ContextVar[str | None] = ContextVar(
    "user_id",
    default=None
)


# ============================================================================
# 便捷函数
# ============================================================================

def generate_trace_id() -> str:
    """
    生成 Trace ID

    格式：tr_ + 16位十六进制字符串
    例如：tr_a1b2c3d4e5f60718

    Returns:
        格式化的 Trace ID
    """
    return f"tr_{uuid.uuid4().hex[:16]}"


def generate_run_id() -> str:
    """
    生成 Run ID

    格式：run_ + 16位十六进制字符串
    例如：run_f1e2d3c4b5a60789

    Returns:
        格式化的 Run ID
    """
    return f"run_{uuid.uuid4().hex[:16]}"


def generate_conversation_id() -> str:
    """
    生成 Conversation ID

    格式：conv_ + 16位十六进制字符串
    例如：conv_1234567890abcdef

    Returns:
        格式化的 Conversation ID
    """
    return f"conv_{uuid.uuid4().hex[:16]}"


# ============================================================================
# 上下文管理器
# ============================================================================

class TraceContext:
    """
    Trace 上下文管理器

    使用上下文管理器确保资源正确清理：
    - 自动设置 trace_id 和 run_id
    - 自动清除上下文
    - 支持嵌套上下文

    使用示例：
        async with TraceContext() as ctx:
            logger.info("Hello")  # 自动带上 trace_id
            await some_async_function()

        # 上下文自动清除

    设计原理：
    ---------
    1. __enter__：生成 trace_id/run_id，设置到 contextvars
    2. __exit__：清除 contextvars，释放资源
    3. 支持 with 和 async with 两种模式
    """

    def __init__(
        self,
        trace_id: str | None = None,
        run_id: str | None = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ):
        """
        初始化上下文管理器

        Args:
            trace_id: 可选，指定 trace_id，默认自动生成
            run_id: 可选，指定 run_id，默认自动生成
            conversation_id: 会话 ID
            user_id: 用户 ID
        """
        self.trace_id = trace_id or generate_trace_id()
        self.run_id = run_id or generate_run_id()
        self.conversation_id = conversation_id
        self.user_id = user_id

        # 保存旧的上下文（用于嵌套）
        self._old_trace_id: str | None = None
        self._old_run_id: str | None = None
        self._old_conversation_id: str | None = None
        self._old_user_id: str | None = None

    def __enter__(self) -> "TraceContext":
        """同步上下文入口"""
        # 保存旧的上下文
        self._old_trace_id = _trace_id_var.get()
        self._old_run_id = _run_id_var.get()
        self._old_conversation_id = _conversation_id_var.get()
        self._old_user_id = _user_id_var.get()

        # 设置新上下文
        _trace_id_var.set(self.trace_id)
        _run_id_var.set(self.run_id)
        _conversation_id_var.set(self.conversation_id)
        _user_id_var.set(self.user_id)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """同步上下文出口"""
        # 恢复旧上下文
        _trace_id_var.set(self._old_trace_id)
        _run_id_var.set(self._old_run_id)
        _conversation_id_var.set(self._old_conversation_id)
        _user_id_var.set(self._old_user_id)

    async def __aenter__(self) -> "TraceContext":
        """异步上下文入口"""
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文出口"""
        self.__exit__(exc_type, exc_val, exc_tb)


@dataclass
class RequestContext:
    """
    请求上下文数据类

    包含一次请求的所有上下文信息

    设计说明：
    --------
    1. 使用 dataclass 方便创建和序列化
    2. 包含时间戳，方便日志关联
    3. 所有字段可选，支持灵活创建
    """

    trace_id: str
    run_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    conversation_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None

    # 请求元信息
    request_id: str | None = None
    endpoint: str | None = None
    method: str | None = None

    # 用户代理信息
    user_agent: str | None = None
    ip_address: str | None = None

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "timestamp": self.timestamp.isoformat(),
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "endpoint": self.endpoint,
            "method": self.method,
        }


# ============================================================================
# 全局访问函数
# ============================================================================

def get_trace_id() -> str | None:
    """
    获取当前 Trace ID

    Returns:
        当前上下文的 trace_id，如果没有设置返回 None
    """
    return _trace_id_var.get()


def get_run_id() -> str | None:
    """
    获取当前 Run ID

    Returns:
        当前上下文的 run_id，如果没有设置返回 None
    """
    return _run_id_var.get()


def get_conversation_id() -> str | None:
    """
    获取当前 Conversation ID

    Returns:
        当前上下文的 conversation_id，如果没有设置返回 None
    """
    return _conversation_id_var.get()


def get_user_id() -> str | None:
    """
    获取当前 User ID

    Returns:
        当前上下文的 user_id，如果没有设置返回 None
    """
    return _user_id_var.get()


def set_trace_context(
    trace_id: str | None = None,
    run_id: str | None = None,
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> tuple[str, str]:
    """
    设置 Trace 上下文

    Args:
        trace_id: 可选，指定 trace_id
        run_id: 可选，指定 run_id
        conversation_id: 会话 ID
        user_id: 用户 ID

    Returns:
        (trace_id, run_id) 元组

    使用示例：
        trace_id, run_id = set_trace_context(
            trace_id="tr_abc123",
            user_id="user_001"
        )
    """
    actual_trace_id = trace_id or generate_trace_id()
    actual_run_id = run_id or generate_run_id()

    _trace_id_var.set(actual_trace_id)
    _run_id_var.set(actual_run_id)

    if conversation_id is not None:
        _conversation_id_var.set(conversation_id)
    if user_id is not None:
        _user_id_var.set(user_id)

    return actual_trace_id, actual_run_id


def clear_trace_context() -> None:
    """
    清除 Trace 上下文

    建议在请求结束时调用，避免内存泄漏

    使用示例：
        try:
            # 处理请求
            await handle_request()
        finally:
            clear_trace_context()
    """
    _trace_id_var.set(None)
    _run_id_var.set(None)
    _conversation_id_var.set(None)
    _user_id_var.set(None)


def copy_trace_context() -> RequestContext | None:
    """
    复制当前 Trace 上下文

    Returns:
        RequestContext 对象，包含当前所有上下文信息
    """
    trace_id = _trace_id_var.get()
    run_id = _run_id_var.get()

    if not trace_id or not run_id:
        return None

    return RequestContext(
        trace_id=trace_id,
        run_id=run_id,
        conversation_id=_conversation_id_var.get(),
        user_id=_user_id_var.get(),
    )
