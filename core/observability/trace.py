"""分布式追踪模块。

该模块使用 OpenTelemetry SDK 提供企业级分布式追踪能力。

为什么用 OpenTelemetry？
-----------------------
OpenTelemetry（简称 OTel）是 CNCF 毕业项目，是分布式追踪的事实标准。

核心优势：
1. **标准化**：供应商无关，可切换后端（Jaeger/Zipkin/Tempo）
2. **功能完整**：Span 管理、采样、上下文传播
3. **自动埋点**：支持 FastAPI、httpx、LangChain 自动注入
4. **生态完善**：Jaeger、Grafana Tempo、Loki 等原生支持
5. **社区活跃**：各大云厂商和开源项目广泛采用

对比自研方案：
- 自研：需要自己实现 Exporter、采样、上下文传递
- OpenTelemetry：开箱即用，社区维护，持续迭代

核心概念：
---------
1. **Tracer**：追踪器，负责创建 Span
2. **Span**：跨度，追踪的基本单元
3. **SpanContext**：上下文，包含 trace_id 和 span_id
4. **TracerProvider**：追踪器提供者，管理全局 Tracer
5. **SpanProcessor**：处理器，管理 Span 的生命周期
6. **SpanExporter**：导出器，将 Span 发送到后端

架构设计：
---------
    应用代码
        │
        ▼
    Tracer.start_span()
        │
        ├── 创建 Span
        ├── 设置属性
        └── 添加事件
        │
        ▼
    SpanProcessor
        │
        ├── 批量收集
        ├── 采样判断
        └── 缓存
        │
        ▼
    SpanExporter (OTLP/Jaeger/Console)
        │
        ▼
    后端存储 (Tempo/Jaeger)
        │
        ▼
    可视化 (Grafana)

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

    # 方式2: 装饰器（自动管理）
    @traced(span_name="rag_retrieval")
    async def retrieve(query: str):
        return await do_retrieval(query)
"""

from __future__ import annotations

import time
import functools
from typing import Any, Callable, Optional
from contextlib import contextmanager

# OpenTelemetry 核心
from opentelemetry import trace
from opentelemetry.trace import (
    Span,
    SpanKind,
    Status,
    StatusCode,
    Tracer,
    get_current_span,
)
from opentelemetry.trace.propagation import set_span_in_context
from opentelemetry.context import Context

# OpenTelemetry SDK
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanExporter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.sampling import Sampler, TraceIdRatioBased

# 用于返回值的类型注解
from opentelemetry.trace import Link


# ============================================================================
# Span 状态枚举（兼容旧代码）
# ============================================================================

class SpanStatus:
    """
    Span 状态枚举（兼容旧代码）

    对应 OpenTelemetry StatusCode：
    - UNSET: Span 尚未结束，状态未知
    - OK: Span 正常结束
    - ERROR: Span 以错误结束
    """

    UNSET = StatusCode.UNSET
    OK = StatusCode.OK
    ERROR = StatusCode.ERROR


# ============================================================================
# Span 事件
# ============================================================================

@dataclass
class SpanEvent:
    """
    Span 事件

    在 Span 执行过程中记录的关键事件。

    为什么需要事件？
    - 记录子步骤开始/结束
    - 记录状态变化
    - 记录关键决策点
    - 不创建子 Span，只记录时间点

    使用示例：
        span = tracer.start_span("rag_retrieval")
        span.add_event("retrieval_start", {"query_length": 50})
        # ... 执行检索 ...
        span.add_event("retrieval_end", {"result_count": 5})
    """
    name: str
    timestamp: datetime | None = None
    attributes: dict[str, Any] | None = None


# 需要 dataclass
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ============================================================================
# Tracer 封装
# ============================================================================

