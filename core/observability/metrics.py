"""Prometheus 指标采集模块。

该模块使用 prometheus_client 提供企业级指标采集能力。

为什么用 prometheus_client？
-------------------------
prometheus_client 是 Prometheus 官方提供的 Python 客户端，是采集指标的事实标准。

核心优势：
1. **官方支持**：Prometheus 官方维护，持续更新
2. **格式正确**：自动生成符合 Prometheus 规范的指标格式
3. **功能完整**：Counter、Gauge、Histogram、Summary 全支持
4. **性能优秀**：高效的并发计数器实现
5. **易于集成**：与 Prometheus、Grafana 原生兼容

对比自研方案：
- 自研：需要手写 Histogram 桶计算、格式生成
- prometheus_client：开箱即用，格式正确

核心概念：
---------
1. **Counter**：只能递增的计数器，用于记录次数
2. **Gauge**：可增可减的仪表，用于记录当前值
3. **Histogram**：直方图，记录分布，用于延迟统计
4. **Summary**：摘要，类似 Histogram，但计算在客户端完成

指标格式（Prometheus text format）：
    # HELP 请求总数
    # TYPE 请求总数 counter
    请求总数{endpoint="/chat"} 12345

    # HELP 请求延迟分布
    # TYPE 请求延迟分布 histogram
    请求延迟分布_bucket{endpoint="/chat",le="0.1"} 1000
    请求延迟分布_bucket{endpoint="/chat",le="0.5"} 5000
    请求延迟分布_bucket{endpoint="/chat",le="+Inf"} 10000
    请求延迟分布_sum{endpoint="/chat"} 2500.5
    请求延迟分布_count{endpoint="/chat"} 10000

使用示例：
    from core.observability.metrics import metrics

    # 记录计数器
    metrics.increment("requests_total", tags={"endpoint": "/chat"})

    # 记录直方图
    metrics.observe("request_duration", 0.125, tags={"endpoint": "/chat"})

    # 暴露 /metrics 端点
    @router.get("/metrics")
    async def metrics():
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST
        )
"""

from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable

# Prometheus 客户端
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Summary,
    Info,
    Enum,
    generate_latest,
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    REGISTRY,
)

# OpenTelemetry 集成（可选）
try:
    from opentelemetry.metrics import get_meter
    OTEL_METRICS_AVAILABLE = True
except ImportError:
    OTEL_METRICS_AVAILABLE = False


# ============================================================================
# 预定义指标常量
# ============================================================================

# 服务信息
SERVICE_NAME = "agent-platform"
SERVICE_VERSION = "1.0.0"

# HTTP 请求相关
HTTP_REQUEST_COUNT = "http_requests_total"
HTTP_REQUEST_LATENCY = "http_request_duration_seconds"
HTTP_REQUEST_SIZE = "http_request_size_bytes"
HTTP_RESPONSE_SIZE = "http_response_size_bytes"

# Agent 相关
AGENT_REQUEST_COUNT = "agent_requests_total"
AGENT_EXECUTION_LATENCY = "agent_execution_duration_seconds"
AGENT_TOOL_CALLS = "agent_tool_calls_total"

# 意图检测相关
INTENT_DETECTION_COUNT = "intent_detection_total"
INTENT_DETECTION_LATENCY = "intent_detection_duration_seconds"
INTENT_DETECTION_CONFIDENCE = "intent_detection_confidence"

# LLM 相关
LLM_REQUEST_COUNT = "llm_requests_total"
LLM_REQUEST_LATENCY = "llm_request_duration_seconds"
LLM_TOKEN_PROMPT = "llm_tokens_prompt_total"
LLM_TOKEN_COMPLETION = "llm_tokens_completion_total"
LLM_REQUEST_ERRORS = "llm_request_errors_total"

# RAG 相关
RAG_RETRIEVAL_COUNT = "rag_retrieval_total"
RAG_RETRIEVAL_LATENCY = "rag_retrieval_duration_seconds"
RAG_RETRIEVAL_HITS = "rag_retrieval_hits_total"
RAG_RETRIEVAL_RESULTS = "rag_retrieval_results"

# 业务相关
CONTRACT_REVIEW_COUNT = "contract_review_total"
REPORT_GENERATION_COUNT = "report_generation_total"
HUMAN_REVIEW_COUNT = "human_review_total"
HUMAN_REVIEW_PENDING = "human_review_pending"

