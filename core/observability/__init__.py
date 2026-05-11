"""可观测性模块包。

该模块提供企业级 Agent 平台的可观测性能力，基于主流开源框架实现：

1. **structlog** - 结构化日志
   - JSON 格式输出
   - 自动上下文注入
   - 丰富的处理器链

2. **OpenTelemetry** - 分布式追踪
   - 标准化的 Span 管理
   - 多后端支持（Jaeger/Tempo/Zipkin）
   - 自动埋点支持

3. **prometheus_client** - 指标采集
   - Counter、Gauge、Histogram
   - Prometheus 格式导出
   - Grafana 原生集成

4. **自研审计模块** - 业务审计
   - 事件类型化
   - 风险分级
   - 可扩展导出器

架构设计：
---------
    ┌─────────────────────────────────────────────────────────────┐
    │                    可观测性架构                              │
    ├─────────────────────────────────────────────────────────────┤
    │                                                             │
    │  应用代码                                                    │
    │       │                                                    │
    │       ▼                                                    │
    │  ┌─────────────────────────────────────────────────────┐  │
    │  │              统一 API 层                             │  │
    │  │  get_logger() / get_tracer() / get_metrics()        │  │
    │  └─────────────────────┬───────────────────────────────┘  │
    │                        │                                    │
    │       ┌────────────────┼────────────────┐                 │
    │       │                │                │                  │
    │       ▼                ▼                ▼                  │
    │  ┌──────────┐    ┌──────────┐    ┌──────────┐           │
    │  │ structlog│    │   OTel   │    │ prometh. │           │
    │  │  (日志)  │    │  (追踪)  │    │ (指标)   │           │
    │  └────┬─────┘    └────┬─────┘    └────┬─────┘           │
    │       │                │                │                  │
    │       └────────────────┼────────────────┘                 │
    │                        │                                    │
    │                        ▼                                    │
    │  ┌─────────────────────────────────────────────────────┐  │
    │  │           OpenTelemetry Collector（可选）            │  │
    │  └─────────────────────┬───────────────────────────────┘  │
    │                        │                                    │
    │       ┌────────────────┼────────────────┐                 │
    │       │                │                │                  │
    │       ▼                ▼                ▼                  │
    │  ┌──────────┐    ┌──────────┐    ┌──────────┐           │
    │  │ Grafana  │    │  Tempo   │    │Prometheus│           │
    │  │ Loki面板 │    │ (追踪)   │    │ (指标)   │           │
    │  └──────────┘    └──────────┘    └──────────┘           │
    │                                                             │
    └─────────────────────────────────────────────────────────────┘

使用示例：
---------
```python
# 1. 应用启动时初始化
from core.observability import setup_observability

setup_observability(
    service_name="agent-platform",
    log_level="INFO",
    enable_metrics=True,
)

# 2. 获取日志器
from core.observability import get_logger
logger = get_logger("intent_detector")
logger.info("意图识别完成", intent_type="rag_qa")

# 3. 追踪执行
from core.observability import traced
@traced(span_name="rag_retrieval")
async def retrieve(query: str):
    return await do_retrieval(query)

# 4. 记录审计
from core.observability import audit_log, AuditEventType, RiskLevel
audit_log.log_agent_request(action="query")

# 5. 记录指标
from core.observability import metrics
metrics.record_llm_call(model="gpt-4", duration_ms=500)
```

快速开始：
---------
```bash
# 安装依赖
pip install structlog opentelemetry-api opentelemetry-sdk \
            opentelemetry-exporter-otlp prometheus-client

# 运行服务
# - 日志自动输出 JSON 格式
# - /metrics 端点暴露 Prometheus 指标
# - Span 发送到配置的 OTel Collector
```
"""

from __future__ import annotations

from core.observability.logging import (
    # 初始化
    setup_logging,
    # 日志器
    get_logger,
    get_root_logger,
    ComponentLogger,
)

from core.observability.trace import (
    # Tracer
    get_tracer,
    get_otel_tracer,
    OTelTracer,
    # 装饰器
    traced,
    # Span 管理
    start_span,
    end_span,
    add_event,
    set_attribute,
    get_current_span,
    SpanContext,
    # 类型
    Span,
    SpanKind,
    StatusCode,
    SpanStatus,
    # 配置
    configure_otlp_exporter,
    configure_jaeger_exporter,
)

from core.observability.audit import (
    # 日志记录器
    audit_log,
    get_audit_logger,
    AuditLogger,
    # 事件
    AuditEvent,
    AuditEventType,
    # 风险等级
    RiskLevel,
    # 导出器
    AuditExporter,
    ConsoleAuditExporter,
    DictAuditExporter,
    DatabaseAuditExporter,
    # 便捷函数
    log_audit_event,
)

from core.observability.metrics import (
    # 指标管理器
    metrics,
    get_metrics,
    MetricsManager,
    setup_metrics,
    # 装饰器
    track_latency,
    track_counter,
    # 指标名称常量
    HTTP_REQUEST_COUNT,
    HTTP_REQUEST_LATENCY,
    AGENT_REQUEST_COUNT,
    AGENT_EXECUTION_LATENCY,
    LLM_REQUEST_COUNT,
    LLM_REQUEST_LATENCY,
    LLM_TOKEN_PROMPT,
    LLM_TOKEN_COMPLETION,
    RAG_RETRIEVAL_COUNT,
    RAG_RETRIEVAL_LATENCY,
)

