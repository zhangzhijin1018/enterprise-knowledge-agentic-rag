"""Prometheus 指标采集模块。

该模块提供简化的指标采集能力，支持 Prometheus 格式输出。

核心概念：
---------
1. Counter（计数器）：只能递增，用于记录次数
2. Gauge（仪表）：可增可减，用于记录当前值
3. Histogram（直方图）：记录分布，用于记录延迟

为什么需要指标？
--------------
日志和追踪告诉我们"发生了什么"，指标告诉我们"发生了多少"。

| 类型 | 用途 | 示例 |
|------|------|------|
| Counter | 记录次数 | 请求数、错误数、Token消耗 |
| Gauge | 记录当前值 | 活跃连接数、队列长度 |
| Histogram | 记录分布 | 请求延迟、响应大小 |

核心设计：
---------
1. 简化 API：不需要理解 Prometheus 复杂概念
2. 自动注册：首次使用自动注册指标
3. 上下文感知：自动带上 trace_id 等标签

使用示例：
    from core.observability.metrics import metrics, track_latency, setup_metrics

    # 初始化（应用启动时）
    setup_metrics()

    # 记录计数器
    metrics.increment("requests_total", tags={"endpoint": "/chat"})

    # 记录直方图
    metrics.observe("request_duration", 0.125, tags={"endpoint": "/chat"})

    # 使用装饰器自动追踪
    @track_latency("my_function")
    def my_function():
        pass
"""

from __future__ import annotations

import time
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from functools import wraps
from collections import defaultdict

from core.observability.context import get_trace_id, get_run_id
from core.observability.logging import get_logger

# ============================================================================
# 指标类型
# ============================================================================

class MetricType(Enum):
    """指标类型枚举"""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


# ============================================================================
# 指标定义
# ============================================================================

@dataclass
class MetricDefinition:
    """
    指标定义

    描述一个指标的基本信息
    """
    # 指标名称
    name: str

    # 指标类型
    metric_type: MetricType

    # 描述
    description: str = ""

    # 单位
    unit: str = ""

    # 标签
    label_names: tuple[str, ...] = ()

    # 桶配置（仅 Histogram）
    buckets: tuple[float, ...] = (.005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0)


@dataclass
class CounterValue:
    """计数器值"""
    value: float = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class GaugeValue:
    """仪表值"""
    value: float = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class HistogramValue:
    """直方图值"""
    count: int = 0
    sum: float = 0
    buckets: dict[float, int] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# 指标存储
# ============================================================================

