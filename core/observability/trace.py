"""分布式追踪模块。

该模块提供完整的调用链追踪能力，支持 Span 管理和异步上下文传递。

核心概念：
---------
1. Trace（追踪）：一次完整的请求链路
2. Span（跨度）：Trace 中的一个操作单元
3. Parent-Child 关系：Span 之间的父子关系

为什么需要分布式追踪？
---------------------
微服务架构下，一个请求可能经过多个服务：
    用户请求 → API Gateway → Auth Service → User Service → Database

传统日志只能看到单个服务的日志，追踪困难。

分布式追踪可以：
1. 看到完整的调用链路
2. 定位哪个环节耗时
3. 追踪跨服务的错误

架构设计：
---------
Trace 由多个 Span 组成，形成树形结构：

    Trace (tr_abc123)
    ├── Span: API Gateway (根节点)
    │   ├── Span: Auth Service
    │   │   └── Span: Redis
    │   └── Span: User Service
    │       └── Span: PostgreSQL

使用示例：
    from core.observability.trace import get_tracer, traced, SpanStatus

    tracer = get_tracer()

    # 方式1: 手动管理 Span
    span = tracer.start_span("intent_detection")
    try:
        result = detect_intent(query)
        span.end(status=SpanStatus.OK)
    except Exception as e:
        span.end(status=SpanStatus.ERROR, error=e)
        raise

    # 方式2: 使用装饰器
    @traced(span_name="rag_retrieval")
    async def retrieve(query: str):
        return await do_retrieval(query)
"""

from __future__ import annotations

import time
import json
import uuid
from abc import ABC, abstractmethod
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional
from functools import wraps
import asyncio

from core.observability.context import (
    get_trace_id,
    get_run_id,
    set_trace_context,
    generate_trace_id,
    generate_run_id,
)
from core.observability.logging import get_logger

# ============================================================================
# Span 状态枚举
# ============================================================================

class SpanStatus(Enum):
    """
    Span 状态枚举

    描述一个 Span 的执行结果状态
    """
    # Span 正常结束
    OK = "ok"

    # Span 以错误结束
    ERROR = "error"

    # Span 尚未结束或状态未知
    UNSET = "unset"


# ============================================================================
# Span 事件
# ============================================================================

@dataclass
class SpanEvent:
    """
    Span 事件

    在 Span 执行过程中记录的关键事件

    使用场景：
    - 记录子步骤开始/结束
    - 记录状态变化
    - 记录关键决策点
    """
    # 事件名称
    name: str

    # 事件时间戳
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # 事件属性
    attributes: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Span 对象
# ============================================================================

@dataclass
class Span:
    """
    Span（跨度）对象

    Span 是追踪的基本单元，代表一个操作或时间段

    字段说明：
    --------
    - trace_id: 所属 Trace 的唯一标识
    - span_id: Span 自身的唯一标识
    - parent_span_id: 父 Span 的 ID（用于构建树形结构）
    - name: Span 名称（描述操作）
    - start_time / end_time: 开始/结束时间
    - status: 执行状态
    - attributes: 属性（键值对）
    - events: 事件列表
    - error: 错误信息

    设计原理：
    --------
    Span 的设计参考了 OpenTelemetry 的 Data Model：
    - 使用树形结构表示调用关系
    - 通过时间戳计算耗时
    - 通过 attributes 添加结构化属性
    - 通过 events 记录关键时刻
    """
    # 标识信息
    trace_id: str
    span_id: str
    parent_span_id: str | None

    # 操作信息
    name: str

    # 时间信息
    start_time: datetime
    end_time: datetime | None = None

    # 状态信息
    status: SpanStatus = SpanStatus.UNSET

    # 属性和事件
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[SpanEvent] = field(default_factory=list)

    # 错误信息
    error: dict[str, Any] | None = None

    # 资源信息
    service_name: str = "agent-platform"

    @property
    def duration_ms(self) -> float | None:
        """
        计算 Span 耗时（毫秒）

        Returns:
            耗时（毫秒），如果未结束返回 None
        """
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return None

    @property
    def isEnded(self) -> bool:
        """Span 是否已结束"""
        return self.end_time is not None

    def set_attribute(self, key: str, value: Any) -> None:
        """设置属性"""
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """
        添加事件

        Args:
            name: 事件名称
            attributes: 事件属性
        """
        self.events.append(SpanEvent(
            name=name,
            attributes=attributes or {}
        ))

    def set_error(self, error: Exception) -> None:
        """
        设置错误信息

        Args:
            error: 异常对象
        """
        self.status = SpanStatus.ERROR
        self.error = {
            "type": type(error).__name__,
            "message": str(error),
        }

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "service_name": self.service_name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "status": self.status.value,
            "attributes": self.attributes,
            "events": [
                {
                    "name": e.name,
                    "timestamp": e.timestamp.isoformat(),
                    "attributes": e.attributes,
                }
                for e in self.events
            ],
            "error": self.error,
        }