# 系统相关
ACTIVE_CONNECTIONS = "active_connections"
ACTIVE_RUNS = "active_runs"
QUEUE_LENGTH = "queue_length"


# ============================================================================
# 指标定义
# ============================================================================

def create_metrics(service_name: str = SERVICE_NAME) -> dict:
    """
    创建所有预定义指标

    为什么在函数里创建？
    - 允许传入不同的 service_name
    - 便于测试时创建独立指标

    Args:
        service_name: 服务名称

    Returns:
        指标字典
    """
    metrics = {}

    # ==================== HTTP 请求指标 ====================

    metrics[HTTP_REQUEST_COUNT] = Counter(
        HTTP_REQUEST_COUNT,
        "Total HTTP requests",
        ["method", "endpoint", "status"],
    )

    metrics[HTTP_REQUEST_LATENCY] = Histogram(
        HTTP_REQUEST_LATENCY,
        "HTTP request latency in seconds",
        ["method", "endpoint"],
        # 桶配置：适用于 HTTP 请求
        buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0),
    )

    # ==================== Agent 指标 ====================

    metrics[AGENT_REQUEST_COUNT] = Counter(
        AGENT_REQUEST_COUNT,
        "Total agent requests",
        ["intent_type", "status"],
    )

    metrics[AGENT_EXECUTION_LATENCY] = Histogram(
        AGENT_EXECUTION_LATENCY,
        "Agent execution latency in seconds",
        ["agent_name", "intent_type"],
        # 桶配置：适用于 Agent 执行
        buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
    )

    metrics[AGENT_TOOL_CALLS] = Counter(
        AGENT_TOOL_CALLS,
        "Total agent tool calls",
        ["agent_name", "tool_name", "status"],
    )

    # ==================== 意图检测指标 ====================

    metrics[INTENT_DETECTION_COUNT] = Counter(
        INTENT_DETECTION_COUNT,
        "Total intent detection requests",
        ["intent_type"],
    )

    metrics[INTENT_DETECTION_LATENCY] = Histogram(
        INTENT_DETECTION_LATENCY,
        "Intent detection latency in seconds",
        ["intent_type"],
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
    )

    metrics[INTENT_DETECTION_CONFIDENCE] = Histogram(
        INTENT_DETECTION_CONFIDENCE,
        "Intent detection confidence distribution",
        ["intent_type"],
        buckets=(0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0),
    )

    # ==================== LLM 指标 ====================

    metrics[LLM_REQUEST_COUNT] = Counter(
        LLM_REQUEST_COUNT,
        "Total LLM requests",
        ["model", "provider", "status"],
    )

    metrics[LLM_REQUEST_LATENCY] = Histogram(
        LLM_REQUEST_LATENCY,
        "LLM request latency in seconds",
        ["model", "provider"],
        # 桶配置：LLM 可能很慢
        buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
    )

    metrics[LLM_TOKEN_PROMPT] = Counter(
        LLM_TOKEN_PROMPT,
        "Total prompt tokens consumed",
        ["model", "provider"],
    )

    metrics[LLM_TOKEN_COMPLETION] = Counter(
        LLM_TOKEN_COMPLETION,
        "Total completion tokens generated",
        ["model", "provider"],
    )

    metrics[LLM_REQUEST_ERRORS] = Counter(
        LLM_REQUEST_ERRORS,
        "Total LLM request errors",
        ["model", "provider", "error_type"],
    )

    # ==================== RAG 指标 ====================

    metrics[RAG_RETRIEVAL_COUNT] = Counter(
        RAG_RETRIEVAL_COUNT,
        "Total RAG retrieval requests",
        ["retrieval_type"],
    )

    metrics[RAG_RETRIEVAL_LATENCY] = Histogram(
        RAG_RETRIEVAL_LATENCY,
        "RAG retrieval latency in seconds",
        ["retrieval_type"],
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    )

    metrics[RAG_RETRIEVAL_HITS] = Counter(
        RAG_RETRIEVAL_HITS,
        "Total RAG retrieval hits",
        ["hit_type"],  # exact, partial, miss
    )

    metrics[RAG_RETRIEVAL_RESULTS] = Histogram(
        RAG_RETRIEVAL_RESULTS,
        "Number of retrieved chunks",
        ["retrieval_type"],
        buckets=(1, 3, 5, 10, 20, 50, 100),
    )

    # ==================== 业务指标 ====================

    metrics[CONTRACT_REVIEW_COUNT] = Counter(
        CONTRACT_REVIEW_COUNT,
        "Total contract reviews",
        ["contract_type", "risk_level", "status"],
    )

    metrics[REPORT_GENERATION_COUNT] = Counter(
        REPORT_GENERATION_COUNT,
        "Total report generations",
        ["report_type", "status"],
    )

    metrics[HUMAN_REVIEW_COUNT] = Counter(
        HUMAN_REVIEW_COUNT,
        "Total human reviews",
        ["action", "risk_level"],
    )

    metrics[HUMAN_REVIEW_PENDING] = Gauge(
        HUMAN_REVIEW_PENDING,
        "Number of pending human reviews",
        ["priority"],
    )

    # ==================== 系统指标 ====================

    metrics[ACTIVE_CONNECTIONS] = Gauge(
        ACTIVE_CONNECTIONS,
        "Number of active connections",
    )

    metrics[ACTIVE_RUNS] = Gauge(
        ACTIVE_RUNS,
        "Number of active agent runs",
    )

    metrics[QUEUE_LENGTH] = Gauge(
        QUEUE_LENGTH,
        "Length of task queue",
        ["queue_name"],
    )

    return metrics