class MetricStorage:
    """
    内存指标存储

    用于存储指标的当前值，支持线程安全操作

    注意：这是简化实现，生产环境应该使用 prometheus_client 库
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, CounterValue] = defaultdict(CounterValue)
        self._gauges: dict[str, GaugeValue] = defaultdict(GaugeValue)
        self._histograms: dict[str, HistogramValue] = defaultdict(
            lambda: HistogramValue(buckets={})
        )

    def inc_counter(self, name: str, value: float = 1, labels: dict | None = None) -> None:
        """增加计数器"""
        key = self._make_key(name, labels)
        with self._lock:
            self._counters[key].value += value
            self._counters[key].timestamp = datetime.now(timezone.utc)

    def set_gauge(self, name: str, value: float, labels: dict | None = None) -> None:
        """设置仪表值"""
        key = self._make_key(name, labels)
        with self._lock:
            self._gauges[key].value = value
            self._gauges[key].timestamp = datetime.now(timezone.utc)

    def observe_histogram(self, name: str, value: float, labels: dict | None = None) -> None:
        """记录直方图值"""
        key = self._make_key(name, labels)
        with self._lock:
            h = self._histograms[key]
            h.count += 1
            h.sum += value
            for bucket in self._get_buckets(name):
                if value <= bucket:
                    h.buckets[bucket] = h.buckets.get(bucket, 0) + 1

    def _make_key(self, name: str, labels: dict | None) -> str:
        """生成指标键"""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def _get_buckets(self, name: str) -> tuple[float, ...]:
        """获取桶配置"""
        # 默认桶配置
        return (.005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0)

    def get_counter(self, name: str, labels: dict | None = None) -> float:
        """获取计数器值"""
        key = self._make_key(name, labels)
        with self._lock:
            return self._counters[key].value

    def get_gauge(self, name: str, labels: dict | None = None) -> float:
        """获取仪表值"""
        key = self._make_key(name, labels)
        with self._lock:
            return self._gauges[key].value

    def get_histogram(self, name: str, labels: dict | None = None) -> dict:
        """获取直方图值"""
        key = self._make_key(name, labels)
        with self._lock:
            h = self._histograms[key]
            return {
                "count": h.count,
                "sum": h.sum,
                "buckets": dict(h.buckets),
            }


# ============================================================================
# Prometheus 格式化器
# ============================================================================

class PrometheusFormatter:
    """
    Prometheus 指标格式化器

    将指标值格式化为 Prometheus 文本格式

    格式说明：
    ---------
    # HELP 请求总数
    # TYPE 请求总数 counter
    请求总数{endpoint="/chat"} 12345
    """

    def format(self, storage: MetricStorage) -> str:
        """
        格式化所有指标

        Returns:
            Prometheus 格式的文本
        """
        lines = []

        # 格式化计数器
        for key, value in storage._counters.items():
            name = key.split("{")[0] if "{" in key else key
            labels = self._extract_labels(key)
            help_text = f"# HELP {name}"
            type_text = f"# TYPE {name} counter"
            value_text = f"{name}{{{labels}}} {value.value}"

            lines.extend([help_text, type_text, value_text, ""])

        # 格式化仪表
        for key, value in storage._gauges.items():
            name = key.split("{")[0] if "{" in key else key
            labels = self._extract_labels(key)
            help_text = f"# HELP {name}"
            type_text = f"# TYPE {name} gauge"
            value_text = f"{name}{{{labels}}} {value.value}"

            lines.extend([help_text, type_text, value_text, ""])

        # 格式化直方图
        for key, h in storage._histograms.items():
            name = key.split("{")[0] if "{" in key else key
            labels = self._extract_labels(key)
            help_text = f"# HELP {name}"
            type_text = f"# TYPE {name} histogram"

            lines.extend([help_text, type_text])

            # 每个桶一行
            cumulative = 0
            for bucket, count in sorted(h.buckets.items()):
                cumulative += count
                bucket_labels = f'{labels},"le":"{bucket}"}'
                lines.append(f'{name}_bucket{{{bucket_labels}}} {cumulative}')

            # +Inf 桶
            inf_labels = f'{labels},"le":"+Inf"}'
            lines.append(f'{name}_bucket{{{inf_labels}}} {h.count}')

            # sum 和 count
            lines.append(f"{name}_sum{{{labels}}} {h.sum}")
            lines.append(f"{name}_count{{{labels}}} {h.count}")
            lines.append("")

        return "\n".join(lines)

    def _extract_labels(self, key: str) -> str:
        """从键中提取标签"""
        if "{" not in key:
            return ""
        return key[key.index("{"):]


# ============================================================================
# 指标管理器
# ============================================================================

class MetricsManager:
    """
    指标管理器

    核心功能：
    1. 提供简洁的指标操作 API
    2. 自动创建和管理指标
    3. 支持 Prometheus 格式导出

    使用示例：
        # 初始化
        metrics = MetricsManager()

        # 记录指标
        metrics.increment("requests_total", tags={"endpoint": "/chat"})
        metrics.gauge("active_connections", 100)
        metrics.observe("request_duration", 0.125)
    """

    def __init__(self, service_name: str = "agent-platform"):
        self.service_name = service_name
        self.storage = MetricStorage()
        self.logger = get_logger("metrics")
        self._enabled = True

    def enable(self) -> None:
        """启用指标采集"""
        self._enabled = True

    def disable(self) -> None:
        """禁用指标采集"""
        self._enabled = False

    def increment(
        self,
        name: str,
        value: float = 1,
        tags: dict[str, str] | None = None,
    ) -> None:
        """
        增加计数器

        Args:
            name: 指标名称
            value: 增量值
            tags: 标签字典

        使用示例：
            metrics.increment("requests_total", tags={"endpoint": "/chat"})
            metrics.increment("errors_total", value=1, tags={"type": "timeout"})
        """
        if not self._enabled:
            return

        self.storage.inc_counter(name, value, tags)
        self.logger.debug(
            event="metric_increment",
            message=f"Counter 增加: {name} +{value}",
            extra={"name": name, "value": value, "tags": tags or {}},
        )

    def gauge(
        self,
        name: str,
        value: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        """
        设置仪表值

        Args:
            name: 指标名称
            value: 值
            tags: 标签字典

        使用示例：
            metrics.gauge("active_connections", 100)
            metrics.gauge("queue_length", 50, tags={"queue": "high_priority"})
        """
        if not self._enabled:
            return

        self.storage.set_gauge(name, value, tags)
        self.logger.debug(
            event="metric_gauge",
            message=f"Gauge 设置: {name} = {value}",
            extra={"name": name, "value": value, "tags": tags or {}},
        )

    def observe(
        self,
        name: str,
        value: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        """
        记录直方图值

        Args:
            name: 指标名称
            value: 观察值
            tags: 标签字典

        使用示例：
            metrics.observe("request_duration", 0.125)
            metrics.observe("response_size", 1024, tags={"type": "json"})
        """
        if not self._enabled:
            return

        self.storage.observe_histogram(name, value, tags)
        self.logger.debug(
            event="metric_observe",
            message=f"Histogram 记录: {name} = {value}",
            extra={"name": name, "value": value, "tags": tags or {}},
        )

    # ==================== 业务专用方法 ====================

    def record_request(
        self,
        endpoint: str,
        method: str = "POST",
        status_code: int = 200,
        duration_ms: float = 0,
    ) -> None:
        """
        记录 HTTP 请求

        Args:
            endpoint: 端点路径
            method: HTTP 方法
            status_code: 状态码
            duration_ms: 耗时（毫秒）
        """
        tags = {"endpoint": endpoint, "method": method, "status": str(status_code)}

        self.increment("http_requests_total", tags=tags)
        if duration_ms > 0:
            self.observe("http_request_duration_seconds", duration_ms / 1000, tags=tags)

    def record_llm_call(
        self,
        model: str,
        provider: str,
        success: bool = True,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        duration_ms: float = 0,
    ) -> None:
        """
        记录 LLM 调用

        Args:
            model: 模型名称
            provider: 提供商
            success: 是否成功
            prompt_tokens: 提示词 Token 数
            completion_tokens: 完成 Token 数
            duration_ms: 耗时
        """
        tags = {"model": model, "provider": provider, "status": "success" if success else "error"}

        self.increment("llm_calls_total", tags=tags)
        self.increment("llm_tokens_total", prompt_tokens, tags={**tags, "type": "prompt"})
        self.increment("llm_tokens_total", completion_tokens, tags={**tags, "type": "completion"})

        if duration_ms > 0:
            self.observe("llm_call_duration_seconds", duration_ms / 1000, tags=tags)

    def record_agent_execution(
        self,
        agent_name: str,
        intent_type: str,
        success: bool = True,
        duration_ms: float = 0,
        tool_calls: int = 0,
    ) -> None:
        """
        记录 Agent 执行

        Args:
            agent_name: Agent 名称
            intent_type: 意图类型
            success: 是否成功
            duration_ms: 耗时
            tool_calls: 工具调用次数
        """
        tags = {"agent": agent_name, "intent": intent_type, "status": "success" if success else "error"}

        self.increment("agent_executions_total", tags=tags)
        self.increment("agent_tool_calls_total", tool_calls, tags={"agent": agent_name})

        if duration_ms > 0:
            self.observe("agent_execution_duration_seconds", duration_ms / 1000, tags=tags)

    def record_rag_retrieval(
        self,
        retrieval_type: str,
        top_k: int,
        retrieved_count: int,
        duration_ms: float = 0,
    ) -> None:
        """
        记录 RAG 检索

        Args:
            retrieval_type: 检索类型
            top_k: 请求数量
            retrieved_count: 实际检索数量
            duration_ms: 耗时
        """
        tags = {"type": retrieval_type}

        self.increment("rag_retrieval_total", tags=tags)
        self.observe("rag_retrieval_count", retrieved_count, tags=tags)

        if duration_ms > 0:
            self.observe("rag_retrieval_duration_seconds", duration_ms / 1000, tags=tags)

    # ==================== 导出 ====================

    def export(self) -> str:
        """
        导出 Prometheus 格式指标

        Returns:
            Prometheus 格式文本
        """
        formatter = PrometheusFormatter()
        return formatter.format(self.storage)


# ============================================================================
# 全局实例
# ============================================================================

_metrics_manager: MetricsManager | None = None


def get_metrics() -> MetricsManager:
    """获取全局指标管理器"""
    global _metrics_manager
    if _metrics_manager is None:
        _metrics_manager = MetricsManager()
    return _metrics_manager


# 便捷访问
metrics = get_metrics()


def setup_metrics(service_name: str = "agent-platform") -> MetricsManager:
    """
    初始化指标系统

    Args:
        service_name: 服务名称

    Returns:
        MetricsManager 实例
    """
    global _metrics_manager
    _metrics_manager = MetricsManager(service_name=service_name)
    return _metrics_manager


# ============================================================================
# 装饰器
# ============================================================================

def track_latency(
    metric_name: str,
    tags: dict[str, str] | None = None,
) -> Callable:
    """
    延迟追踪装饰器

    自动记录函数执行时间到 Histogram

    Args:
        metric_name: 指标名称
        tags: 标签

    使用示例：
        @track_latency("my_function_duration")
        def my_function():
            pass

        @track_latency("rag_retrieval_duration", tags={"type": "hybrid"})
        async def retrieve():
            pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = (time.time() - start_time) * 1000  # 毫秒
                m = get_metrics()
                m.observe(metric_name, duration / 1000, tags=tags)  # 转为秒

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = (time.time() - start_time) * 1000
                m = get_metrics()
                m.observe(metric_name, duration / 1000, tags=tags)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def track_counter(
    metric_name: str,
    tags: dict[str, str] | None = None,
) -> Callable:
    """
    计数器追踪装饰器

    自动在函数调用时增加计数器

    Args:
        metric_name: 指标名称
        tags: 标签

    使用示例：
        @track_counter("my_function_calls")
        def my_function():
            pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            m = get_metrics()
            m.increment(metric_name, tags=tags)
            return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            m = get_metrics()
            m.increment(metric_name, tags=tags)
            return func(*args, **kwargs)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