# ============================================================================
# Span 导出器抽象
# ============================================================================

class SpanExporter(ABC):
    """
    Span 导出器抽象基类

    定义 Span 数据的导出接口

    实现类：
    - ConsoleExporter: 输出到控制台（开发调试）
    - FileExporter: 输出到文件
    - JaegerExporter: 导出到 Jaeger
    - OTLPExporter: 导出到 OpenTelemetry Collector
    """

    @abstractmethod
    def export(self, span: Span) -> None:
        """
        导出单个 Span

        Args:
            span: Span 对象
        """
        pass

    @abstractmethod
    def export_batch(self, spans: list[Span]) -> None:
        """
        批量导出 Span

        Args:
            spans: Span 列表
        """
        pass


class ConsoleSpanExporter(SpanExporter):
    """
    控制台 Span 导出器

    将 Span 输出到控制台，便于开发调试

    输出格式：
    [TRACE] {"trace_id": "tr_abc123", "span_id": "sp_xyz", ...}
    """

    def export(self, span: Span) -> None:
        """导出单个 Span 到控制台"""
        print(f"[TRACE] {json.dumps(span.to_dict())}")

    def export_batch(self, spans: list[Span]) -> None:
        """批量导出 Span 到控制台"""
        for span in spans:
            self.export(span)


# ============================================================================
# Tracer 实现
# ============================================================================