from core.observability.context import (
    # 上下文变量
    get_trace_id,
    get_run_id,
    get_user_id,
    get_conversation_id,
    # 上下文管理
    set_trace_context,
    clear_trace_context,
    TraceContext,
    RequestContext,
    # ID 生成
    generate_trace_id,
    generate_run_id,
    generate_conversation_id,
)


# ============================================================================
# 统一初始化函数
# ============================================================================

def setup_observability(
    service_name: str = "agent-platform",
    log_level: str = "INFO",
    json_logging: bool | None = None,
    enable_metrics: bool = True,
    otlp_endpoint: str | None = None,
    sampling_rate: float = 1.0,
) -> None:
    """
    初始化可观测性模块

    这是应用的统一初始化入口，建议在应用启动时调用一次。

    为什么需要统一初始化？
    - 确保所有组件正确配置
    - 避免遗漏某个组件
    - 便于管理配置

    Args:
        service_name: 服务名称
        log_level: 日志级别（DEBUG、INFO、WARNING、ERROR）
        json_logging: 是否输出 JSON 日志
                        None: 自动判断（开发环境控制台，生产环境 JSON）
                        True: 强制 JSON
                        False: 强制控制台
        enable_metrics: 是否启用指标采集
        otlp_endpoint: OpenTelemetry Collector 端点
                        如 "http://localhost:4317"
                        如果不设置，Span 输出到控制台
        sampling_rate: 采样率（0.0-1.0）

    使用示例：
        # 开发环境
        setup_observability(service_name="agent-platform")

        # 生产环境
        setup_observability(
            service_name="agent-platform",
            log_level="INFO",
            json_logging=True,
            otlp_endpoint="http://otel-collector:4317",
            sampling_rate=0.1,
        )
    """
    # 1. 初始化日志（structlog）
    setup_logging(
        service_name=service_name,
        level=log_level,
        json_output=json_logging,
    )

    # 2. 初始化追踪器（OpenTelemetry）
    if otlp_endpoint:
        # 使用 OTLP 导出器
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    else:
        # 不设置导出器，默认输出到控制台
        exporter = None

    tracer = get_tracer(
        service_name=service_name,
        exporter=exporter,
        sampling_rate=sampling_rate,
    )

    # 3. 初始化指标（prometheus_client）
    if enable_metrics:
        setup_metrics(service_name=service_name)


# ============================================================================
# FastAPI 集成辅助函数
# ============================================================================

def setup_fastapi_instrumentation(app) -> None:
    """
    为 FastAPI 应用添加自动埋点

    自动为所有路由添加：
    - HTTP 请求追踪（OpenTelemetry）
    - 请求指标（prometheus_client）
    - 结构化日志

    Args:
        app: FastAPI 应用实例

    使用示例：
        from fastapi import FastAPI
        from core.observability import setup_observability, setup_fastapi_instrumentation

        app = FastAPI()
        setup_observability()
        setup_fastapi_instrumentation(app)
    """
    # OpenTelemetry FastAPI 自动埋点
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except ImportError:
        pass

    # HTTPX 自动埋点（用于 LLM 调用）
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except ImportError:
        pass


# ============================================================================
# 导出清单
# ============================================================================

__all__ = [
    # ========== 初始化 ==========
    "setup_observability",
    "setup_fastapi_instrumentation",

    # ========== 日志（structlog）==========
    "setup_logging",
    "get_logger",
    "get_root_logger",
    "ComponentLogger",

    # ========== 追踪（OpenTelemetry）==========
    "get_tracer",
    "get_otel_tracer",
    "OTelTracer",
    "traced",
    "start_span",
    "end_span",
    "add_event",
    "set_attribute",
    "get_current_span",
    "SpanContext",
    "Span",
    "SpanKind",
    "StatusCode",
    "SpanStatus",
    "configure_otlp_exporter",
    "configure_jaeger_exporter",

    # ========== 审计 ==========
    "audit_log",
    "get_audit_logger",
    "AuditLogger",
    "AuditEvent",
    "AuditEventType",
    "RiskLevel",
    "AuditExporter",
    "ConsoleAuditExporter",
    "DictAuditExporter",
    "DatabaseAuditExporter",
    "log_audit_event",

    # ========== 指标（prometheus_client）==========
    "metrics",
    "get_metrics",
    "MetricsManager",
    "setup_metrics",
    "track_latency",
    "track_counter",
    "HTTP_REQUEST_COUNT",
    "HTTP_REQUEST_LATENCY",
    "AGENT_REQUEST_COUNT",
    "AGENT_EXECUTION_LATENCY",
    "LLM_REQUEST_COUNT",
    "LLM_REQUEST_LATENCY",
    "LLM_TOKEN_PROMPT",
    "LLM_TOKEN_COMPLETION",
    "RAG_RETRIEVAL_COUNT",
    "RAG_RETRIEVAL_LATENCY",

    # ========== 上下文 ==========
    "get_trace_id",
    "get_run_id",
    "get_user_id",
    "get_conversation_id",
    "set_trace_context",
    "clear_trace_context",
    "TraceContext",
    "RequestContext",
    "generate_trace_id",
    "generate_run_id",
    "generate_conversation_id",
]