# ============================================================================
# 指标管理器
# ============================================================================

class MetricsManager:
    """
    指标管理器

    提供简洁的指标操作 API，自动处理标签和类型转换。

    为什么需要管理器？
    - 简化 prometheus_client 的使用
    - 统一管理所有指标
    - 提供业务友好的 API

    使用示例：
        metrics = MetricsManager()

        # 记录请求
        metrics.increment(HTTP_REQUEST_COUNT,
            labels={"method": "POST", "endpoint": "/chat", "status": "200"})

        # 记录延迟
        metrics.observe(HTTP_REQUEST_LATENCY, 0.125,
            labels={"method": "POST", "endpoint": "/chat"})

        # 记录 LLM 调用
        metrics.record_llm_call(
            model="gpt-4",
            provider="openai",
            prompt_tokens=100,
            completion_tokens=50,
            duration_ms=500,
        )
    """

    def __init__(self, service_name: str = SERVICE_NAME):
        """
        初始化指标管理器

        Args:
            service_name: 服务名称
        """
        self.service_name = service_name
        self._metrics = create_metrics(service_name)
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
        labels: dict[str, str] | None = None,
    ) -> None:
        """
        增加计数器

        Args:
            name: 指标名称
            value: 增量值
            labels: 标签字典
        """
        if not self._enabled:
            return

        metric = self._metrics.get(name)
        if metric is None:
            return

        if labels:
            metric.labels(**labels).inc(value)
        else:
            metric.inc(value)

    def set(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """
        设置 Gauge 值

        Args:
            name: 指标名称
            value: 值
            labels: 标签字典
        """
        if not self._enabled:
            return

        metric = self._metrics.get(name)
        if metric is None:
            return

        if labels:
            metric.labels(**labels).set(value)
        else:
            metric.set(value)

    def observe(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """
        记录直方图/摘要值

        Args:
            name: 指标名称
            value: 观察值
            labels: 标签字典
        """
        if not self._enabled:
            return

        metric = self._metrics.get(name)
        if metric is None:
            return

        if labels:
            metric.labels(**labels).observe(value)
        else:
            metric.observe(value)

    # ==================== 业务专用方法 ====================

    def record_request(
        self,
        method: str,
        endpoint: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        """
        记录 HTTP 请求

        Args:
            method: HTTP 方法
            endpoint: 请求路径
            status_code: 状态码
            duration_ms: 耗时（毫秒）
        """
        labels = {
            "method": method,
            "endpoint": endpoint,
            "status": str(status_code),
        }

        # 增加计数
        self.increment(HTTP_REQUEST_COUNT, labels=labels)

        # 记录延迟
        self.observe(
            HTTP_REQUEST_LATENCY,
            duration_ms / 1000,  # 转换为秒
            labels={"method": method, "endpoint": endpoint},
        )

    def record_agent_execution(
        self,
        agent_name: str,
        intent_type: str,
        duration_ms: float,
        success: bool = True,
        tool_calls: int = 0,
    ) -> None:
        """
        记录 Agent 执行

        Args:
            agent_name: Agent 名称
            intent_type: 意图类型
            duration_ms: 耗时（毫秒）
            success: 是否成功
            tool_calls: 工具调用次数
        """
        # 增加计数
        self.increment(
            AGENT_REQUEST_COUNT,
            labels={
                "intent_type": intent_type,
                "status": "success" if success else "error",
            },
        )

        # 记录延迟
        self.observe(
            AGENT_EXECUTION_LATENCY,
            duration_ms / 1000,
            labels={"agent_name": agent_name, "intent_type": intent_type},
        )

        # 记录工具调用
        if tool_calls > 0:
            self.increment(
                AGENT_TOOL_CALLS,
                value=tool_calls,
                labels={"agent_name": agent_name, "tool_name": "aggregate", "status": "success"},
            )

    def record_intent_detection(
        self,
        intent_type: str,
        confidence: float,
        duration_ms: float,
    ) -> None:
        """
        记录意图检测

        Args:
            intent_type: 意图类型
            confidence: 置信度
            duration_ms: 耗时（毫秒）
        """
        # 增加计数
        self.increment(INTENT_DETECTION_COUNT, labels={"intent_type": intent_type})

        # 记录延迟
        self.observe(
            INTENT_DETECTION_LATENCY,
            duration_ms / 1000,
            labels={"intent_type": intent_type},
        )

        # 记录置信度分布
        self.observe(
            INTENT_DETECTION_CONFIDENCE,
            confidence,
            labels={"intent_type": intent_type},
        )

    def record_llm_call(
        self,
        model: str,
        provider: str,
        duration_ms: float,
        success: bool = True,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        error_type: str | None = None,
    ) -> None:
        """
        记录 LLM 调用

        Args:
            model: 模型名称
            provider: 提供商
            duration_ms: 耗时（毫秒）
            success: 是否成功
            prompt_tokens: 提示词 Token 数
            completion_tokens: 完成 Token 数
            error_type: 错误类型（如果有）
        """
        status = "success" if success else "error"

        # 增加计数
        self.increment(
            LLM_REQUEST_COUNT,
            labels={"model": model, "provider": provider, "status": status},
        )

        # 记录延迟
        self.observe(
            LLM_REQUEST_LATENCY,
            duration_ms / 1000,
            labels={"model": model, "provider": provider},
        )

        # 记录 Token 消耗
        if prompt_tokens > 0:
            self.increment(
                LLM_TOKEN_PROMPT,
                value=prompt_tokens,
                labels={"model": model, "provider": provider},
            )

        if completion_tokens > 0:
            self.increment(
                LLM_TOKEN_COMPLETION,
                value=completion_tokens,
                labels={"model": model, "provider": provider},
            )

        # 记录错误
        if not success and error_type:
            self.increment(
                LLM_REQUEST_ERRORS,
                labels={"model": model, "provider": provider, "error_type": error_type},
            )

    def record_rag_retrieval(
        self,
        retrieval_type: str,
        duration_ms: float,
        result_count: int,
        hit_type: str | None = None,
    ) -> None:
        """
        记录 RAG 检索

        Args:
            retrieval_type: 检索类型（dense、sparse、hybrid）
            duration_ms: 耗时（毫秒）
            result_count: 检索结果数量
            hit_type: 命中类型（exact、partial、miss）
        """
        # 增加计数
        self.increment(RAG_RETRIEVAL_COUNT, labels={"retrieval_type": retrieval_type})

        # 记录延迟
        self.observe(
            RAG_RETRIEVAL_LATENCY,
            duration_ms / 1000,
            labels={"retrieval_type": retrieval_type},
        )

        # 记录结果数量分布
        self.observe(
            RAG_RETRIEVAL_RESULTS,
            result_count,
            labels={"retrieval_type": retrieval_type},
        )

        # 记录命中类型
        if hit_type:
            self.increment(RAG_RETRIEVAL_HITS, labels={"hit_type": hit_type})

    def record_contract_review(
        self,
        contract_type: str,
        risk_level: str,
        status: str,
    ) -> None:
        """
        记录合同审查

        Args:
            contract_type: 合同类型
            risk_level: 风险等级
            status: 状态
        """
        self.increment(
            CONTRACT_REVIEW_COUNT,
            labels={
                "contract_type": contract_type,
                "risk_level": risk_level,
                "status": status,
            },
        )

    def record_report_generation(
        self,
        report_type: str,
        status: str,
    ) -> None:
        """
        记录报告生成

        Args:
            report_type: 报告类型
            status: 状态
        """
        self.increment(
            REPORT_GENERATION_COUNT,
            labels={"report_type": report_type, "status": status},
        )

    def record_human_review(
        self,
        action: str,
        risk_level: str,
    ) -> None:
        """
        记录人工复核

        Args:
            action: 操作（request、approve、reject）
            risk_level: 风险等级
        """
        self.increment(
            HUMAN_REVIEW_COUNT,
            labels={"action": action, "risk_level": risk_level},
        )

    def set_pending_reviews(
        self,
        priority: str,
        count: int,
    ) -> None:
        """
        设置待复核数量

        Args:
            priority: 优先级（high、medium、low）
            count: 数量
        """
        self.set(HUMAN_REVIEW_PENDING, count, labels={"priority": priority})

    def set_active_connections(self, count: int) -> None:
        """
        设置活跃连接数

        Args:
            count: 连接数
        """
        self.set(ACTIVE_CONNECTIONS, count)

    def set_active_runs(self, count: int) -> None:
        """
        设置活跃运行数

        Args:
            count: 运行数
        """
        self.set(ACTIVE_RUNS, count)

    # ==================== 导出 ====================

    def export(self) -> bytes:
        """
        导出 Prometheus 格式指标

        Returns:
            Prometheus 格式的字节串
        """
        return generate_latest()

    def export_to_string(self) -> str:
        """
        导出 Prometheus 格式指标（字符串）

        Returns:
            Prometheus 格式的字符串
        """
        return generate_latest(REGISTRY).decode("utf-8")


# ============================================================================
# 全局实例
# ============================================================================

_metrics_manager: MetricsManager | None = None


def get_metrics() -> MetricsManager:
    """
    获取全局指标管理器

    Returns:
        MetricsManager 实例
    """
    global _metrics_manager
    if _metrics_manager is None:
        _metrics_manager = MetricsManager()
    return _metrics_manager


# 便捷访问
metrics = get_metrics()


def setup_metrics(service_name: str = SERVICE_NAME) -> MetricsManager:
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
    labels: dict[str, str] | None = None,
) -> Callable:
    """
    延迟追踪装饰器

    自动记录函数执行时间到 Histogram

    为什么需要装饰器？
    - 简化埋点
    - 确保资源正确清理
    - 代码更简洁

    使用示例：
        @track_latency(HTTP_REQUEST_LATENCY, labels={"endpoint": "/chat"})
        async def handle_chat():
            return await process_chat()

    Args:
        metric_name: 指标名称
        labels: 标签
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
                m.observe(metric_name, duration / 1000, labels=labels)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = (time.time() - start_time) * 1000
                m = get_metrics()
                m.observe(metric_name, duration / 1000, labels=labels)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def track_counter(
    metric_name: str,
    labels: dict[str, str] | None = None,
    increment_value: float = 1,
) -> Callable:
    """
    计数器追踪装饰器

    自动在函数调用时增加计数器

    使用示例：
        @track_counter(AGENT_REQUEST_COUNT, labels={"intent_type": "rag_qa"})
        async def rag_agent():
            return await process_rag()

    Args:
        metric_name: 指标名称
        labels: 标签
        increment_value: 增量值
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            m = get_metrics()
            m.increment(metric_name, value=increment_value, labels=labels)
            return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            m = get_metrics()
            m.increment(metric_name, value=increment_value, labels=labels)
            return func(*args, **kwargs)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ============================================================================
# OpenTelemetry Metrics 集成
# ============================================================================

def setup_otel_metrics() -> None:
    """
    设置 OpenTelemetry Metrics

    将 prometheus_client 的指标暴露给 OpenTelemetry

    为什么需要这个？
    - 统一观测平台
    - 可以用 OpenTelemetry 导出器
    - 与 trace 关联
    """
    if not OTEL_METRICS_AVAILABLE:
        return

    meter = get_meter(SERVICE_NAME)

    # TODO: 实现 OpenTelemetry Metrics 与 prometheus_client 的桥接
    # 这需要更复杂的实现，暂时保留为空


# ============================================================================
# 类型别名（兼容旧代码）
# ============================================================================

MetricType = type("MetricType", (), {
    "COUNTER": "counter",
    "GAUGE": "gauge",
    "HISTOGRAM": "histogram",
})