class Tracer:
    """
    追踪器

    负责创建、管理和导出 Span

    核心功能：
    1. 创建 Span
    2. 管理 Span 生命周期
    3. 导出 Span 数据

    设计原理：
    --------
    Tracer 的设计参考了 OpenTelemetry SDK：
    - 使用 Provider 模式管理全局配置
    - 使用 Exporter 模式导出数据
    - 使用 contextvars 传递上下文
    """

    def __init__(
        self,
        service_name: str = "agent-platform",
        exporter: SpanExporter | None = None,
    ):
        """
        初始化 Tracer

        Args:
            service_name: 服务名称
            exporter: Span 导出器，默认使用 ConsoleExporter
        """
        self.service_name = service_name
        self.exporter = exporter or ConsoleSpanExporter()

        # 日志器
        self.logger = get_logger("tracer")

    def start_span(
        self,
        name: str,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        """
        创建并启动一个 Span

        Args:
            name: Span 名称
            trace_id: Trace ID（为空则自动生成）
            parent_span_id: 父 Span ID（为空则从上下文获取）
            attributes: 初始属性

        Returns:
            新的 Span 对象

        设计说明：
        --------
        Span 创建时会：
        1. 生成或使用传入的 trace_id
        2. 生成新的 span_id
        3. 从 contextvars 获取父 span_id
        4. 记录 start_time
        """
        # 获取或生成 trace_id
        actual_trace_id = trace_id or get_trace_id() or generate_trace_id()

        # 获取父 span_id（从上下文）
        actual_parent_id = parent_span_id or _current_span_id_var.get()

        # 生成 span_id
        span_id = self._generate_span_id()

        # 创建 Span
        span = Span(
            trace_id=actual_trace_id,
            span_id=span_id,
            parent_span_id=actual_parent_id,
            name=name,
            start_time=datetime.now(timezone.utc),
            attributes=attributes or {},
            service_name=self.service_name,
        )

        # 更新上下文
        _current_span_id_var.set(span_id)
        _spans_stack_var.get().append(span)

        self.logger.debug(
            event="span_start",
            message=f"启动 Span: {name}",
            extra={
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "parent_span_id": span.parent_span_id,
            }
        )

        return span

    def end_span(
        self,
        span: Span,
        status: SpanStatus = SpanStatus.OK,
        error: Exception | None = None,
    ) -> None:
        """
        结束一个 Span

        Args:
            span: 要结束的 Span
            status: 状态
            error: 异常（如果有）

        设计说明：
        --------
        Span 结束时会：
        1. 记录 end_time
        2. 设置状态
        3. 设置错误信息（如果有）
        4. 计算 duration_ms
        5. 导出到后端
        """
        # 如果已结束，跳过
        if span.isEnded:
            self.logger.warning(
                event="span_already_ended",
                message=f"Span 已结束，忽略重复调用: {span.name}"
            )
            return

        # 记录结束时间
        span.end_time = datetime.now(timezone.utc)
        span.status = status

        # 记录错误
        if error:
            span.set_error(error)

        # 导出 Span
        self.exporter.export(span)

        # 从栈中弹出
        spans_stack = _spans_stack_var.get()
        if spans_stack and spans_stack[-1] == span:
            spans_stack.pop()

        # 恢复父 span_id
        if span.parent_span_id:
            _current_span_id_var.set(span.parent_span_id)
        else:
            _current_span_id_var.set(None)

        self.logger.debug(
            event="span_end",
            message=f"结束 Span: {span.name}",
            extra={
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "duration_ms": span.duration_ms,
                "status": span.status.value,
            }
        )

    def add_span_event(
        self,
        span: Span | None,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """
        给 Span 添加事件

        Args:
            span: Span 对象（为 None 时使用当前 Span）
            name: 事件名称
            attributes: 事件属性
        """
        if span is None:
            spans = _spans_stack_var.get()
            if spans:
                span = spans[-1]

        if span:
            span.add_event(name, attributes)

    def get_current_span(self) -> Span | None:
        """
        获取当前正在执行的 Span

        Returns:
            当前 Span，如果没有返回 None
        """
        spans = _spans_stack_var.get()
        return spans[-1] if spans else None

    def _generate_span_id(self) -> str:
        """生成 Span ID"""
        return f"sp_{uuid.uuid4().hex[:16]}"


# ============================================================================
# 上下文变量
# ============================================================================

# 当前 Span ID（用于维护父子关系）
_current_span_id_var: ContextVar[str | None] = ContextVar(
    "current_span_id",
    default=None
)

# Span 栈（支持嵌套 Span）
_spans_stack_var: ContextVar[list[Span]] = ContextVar(
    "spans_stack",
    default=list
)


# ============================================================================
# 全局 Tracer
# ============================================================================

_tracer: Tracer | None = None


def get_tracer(service_name: str = "agent-platform") -> Tracer:
    """
    获取全局 Tracer 实例

    使用单例模式，全局只有一个 Tracer 实例

    Args:
        service_name: 服务名称（仅首次有效）

    Returns:
        Tracer 实例
    """
    global _tracer
    if _tracer is None:
        _tracer = Tracer(service_name=service_name)
    return _tracer


# ============================================================================
# traced 装饰器
# ============================================================================

def traced(
    span_name: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> Callable:
    """
    Span 追踪装饰器

    自动为函数创建和结束 Span

    Args:
        span_name: Span 名称（默认使用函数名）
        attributes: 初始属性

    使用示例：
        @traced(span_name="rag_retrieval")
        async def retrieve(query: str):
            return await do_retrieval(query)

        # 等价于：
        async def retrieve(query: str):
            span = tracer.start_span("rag_retrieval")
            try:
                result = await do_retrieval(query)
                span.end(status=SpanStatus.OK)
                return result
            except Exception as e:
                span.end(status=SpanStatus.ERROR, error=e)
                raise
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            tracer = get_tracer()
            name = span_name or f"{func.__module__}.{func.__name__}"

            # 创建 Span
            span = tracer.start_span(name, attributes=attributes)

            try:
                # 执行函数
                result = await func(*args, **kwargs)

                # 成功结束
                tracer.end_span(span, SpanStatus.OK)
                return result

            except Exception as e:
                # 异常结束
                tracer.end_span(span, SpanStatus.ERROR, e)
                raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            tracer = get_tracer()
            name = span_name or f"{func.__module__}.{func.__name__}"

            # 创建 Span
            span = tracer.start_span(name, attributes=attributes)

            try:
                # 执行函数
                result = func(*args, **kwargs)

                # 成功结束
                tracer.end_span(span, SpanStatus.OK)
                return result

            except Exception as e:
                # 异常结束
                tracer.end_span(span, SpanStatus.ERROR, e)
                raise

        # 根据函数类型返回不同的包装器
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ============================================================================
# Span 上下文管理器
# ============================================================================

class SpanContext:
    """
    Span 上下文管理器

    使用 with 语句自动管理 Span 生命周期

    使用示例：
        tracer = get_tracer()
        with SpanContext(tracer, "my_operation") as span:
            # span 已自动创建
            do_something()
        # span 已自动结束
    """

    def __init__(
        self,
        tracer: Tracer,
        name: str,
        attributes: dict[str, Any] | None = None,
    ):
        self.tracer = tracer
        self.name = name
        self.attributes = attributes
        self.span: Span | None = None

    def __enter__(self) -> Span:
        self.span = self.tracer.start_span(
            self.name,
            attributes=self.attributes
        )
        return self.span

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.span:
            if exc_val:
                self.tracer.end_span(self.span, SpanStatus.ERROR, exc_val)
            else:
                self.tracer.end_span(self.span, SpanStatus.OK)


# ============================================================================
# 便捷函数
# ============================================================================

def start_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Span:
    """
    便捷函数：启动 Span

    使用全局 Tracer
    """
    return get_tracer().start_span(name, attributes=attributes)


def end_span(
    span: Span,
    status: SpanStatus = SpanStatus.OK,
    error: Exception | None = None,
) -> None:
    """
    便捷函数：结束 Span
    """
    get_tracer().end_span(span, status, error)


def add_event(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> None:
    """
    便捷函数：添加 Span 事件
    """
    tracer = get_tracer()
    span = tracer.get_current_span()
    if span:
        tracer.add_span_event(span, name, attributes)
