"""可观测性模块包。

该模块提供企业级 Agent 平台的可观测性能力：

1. logging - 结构化日志，统一的日志格式和上下文注入
2. trace - 分布式追踪，完整的调用链追踪
3. audit - 审计日志，安全和合规相关的事件记录
4. metrics - Prometheus 指标采集

使用示例：
    from core.observability import setup_observability

    # 初始化（建议在应用启动时调用一次）
    setup_observability(
        service_name="agent-platform",
        log_level="INFO"
    )

    # 获取日志器
    from core.observability.logging import get_logger
    logger = get_logger("intent_detector")
    logger.info("意图识别完成", extra={"intent": "analytics"})

    # 追踪执行
    from core.observability.trace import traced
    @traced(span_name="my_function")
    async def my_function():
        pass

    # 记录审计
    from core.observability.audit import audit_log, AuditEventType
    audit_log.log_agent_request(action="query", trace_id="tr_123")
"""

from core.observability.logging import (
    setup_logging,
    get_logger,
    set_trace_context,
    ComponentLogger,
)

from core.observability.trace import (
    get_tracer,
    traced,
    Span,
    SpanStatus,
    Tracer,
)

from core.observability.audit import (
    audit_log,
    AuditEventType,
    RiskLevel,
    AuditLogger,
    AuditEvent,
)

from core.observability.metrics import (
    metrics,
    track_latency,
    track_counter,
    setup_metrics,
)

from core.observability.context import (
    get_trace_id,
    get_run_id,
    set_trace_context,
    clear_trace_context,
    TraceContext,
)


def setup_observability(
    service_name: str = "agent-platform",
    log_level: str = "INFO",
    enable_metrics: bool = True,
):
    """
    初始化可观测性模块（建议在应用启动时调用一次）

    Args:
        service_name: 服务名称，用于标识日志和追踪的来源
        log_level: 日志级别，可选值：DEBUG, INFO, WARNING, ERROR
        enable_metrics: 是否启用指标采集
    """
    # 1. 初始化日志
    setup_logging(service_name=service_name, level=log_level)

    # 2. 初始化追踪器
    get_tracer(service_name=service_name)

    # 3. 初始化指标
    if enable_metrics:
        setup_metrics(service_name=service_name)


__all__ = [
    # 日志
    "setup_logging",
    "get_logger",
    "set_trace_context",
    "ComponentLogger",
    # 追踪
    "get_tracer",
    "traced",
    "Span",
    "SpanStatus",
    "Tracer",
    # 审计
    "audit_log",
    "AuditEventType",
    "RiskLevel",
    "AuditLogger",
    "AuditEvent",
    # 指标
    "metrics",
    "track_latency",
    "track_counter",
    "setup_metrics",
    # 上下文
    "get_trace_id",
    "get_run_id",
    "set_trace_context",
    "clear_trace_context",
    "TraceContext",
    # 统一初始化
    "setup_observability",
]