class OTelTracer:
    """
    OpenTelemetry Tracer 封装类

    在 OpenTelemetry SDK 的 Tracer 基础上封装，提供：
    1. 更简洁的 API
    2. 与现有代码兼容
    3. 自动资源注入
    4. 便捷的上下文管理

    为什么需要封装？
    - OpenTelemetry API 比较底层
    - 简化日常使用
    - 保持与旧代码的兼容性
    """

    def __init__(
        self,
        service_name: str = "agent-platform",
        exporter: SpanExporter | None = None,
        sampling_rate: float = 1.0,
    ):
        """
        初始化 OTel Tracer

        Args:
            service_name: 服务名称
            exporter: Span 导出器，默认使用 ConsoleSpanExporter
            sampling_rate: 采样率（0.0-1.0），1.0 表示全采样
        """
        self.service_name = service_name

        # 创建资源（包含服务信息）
        self.resource = Resource.create({
            "service.name": service_name,
            "service.version": "1.0.0",
        })

        # 创建采样器
        # TraceIdRatioBased：根据 trace_id 的哈希值采样
        # 确保同一个 trace 的所有 span 都被采样或都不被采样
        if sampling_rate < 1.0:
            sampler = TraceIdRatioBased(sampling_rate)
        else:
            sampler = Sampler.DEFAULT

        # 创建 TracerProvider
        self.provider = TracerProvider(
            resource=self.resource,
            sampler=sampler,
        )

        # 添加导出器
        if exporter is None:
            # 默认使用 Console 导出器（开发调试用）
            exporter = ConsoleSpanExporter()

        self.processor = BatchSpanProcessor(exporter)
        self.provider.add_span_processor(self.processor)

        # 设置全局 TracerProvider
        trace.set_tracer_provider(self.provider)

        # 获取 Tracer
        self.tracer = trace.get_tracer(
            instrumenting_module_name=service_name,
            instrumenting_library_version="1.0.0",
        )

    def start_span(
        self,
        name: str,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
    ) -> Span:
        """
        创建并启动一个 Span

        为什么需要这么多参数？
        - name: Span 的名称，应该简洁描述操作
        - trace_id: 如果外部传入 trace_id，可以保持链路连续
        - parent_span_id: 父 Span ID，构建父子关系
        - attributes: 初始属性，记录关键信息
        - kind: Span 类型，影响语义

        SpanKind 说明：
        - INTERNAL: 内部操作（默认）
        - SERVER: 服务端接收请求
        - CLIENT: 客户端发起请求
        - PRODUCER: 消息生产者
        - CONSUMER: 消息消费者

        Args:
            name: Span 名称
            trace_id: 可选的 trace_id（通常不需要，由 OTel 自动生成）
            parent_span_id: 父 Span ID（通常不需要，由 OTel 自动获取）
            attributes: 初始属性
            kind: Span 类型

        Returns:
            OpenTelemetry Span 对象
        """
        # 构建 span 名称（使用点分隔，符合 OpenTelemetry 约定）
        span_name = name

        # 创建 span
        span = self.tracer.start_span(
            name=span_name,
            kind=kind,
            attributes=attributes or {},
        )

        return span

    def end_span(
        self,
        span: Span,
        status: StatusCode = StatusCode.OK,
        error: Exception | None = None,
    ) -> None:
        """
        结束一个 Span

        为什么需要手动结束？
        - Span 需要知道结束时间
        - 需要设置状态和错误信息
        - 触发导出到后端

        Args:
            span: 要结束的 Span
            status: 状态码
            error: 异常对象（如果有）
        """
        if error:
            # 设置错误状态
            span.set_status(Status(StatusCode.ERROR, str(error)))
            # 记录异常信息
            span.record_exception(error)
        else:
            span.set_status(Status(status))

        # 结束 span
        span.end()

    def add_span_event(
        self,
        span: Span | None,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """
        给 Span 添加事件

        为什么用事件而不是子 Span？
        - 事件更轻量
        - 适合记录时间点
        - 不改变调用树结构

        Args:
            span: Span 对象（为 None 时使用当前 span）
            name: 事件名称
            attributes: 事件属性
        """
        if span is None:
            span = get_current_span()

        if span and span.is_recording():
            span.add_event(name, attributes=attributes or {})

    def set_span_attribute(
        self,
        span: Span | None,
        key: str,
        value: Any,
    ) -> None:
        """
        设置 Span 属性

        Args:
            span: Span 对象（为 None 时使用当前 span）
            key: 属性名
            value: 属性值
        """
        if span is None:
            span = get_current_span()

        if span and span.is_recording():
            span.set_attribute(key, value)

    def get_current_span_id(self) -> str | None:
        """
        获取当前 Span 的 ID

        Returns:
            当前 span_id，如果没有返回 None
        """
        span = get_current_span()
        if span and span.is_recording():
            return format(span.get_span_context().span_id, "016x")
        return None

    def get_current_trace_id(self) -> str | None:
        """
        获取当前 Trace 的 ID

        Returns:
            当前 trace_id，如果没有返回 None
        """
        span = get_current_span()
        if span and span.is_recording():
            return format(span.get_span_context().trace_id, "032x")
        return None


# ============================================================================
# 全局 Tracer
# ============================================================================

# 全局 OTelTracer 实例
_otel_tracer: OTelTracer | None = None


def get_tracer(
    service_name: str = "agent-platform",
    exporter: SpanExporter | None = None,
    sampling_rate: float = 1.0,
) -> OTelTracer:
    """
    获取全局 Tracer 实例

    使用单例模式，全局只有一个 Tracer 实例。

    为什么用单例？
    - TracerProvider 创建成本高
    - 确保所有代码使用同一个 Provider
    - 便于统一配置

    Args:
        service_name: 服务名称（仅首次有效）
        exporter: Span 导出器（仅首次有效）
        sampling_rate: 采样率（仅首次有效）

    Returns:
        OTelTracer 实例
    """
    global _otel_tracer
    if _otel_tracer is None:
        _otel_tracer = OTelTracer(
            service_name=service_name,
            exporter=exporter,
            sampling_rate=sampling_rate,
        )
    return _otel_tracer


def get_otel_tracer() -> OTelTracer:
    """
    获取全局 Tracer 实例（别名）

    与 get_tracer 等价
    """
    return get_tracer()


# ============================================================================
# traced 装饰器
# ============================================================================

def traced(
    span_name: str | None = None,
    attributes: dict[str, Any] | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
) -> Callable:
    """
    Span 追踪装饰器

    自动为函数创建和结束 Span，支持同步和异步函数。

    为什么需要装饰器？
    - 简化 Span 管理
    - 确保 Span 正确结束
    - 自动记录异常

    使用示例：
        @traced(span_name="rag_retrieval")
        async def retrieve(query: str):
            return await do_retrieval(query)

        # 自动添加属性
        @traced(attributes={"operation": "batch_process"})
        def batch_process(items: list):
            return [process(item) for item in items]

    Args:
        span_name: Span 名称（默认使用函数全名）
        attributes: 初始属性
        kind: Span 类型
    """
    def decorator(func: Callable) -> Callable:
        # 获取函数名作为默认 span_name
        _span_name = span_name or f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            tracer = get_tracer()

            # 获取 tracer 实例
            otel_tracer = tracer.tracer

            # 创建 span
            span = otel_tracer.start_span(
                name=_span_name,
                kind=kind,
                attributes=attributes,
            )

            try:
                # 执行函数
                result = await func(*args, **kwargs)
                # 成功结束
                span.set_status(Status(StatusCode.OK))
                return result
            except Exception as e:
                # 异常结束
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise
            finally:
                # 确保 span 结束
                span.end()

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            tracer = get_tracer()

            # 获取 tracer 实例
            otel_tracer = tracer.tracer

            # 创建 span
            span = otel_tracer.start_span(
                name=_span_name,
                kind=kind,
                attributes=attributes,
            )

            try:
                # 执行函数
                result = func(*args, **kwargs)
                # 成功结束
                span.set_status(Status(StatusCode.OK))
                return result
            except Exception as e:
                # 异常结束
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise
            finally:
                # 确保 span 结束
                span.end()

        # 根据函数类型返回不同的包装器
        import asyncio
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

    使用 with 语句自动管理 Span 生命周期。

    为什么需要上下文管理器？
    - 确保 Span 正确结束
    - 自动处理异常
    - 代码更简洁

    使用示例：
        tracer = get_tracer()
        with SpanContext(tracer, "my_operation") as span:
            # span 已自动创建
            do_something()
        # span 已自动结束
    """

    def __init__(
        self,
        tracer: OTelTracer,
        name: str,
        attributes: dict[str, Any] | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
    ):
        self.tracer = tracer
        self.name = name
        self.attributes = attributes
        self.kind = kind
        self.span: Span | None = None

    def __enter__(self) -> Span:
        """同步上下文入口"""
        self.span = self.tracer.start_span(
            name=self.name,
            attributes=self.attributes,
            kind=self.kind,
        )
        return self.span

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """同步上下文出口"""
        if self.span:
            if exc_val:
                self.span.set_status(Status(StatusCode.ERROR, str(exc_val)))
                self.span.record_exception(exc_val)
            else:
                self.span.set_status(Status(StatusCode.OK))
            self.span.end()

    async def __aenter__(self) -> Span:
        """异步上下文入口"""
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文出口"""
        self.__exit__(exc_type, exc_val, exc_tb)


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

    Args:
        name: Span 名称
        attributes: 初始属性

    Returns:
        OpenTelemetry Span 对象
    """
    return get_tracer().start_span(name, attributes=attributes)


def end_span(
    span: Span,
    status: StatusCode = StatusCode.OK,
    error: Exception | None = None,
) -> None:
    """
    便捷函数：结束 Span

    Args:
        span: 要结束的 Span
        status: 状态码
        error: 异常对象
    """
    get_tracer().end_span(span, status, error)


def add_event(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> None:
    """
    便捷函数：添加 Span 事件

    Args:
        name: 事件名称
        attributes: 事件属性
    """
    tracer = get_tracer()
    tracer.add_span_event(None, name, attributes)


def get_current_span() -> Span:
    """
    获取当前正在执行的 Span

    Returns:
        当前 Span
    """
    return trace.get_current_span()


def set_attribute(key: str, value: Any) -> None:
    """
    便捷函数：设置当前 Span 的属性

    Args:
        key: 属性名
        value: 属性值
    """
    span = trace.get_current_span()
    if span and span.is_recording():
        span.set_attribute(key, value)


# ============================================================================
# 与旧代码兼容的类型别名
# ============================================================================

# 为了兼容旧代码，提供这些类型别名
# 实际使用时应该使用 OpenTelemetry 原生类型

SpanKind = SpanKind
StatusCode = StatusCode


# ============================================================================
# OTLP 导出配置
# ============================================================================

def configure_otlp_exporter(
    endpoint: str = "http://localhost:4317",
    insecure: bool = True,
) -> SpanExporter:
    """
    配置 OTLP 导出器

    OTLP（OpenTelemetry Protocol）是 OTel 的标准协议，
    用于将数据发送到 OpenTelemetry Collector 或支持 OTLP 的后端。

    为什么用 OTLP？
    - 标准协议，供应商无关
    - 支持 Trace、Metrics、Logs
    - 可以在 Collector 中做采样、过滤、路由

    Args:
        endpoint: OTLP 接收端点（通常是 Collector 的 OTLP 端口）
        insecure: 是否使用非安全连接（开发环境 True，生产环境 False）

    Returns:
        OTLP SpanExporter
    """
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    exporter = OTLPSpanExporter(
        endpoint=endpoint,
        insecure=insecure,
    )

    return exporter


def configure_jaeger_exporter(
    agent_host: str = "localhost",
    agent_port: int = 6831,
) -> SpanExporter:
    """
    配置 Jaeger 导出器（直接导出到 Jaeger Agent）

    Jaeger 是 CNCF 毕业项目，专业的分布式追踪系统。

    Args:
        agent_host: Jaeger Agent 主机
        agent_port: Jaeger Agent 端口

    Returns:
        Jaeger SpanExporter
    """
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter

    exporter = JaegerExporter(
        agent_host_name=agent_host,
        agent_port=agent_port,
    )

    return exporter
