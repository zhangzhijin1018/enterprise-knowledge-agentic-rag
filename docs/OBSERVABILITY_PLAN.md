# 审计与可观测性规划方案

> 目标：建立完整的 Trace、指标、日志、审计体系，实现"全程可追溯、问题可定位、性能可分析"

---

## 一、现状分析

### 1.1 现有能力

```
✅ 已具备
├── Event Bus 抽象 (core/runtime/events/)
├── trace_id 字段 (LLM 调用、Agent State)
├── 基础日志 (logger.info/error)
└── SQL Audit (经营分析模块)

⚠️ 缺失
├── 统一 Trace 收集
├── 指标采集 (Prometheus)
├── 结构化日志
├── 调用链可视化
├── Audit 持久化
└── 告警规则
```

### 1.2 核心问题

| 问题 | 影响 |
|------|------|
| Trace 散落各处，无法串联 | 定位问题困难 |
| 没有统一指标 | 无法分析系统性能 |
| 日志格式不统一 | 难以搜索和分析 |
| Audit 存储分散 | 难以生成合规报告 |

---

## 二、整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        可观测性架构                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐        │
│  │   Trace     │    │  Metrics    │    │   Logs      │        │
│  │  (调用链)   │    │  (指标)     │    │  (日志)     │        │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘        │
│         │                   │                   │               │
│         └───────────────────┼───────────────────┘               │
│                             │                                   │
│                             ▼                                   │
│                  ┌─────────────────────┐                      │
│                  │   OpenTelemetry SDK  │                      │
│                  │   (统一采集层)        │                      │
│                  └──────────┬──────────┘                      │
│                             │                                   │
│         ┌───────────────────┼───────────────────┐              │
│         │                   │                   │              │
│         ▼                   ▼                   ▼              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐      │
│  │  Jaeger     │    │ Prometheus  │    │  Loki/ELK   │      │
│  │ (Trace存储) │    │ (指标存储)  │    │ (日志存储)  │      │
│  └─────────────┘    └──────┬──────┘    └─────────────┘      │
│                            │                                   │
│                            ▼                                   │
│                   ┌─────────────────┐                         │
│                   │   Grafana       │                         │
│                   │  (可视化平台)   │                         │
│                   └─────────────────┘                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、详细规划

### 3.1 第一阶段：基础设施（1-2周）

#### 3.1.1 统一日志格式

**当前问题：**
```python
# 散乱的日志格式
logger.info(f"查询处理完成，耗时: {time:.2f}s")
logger.error(f"LLM调用失败: {e}")
logger.warning("Reranker 不可用")
```

**目标格式：**
```python
{
    "timestamp": "2026-05-08T16:00:00.000Z",
    "level": "INFO",
    "trace_id": "tr_abc123",
    "run_id": "run_xyz789",
    "service": "agent-service",
    "component": "intent_detector",
    "event": "intent_detected",
    "duration_ms": 45,
    "message": "意图识别完成",
    "extra": {
        "intent_type": "analytics_query",
        "confidence": 0.92
    }
}
```

**实现代码：**

```python
# core/observability/logging.py
"""
统一日志配置模块

提供：
1. 结构化日志输出（JSON格式）
2. trace_id / run_id 自动注入
3. 组件级别的日志分类
"""

import logging
import json
import sys
from datetime import datetime, timezone
from contextvars import ContextVar
from typing import Any

# 上下文变量：自动注入 trace_id 和 run_id
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)


class StructuredLogFormatter(logging.Formatter):
    """结构化日志格式化器"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": "agent-platform",
        }

        # 自动注入 trace_id / run_id
        if trace_id := trace_id_var.get():
            log_data["trace_id"] = trace_id
        if run_id := run_id_var.get():
            log_data["run_id"] = run_id

        # 添加组件信息
        if hasattr(record, "component"):
            log_data["component"] = record.component
        if hasattr(record, "event"):
            log_data["event"] = record.event
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms

        # 添加 extra 字段
        if hasattr(record, "extra"):
            log_data["extra"] = record.extra

        # 添加异常信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


class ComponentLogger:
    """组件日志器"""

    def __init__(self, component: str):
        self.component = component
        self.logger = logging.getLogger(f"agent.{component}")

    def _log(
        self,
        level: int,
        event: str,
        message: str,
        extra: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ):
        """统一日志方法"""
        kwargs = {
            "extra": {
                "component": self.component,
                "event": event,
                **(extra or {}),
            }
        }
        if duration_ms is not None:
            kwargs["extra"]["duration_ms"] = duration_ms

        self.logger.log(level, message, **kwargs)

    def info(self, event: str, message: str, **kwargs):
        self._log(logging.INFO, event, message, **kwargs)

    def error(self, event: str, message: str, **kwargs):
        self._log(logging.ERROR, event, message, **kwargs)

    def warning(self, event: str, message: str, **kwargs):
        self._log(logging.WARNING, event, message, **kwargs)

    def debug(self, event: str, message: str, **kwargs):
        self._log(logging.DEBUG, event, message, **kwargs)


# 便捷函数
def get_logger(component: str) -> ComponentLogger:
    """获取组件日志器"""
    return ComponentLogger(component)


def set_trace_context(trace_id: str | None, run_id: str | None = None):
    """设置 Trace 上下文"""
    trace_id_var.set(trace_id)
    run_id_var.set(run_id)


def setup_logging():
    """初始化日志配置"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredLogFormatter())

    root_logger = logging.getLogger("agent")
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
```

**使用示例：**

```python
from core.observability.logging import get_logger, set_trace_context

# 初始化日志器
logger = get_logger("intent_detector")

# 设置上下文
set_trace_context(trace_id="tr_abc123", run_id="run_xyz789")

# 记录日志
logger.info(
    event="intent_detected",
    message="意图识别完成",
    extra={
        "intent_type": "analytics_query",
        "confidence": 0.92,
    },
    duration_ms=45,
)
```

#### 3.1.2 Trace 基础设施

```python
# core/observability/trace.py
"""
Trace 模块

提供：
1. Span 创建和管理
2. trace_id / span_id 生成
3. 与 OpenTelemetry 集成
"""

from __future__ import annotations

import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from datetime import datetime, timezone

# 上下文变量
current_trace_id: ContextVar[str | None] = ContextVar("current_trace_id", default=None)
current_span_id: ContextVar[str | None] = ContextVar("current_span_id", default=None)


class SpanStatus(Enum):
    """Span 状态"""
    OK = "ok"
    ERROR = "error"
    UNSET = "unset"


@dataclass
class Span:
    """Span 对象"""
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    start_time: datetime
    end_time: datetime | None = None
    status: SpanStatus = SpanStatus.UNSET
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    error: dict | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return None


class Tracer:
    """
    轻量级 Tracer

    可以在：
    1. 直接使用（轻量模式）
    2. 替换为 OpenTelemetry Tracer（生产模式）
    """

    def __init__(self, service_name: str = "agent-platform"):
        self.service_name = service_name

    def start_span(
        self,
        name: str,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        """创建 Span"""
        trace_id = trace_id or current_trace_id.get() or self._generate_trace_id()
        span_id = self._generate_span_id()

        # 设置上下文
        current_trace_id.set(trace_id)
        current_span_id.set(span_id)

        return Span(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id or current_span_id.get(),
            name=name,
            start_time=datetime.now(timezone.utc),
            attributes=attributes or {},
        )

    def end_span(self, span: Span, status: SpanStatus = SpanStatus.OK, error: Exception | None = None):
        """结束 Span"""
        span.end_time = datetime.now(timezone.utc)
        span.status = status

        if error:
            span.status = SpanStatus.ERROR
            span.error = {
                "type": type(error).__name__,
                "message": str(error),
            }

        # 输出 Span（可以发送到 Jaeger / Tempo）
        self._export_span(span)

    def add_span_event(self, span: Span, name: str, attributes: dict[str, Any] | None = None):
        """添加 Span 事件"""
        span.events.append({
            "name": name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attributes": attributes or {},
        })

    def _generate_trace_id(self) -> str:
        return f"tr_{uuid.uuid4().hex[:16]}"

    def _generate_span_id(self) -> str:
        return f"sp_{uuid.uuid4().hex[:8]}"

    def _export_span(self, span: Span):
        """导出 Span 到存储（实现时可替换为 OpenTelemetry）"""
        # TODO: 集成 OpenTelemetry
        import json
        span_data = {
            "trace_id": span.trace_id,
            "span_id": span.span_id,
            "parent_span_id": span.parent_span_id,
            "name": span.name,
            "service": self.service_name,
            "start_time": span.start_time.isoformat(),
            "end_time": span.end_time.isoformat() if span.end_time else None,
            "duration_ms": span.duration_ms,
            "status": span.status.value,
            "attributes": span.attributes,
            "events": span.events,
            "error": span.error,
        }
        # 这里可以发送到 Jaeger / Tempo / Console
        print(f"[TRACE] {json.dumps(span_data)}")


# 全局 Tracer
_tracer: Tracer | None = None


def get_tracer(service_name: str = "agent-platform") -> Tracer:
    """获取 Tracer 实例"""
    global _tracer
    if _tracer is None:
        _tracer = Tracer(service_name)
    return _tracer


# 便捷装饰器
def traced(
    span_name: str | None = None,
    attributes: dict[str, Any] | None = None,
):
    """Span 追踪装饰器"""
    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            tracer = get_tracer()
            name = span_name or f"{func.__module__}.{func.__name__}"
            span = tracer.start_span(name, attributes=attributes)
            try:
                result = await func(*args, **kwargs)
                tracer.end_span(span, SpanStatus.OK)
                return result
            except Exception as e:
                tracer.end_span(span, SpanStatus.ERROR, e)
                raise

        def sync_wrapper(*args, **kwargs):
            tracer = get_tracer()
            name = span_name or f"{func.__module__}.{func.__name__}"
            span = tracer.start_span(name, attributes=attributes)
            try:
                result = func(*args, **kwargs)
                tracer.end_span(span, SpanStatus.OK)
                return result
            except Exception as e:
                tracer.end_span(span, SpanStatus.ERROR, e)
                raise

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
```

**使用示例：**

```python
from core.observability.trace import get_tracer, traced, SpanStatus

tracer = get_tracer()

# 方式1: 手动管理 Span
span = tracer.start_span("intent_detection", attributes={"query_length": len(query)})
try:
    result = detect_intent(query)
    tracer.end_span(span, SpanStatus.OK)
except Exception as e:
    tracer.end_span(span, SpanStatus.ERROR, e)
    raise

# 方式2: 装饰器（自动管理）
@traced(span_name="rag_retrieval")
async def retrieve(query: str, top_k: int = 10):
    # 自动创建和结束 Span
    return await do_retrieval(query, top_k)
```

### 3.2 第二阶段：核心埋点（2-3周）

#### 3.2.1 Agent 执行链路埋点

```python
# core/observability/agent_instrumentation.py
"""
Agent 执行链路埋点

覆盖：
1. Intent Detection
2. Supervisor Dispatch
3. Agent Execution
4. Tool Calling
5. LLM Invocation
"""

from core.observability.trace import get_tracer, SpanStatus, traced
from core.observability.logging import get_logger

logger = get_logger("agent.instrumentation")


class AgentInstrumentation:
    """Agent 执行链路埋点"""

    def __init__(self):
        self.tracer = get_tracer()

    def trace_intent_detection(
        self,
        query: str,
        intent_type: str,
        confidence: float,
        duration_ms: float,
        success: bool = True,
        error: Exception | None = None,
    ):
        """追踪意图识别"""
        span = self.tracer.start_span(
            "intent_detection",
            attributes={
                "query_length": len(query),
                "intent_type": intent_type,
                "confidence": confidence,
            }
        )
        if error:
            self.tracer.end_span(span, SpanStatus.ERROR, error)
        else:
            self.tracer.end_span(span, SpanStatus.OK)

        logger.info(
            event="intent_detection_completed",
            message=f"意图识别完成: {intent_type}",
            extra={
                "intent_type": intent_type,
                "confidence": confidence,
                "duration_ms": duration_ms,
                "success": success,
            },
            duration_ms=duration_ms,
        )

    def trace_agent_execution(
        self,
        agent_name: str,
        intent_type: str,
        duration_ms: float,
        success: bool = True,
        tool_calls: int = 0,
        error: Exception | None = None,
    ):
        """追踪 Agent 执行"""
        span = self.tracer.start_span(
            f"agent.{agent_name}",
            attributes={
                "agent_name": agent_name,
                "intent_type": intent_type,
                "tool_calls_count": tool_calls,
            }
        )
        if error:
            self.tracer.end_span(span, SpanStatus.ERROR, error)
        else:
            self.tracer.end_span(span, SpanStatus.OK)

        logger.info(
            event="agent_execution_completed",
            message=f"Agent 执行完成: {agent_name}",
            extra={
                "agent_name": agent_name,
                "intent_type": intent_type,
                "tool_calls": tool_calls,
                "duration_ms": duration_ms,
                "success": success,
            },
            duration_ms=duration_ms,
        )

    def trace_tool_call(
        self,
        tool_name: str,
        success: bool = True,
        duration_ms: float = 0,
        error: Exception | None = None,
    ):
        """追踪工具调用"""
        self.tracer.add_span_event(
            None,  # 当前 span
            name=f"tool_call.{tool_name}",
            attributes={
                "tool_name": tool_name,
                "success": success,
                "duration_ms": duration_ms,
            }
        )

        logger.info(
            event="tool_call_completed",
            message=f"工具调用完成: {tool_name}",
            extra={
                "tool_name": tool_name,
                "duration_ms": duration_ms,
                "success": success,
            },
            duration_ms=duration_ms,
        )

    def trace_llm_call(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        duration_ms: float,
        success: bool = True,
        error: Exception | None = None,
    ):
        """追踪 LLM 调用"""
        span = self.tracer.start_span(
            "llm.call",
            attributes={
                "llm.model": model,
                "llm.prompt_tokens": prompt_tokens,
                "llm.completion_tokens": completion_tokens,
                "llm.total_tokens": prompt_tokens + completion_tokens,
            }
        )
        if error:
            self.tracer.end_span(span, SpanStatus.ERROR, error)
        else:
            self.tracer.end_span(span, SpanStatus.OK)

        logger.info(
            event="llm_call_completed",
            message=f"LLM 调用完成: {model}",
            extra={
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "duration_ms": duration_ms,
                "success": success,
            },
            duration_ms=duration_ms,
        )


# 全局实例
_agent_instrumentation: AgentInstrumentation | None = None


def get_agent_instrumentation() -> AgentInstrumentation:
    global _agent_instrumentation
    if _agent_instrumentation is None:
        _agent_instrumentation = AgentInstrumentation()
    return _agent_instrumentation
```

#### 3.2.2 审计日志埋点

```python
# core/observability/audit.py
"""
审计日志模块

覆盖：
1. Agent 执行审计
2. Tool 调用审计
3. 数据访问审计
4. 高风险操作审计
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class AuditEventType(Enum):
    """审计事件类型"""
    # Agent 执行
    AGENT_REQUEST = "agent.request"           # Agent 请求
    AGENT_RESPONSE = "agent.response"         # Agent 响应
    AGENT_ERROR = "agent.error"               # Agent 错误

    # 工具调用
    TOOL_INVOCATION = "tool.invocation"       # 工具调用
    TOOL_RESULT = "tool.result"               # 工具结果
    TOOL_ERROR = "tool.error"                 # 工具错误

    # 数据访问
    DATA_QUERY = "data.query"                # 数据查询
    DATA_ACCESS = "data.access"              # 数据访问
    DATA_EXPORT = "data.export"              # 数据导出

    # 高风险操作
    RISK_OPERATION = "risk.operation"         # 高风险操作
    HUMAN_REVIEW_REQUEST = "review.request"   # 人工复核请求
    HUMAN_REVIEW_APPROVE = "review.approve"   # 人工复核通过
    HUMAN_REVIEW_REJECT = "review.reject"     # 人工复核拒绝

    # 安全相关
    AUTH_SUCCESS = "auth.success"             # 认证成功
    AUTH_FAILURE = "auth.failure"            # 认证失败
    PERMISSION_DENIED = "permission.denied"   # 权限拒绝


class RiskLevel(Enum):
    """风险等级"""
    LOW = "low"           # 低风险
    MEDIUM = "medium"     # 中风险
    HIGH = "high"         # 高风险
    CRITICAL = "critical"  # 极高风险


@dataclass
class AuditEvent:
    """审计事件"""
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: AuditEventType
    trace_id: str | None = None
    run_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None

    # 操作信息
    action: str
    resource_type: str | None = None
    resource_id: str | None = None

    # 结果信息
    success: bool = True
    error_message: str | None = None

    # 风险信息
    risk_level: RiskLevel = RiskLevel.LOW
    risk_factors: list[str] = field(default_factory=list)

    # 额外数据
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "success": self.success,
            "error_message": self.error_message,
            "risk_level": self.risk_level.value,
            "risk_factors": self.risk_factors,
            "metadata": self.metadata,
        }


class AuditLogger:
    """
    审计日志记录器

    功能：
    1. 统一记录所有审计事件
    2. 支持多级风险评估
    3. 可扩展存储后端
    """

    def __init__(self):
        self.events: list[AuditEvent] = []

    def log(
        self,
        event_type: AuditEventType,
        action: str,
        trace_id: str | None = None,
        run_id: str | None = None,
        user_id: str | None = None,
        success: bool = True,
        error_message: str | None = None,
        risk_level: RiskLevel = RiskLevel.LOW,
        **metadata,
    ) -> AuditEvent:
        """记录审计事件"""
        event = AuditEvent(
            event_type=event_type,
            action=action,
            trace_id=trace_id,
            run_id=run_id,
            user_id=user_id,
            success=success,
            error_message=error_message,
            risk_level=risk_level,
            metadata=metadata,
        )

        # 存储事件
        self.events.append(event)

        # 如果是高风险事件，需要额外处理
        if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            self._handle_high_risk_event(event)

        # 打印到日志（方便调试）
        import json
        print(f"[AUDIT] {json.dumps(event.to_dict())}")

        return event

    def log_agent_request(
        self,
        action: str,
        trace_id: str | None = None,
        run_id: str | None = None,
        user_id: str | None = None,
        **metadata,
    ):
        """记录 Agent 请求"""
        return self.log(
            event_type=AuditEventType.AGENT_REQUEST,
            action=action,
            trace_id=trace_id,
            run_id=run_id,
            user_id=user_id,
            **metadata,
        )

    def log_tool_invocation(
        self,
        tool_name: str,
        trace_id: str | None = None,
        run_id: str | None = None,
        success: bool = True,
        risk_level: RiskLevel = RiskLevel.LOW,
        **metadata,
    ):
        """记录工具调用"""
        return self.log(
            event_type=AuditEventType.TOOL_INVOCATION,
            action=f"tool.{tool_name}.invoke",
            trace_id=trace_id,
            run_id=run_id,
            success=success,
            resource_type="tool",
            resource_id=tool_name,
            risk_level=risk_level,
            **metadata,
        )

    def log_data_access(
        self,
        data_type: str,
        query: str,
        trace_id: str | None = None,
        run_id: str | None = None,
        user_id: str | None = None,
        risk_level: RiskLevel = RiskLevel.LOW,
        **metadata,
    ):
        """记录数据访问"""
        return self.log(
            event_type=AuditEventType.DATA_ACCESS,
            action=f"data.{data_type}.access",
            trace_id=trace_id,
            run_id=run_id,
            user_id=user_id,
            resource_type=data_type,
            risk_level=risk_level,
            metadata={"query": query, **metadata},
        )

    def log_human_review(
        self,
        action: str,
        review_id: str,
        trace_id: str | None = None,
        run_id: str | None = None,
        reviewer_id: str | None = None,
        success: bool = True,
        **metadata,
    ):
        """记录人工复核"""
        event_type = {
            "request": AuditEventType.HUMAN_REVIEW_REQUEST,
            "approve": AuditEventType.HUMAN_REVIEW_APPROVE,
            "reject": AuditEventType.HUMAN_REVIEW_REJECT,
        }.get(action, AuditEventType.HUMAN_REVIEW_REQUEST)

        return self.log(
            event_type=event_type,
            action=f"review.{action}",
            trace_id=trace_id,
            run_id=run_id,
            user_id=reviewer_id,
            resource_type="review",
            resource_id=review_id,
            success=success,
            risk_level=RiskLevel.HIGH,
            **metadata,
        )

    def _handle_high_risk_event(self, event: AuditEvent):
        """处理高风险事件"""
        # TODO: 发送告警通知
        # 可以发送到 Slack / 邮件 / 钉钉
        print(f"[HIGH RISK ALERT] {event.to_dict()}")


# 全局实例
_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
```

**使用示例：**

```python
from core.observability.audit import (
    get_audit_logger,
    AuditEventType,
    RiskLevel,
)

audit = get_audit_logger()

# 记录 Agent 请求
audit.log_agent_request(
    action="rag.query",
    trace_id="tr_abc123",
    run_id="run_xyz789",
    user_id="user_001",
    intent_type="rag_qa",
    query="集团差旅费报销标准",
)

# 记录工具调用
audit.log_tool_invocation(
    tool_name="rag_search",
    trace_id="tr_abc123",
    success=True,
    metadata={
        "top_k": 10,
        "retrieved_chunks": 5,
    },
)

# 记录数据访问（高风险）
audit.log_data_access(
    data_type="analytics",
    query="SELECT * FROM revenue WHERE ...",
    trace_id="tr_abc123",
    risk_level=RiskLevel.MEDIUM,
    metadata={
        "sql": "...",
        "row_count": 100,
    },
)

# 记录人工复核
audit.log_human_review(
    action="approve",
    review_id="review_001",
    trace_id="tr_abc123",
    reviewer_id="reviewer_001",
)
```

### 3.3 第三阶段：指标采集（1-2周）

#### 3.3.1 Prometheus 指标定义

```python
# core/observability/metrics.py
"""
Prometheus 指标定义

覆盖：
1. 请求指标 (QPS、延迟)
2. Agent 指标 (意图分布、置信度)
3. RAG 指标 (检索质量)
4. LLM 指标 (Token 消耗、延迟)
5. 业务指标 (合同审查数、报告生成数)
"""

from prometheus_client import Counter, Histogram, Gauge, Info
from functools import wraps
import time


# ============================================================================
# Info 指标
# ============================================================================

SERVICE_INFO = Info(
    "agent_platform",
    "Agent Platform Service Information"
)
SERVICE_INFO.info({
    "version": "1.0.0",
    "environment": "production",
})


# ============================================================================
# 请求指标
# ============================================================================

# 请求计数
REQUEST_COUNT = Counter(
    "agent_request_total",
    "Total number of requests",
    ["service", "endpoint", "method", "status"]
)

# 请求延迟
REQUEST_LATENCY = Histogram(
    "agent_request_latency_seconds",
    "Request latency in seconds",
    ["service", "endpoint", "method"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)


# ============================================================================
# Agent 指标
# ============================================================================

# 意图分布
INTENT_DISTRIBUTION = Counter(
    "agent_intent_total",
    "Distribution of intent types",
    ["intent_type"]
)

# 意图置信度
INTENT_CONFIDENCE = Histogram(
    "agent_intent_confidence",
    "Intent detection confidence",
    ["intent_type"],
    buckets=[0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0]
)

# Agent 执行延迟
AGENT_EXECUTION_LATENCY = Histogram(
    "agent_execution_latency_seconds",
    "Agent execution latency",
    ["agent_name", "intent_type"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0]
)


# ============================================================================
# LLM 指标
# ============================================================================

# LLM 调用计数
LLM_CALL_COUNT = Counter(
    "llm_call_total",
    "Total number of LLM calls",
    ["model", "provider", "status"]
)

# Token 消耗
LLM_PROMPT_TOKENS = Counter(
    "llm_prompt_tokens_total",
    "Total prompt tokens consumed",
    ["model", "provider"]
)

LLM_COMPLETION_TOKENS = Counter(
    "llm_completion_tokens_total",
    "Total completion tokens generated",
    ["model", "provider"]
)

# LLM 延迟
LLM_LATENCY = Histogram(
    "llm_latency_seconds",
    "LLM call latency",
    ["model", "provider"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)


# ============================================================================
# RAG 指标
# ============================================================================

# 检索延迟
RAG_RETRIEVAL_LATENCY = Histogram(
    "rag_retrieval_latency_seconds",
    "RAG retrieval latency",
    ["retrieval_type"],  # dense, sparse, hybrid
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
)

# 检索结果数
RAG_RETRIEVAL_COUNT = Histogram(
    "rag_retrieval_count",
    "Number of retrieved chunks",
    ["retrieval_type"],
    buckets=[1, 3, 5, 10, 20, 50, 100]
)

# RAG 命中率（用于评估）
RAG_HIT_RATE = Counter(
    "rag_hit_total",
    "RAG hit rate",
    ["hit_type"]  # exact, partial, miss
)


# ============================================================================
# 业务指标
# ============================================================================

# 合同审查数
CONTRACT_REVIEW_COUNT = Counter(
    "contract_review_total",
    "Total contract reviews",
    ["contract_type", "risk_level", "status"]
)

# 报告生成数
REPORT_GENERATION_COUNT = Counter(
    "report_generation_total",
    "Total reports generated",
    ["report_type", "status"]
)

# 人工复核数
HUMAN_REVIEW_COUNT = Counter(
    "human_review_total",
    "Total human reviews",
    ["action", "risk_level"]  # action: request, approve, reject
)


# ============================================================================
# 高风险指标 (Gauge)
# ============================================================================

# 待复核任务数
PENDING_REVIEW_COUNT = Gauge(
    "human_review_pending",
    "Number of pending human reviews",
    ["priority"]  # high, medium, low
)

# 活跃运行数
ACTIVE_RUNS = Gauge(
    "agent_active_runs",
    "Number of active agent runs"
)


# ============================================================================
# 指标采集装饰器
# ============================================================================

def track_request(service: str, endpoint: str):
    """请求指标追踪装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            status = "success"
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                raise
            finally:
                duration = time.time() - start_time
                REQUEST_COUNT.labels(
                    service=service,
                    endpoint=endpoint,
                    method="POST",
                    status=status
                ).inc()
                REQUEST_LATENCY.labels(
                    service=service,
                    endpoint=endpoint,
                    method="POST"
                ).observe(duration)
        return wrapper
    return decorator


def track_llm_call(model: str, provider: str):
    """LLM 调用追踪装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            status = "success"
            try:
                result = await func(*args, **kwargs)
                # 假设 result 包含 usage 信息
                if hasattr(result, "usage"):
                    LLM_PROMPT_TOKENS.labels(model=model, provider=provider).inc(
                        result.usage.get("prompt_tokens", 0)
                    )
                    LLM_COMPLETION_TOKENS.labels(model=model, provider=provider).inc(
                        result.usage.get("completion_tokens", 0)
                    )
                return result
            except Exception as e:
                status = "error"
                raise
            finally:
                duration = time.time() - start_time
                LLM_CALL_COUNT.labels(
                    model=model,
                    provider=provider,
                    status=status
                ).inc()
                LLM_LATENCY.labels(model=model, provider=provider).observe(duration)
        return wrapper
    return decorator
```

### 3.4 第四阶段：集成与告警（1-2周）

#### 3.4.1 OpenTelemetry 集成

```python
# core/observability/telemetry.py
"""
OpenTelemetry 集成

提供：
1. Trace 导出到 Jaeger/Tempo
2. Metrics 导出到 Prometheus
3. Logs 导出到 Loki
"""

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor


class TelemetryManager:
    """
    Telemetry 管理器

    统一管理 Trace、Metrics、Logs 的初始化和导出
    """

    def __init__(self, service_name: str = "agent-platform"):
        self.service_name = service_name
        self._initialized = False

    def initialize(
        self,
        jaeger_endpoint: str | None = None,
        prometheus_port: int = 9090,
        enable_logging: bool = True,
    ):
        """初始化 Telemetry"""
        if self._initialized:
            return

        resource = Resource.create({
            "service.name": self.service_name,
            "service.version": "1.0.0",
        })

        # 1. 初始化 Trace
        tracer_provider = TracerProvider(resource=resource)

        if jaeger_endpoint:
            jaeger_exporter = JaegerExporter(
                agent_host_name=jaeger_endpoint.split(":")[0],
                agent_port=int(jaeger_endpoint.split(":")[1]) if ":" in jaeger_endpoint else 6831,
            )
            tracer_provider.add_span_processor(
                BatchSpanProcessor(jaeger_exporter)
            )

        trace.set_tracer_provider(tracer_provider)

        # 2. 初始化 Metrics
        prometheus_reader = PrometheusMetricReader()
        meter_provider = MeterProvider(resource=resource, metric_readers=[prometheus_reader])
        metrics.set_meter_provider(meter_provider)

        self._initialized = True

    def instrument_fastapi(self, app):
        """为 FastAPI 添加自动埋点"""
        FastAPIInstrumentor.instrument_app(app)


# 全局实例
_telemetry: TelemetryManager | None = None


def init_telemetry(
    service_name: str = "agent-platform",
    jaeger_endpoint: str | None = None,
    prometheus_port: int = 9090,
):
    """初始化 Telemetry"""
    global _telemetry
    _telemetry = TelemetryManager(service_name)
    _telemetry.initialize(
        jaeger_endpoint=jaeger_endpoint,
        prometheus_port=prometheus_port,
    )
    return _telemetry


def get_telemetry() -> TelemetryManager | None:
    return _telemetry
```

#### 3.4.2 告警规则

```yaml
# prometheus/alerts.yml
groups:
  - name: agent_platform_alerts
    rules:
      # LLM 相关告警
      - alert: LLMHighLatency
        expr: histogram_quantile(0.95, rate(llm_latency_seconds_bucket[5m])) > 5
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "LLM 调用延迟过高"
          description: "P95 延迟超过 5 秒"

      - alert: LLMHighErrorRate
        expr: rate(llm_call_total{status="error"}[5m]) / rate(llm_call_total[5m]) > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "LLM 调用错误率过高"
          description: "错误率超过 5%"

      # Agent 相关告警
      - alert: AgentHighLatency
        expr: histogram_quantile(0.95, rate(agent_execution_latency_seconds_bucket[5m])) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Agent 执行延迟过高"
          description: "P95 延迟超过 10 秒"

      - alert: LowIntentConfidence
        expr: histogram_quantile(0.5, rate(agent_intent_confidence_bucket[5m])) < 0.7
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "意图识别置信度偏低"
          description: "意图识别中位数置信度低于 0.7"

      # RAG 相关告警
      - alert: RAGHighMissRate
        expr: rate(rag_hit_total{hit_type="miss"}[5m]) / rate(rag_hit_total[5m]) > 0.3
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "RAG 命中率偏低"
          description: "RAG 未命中率超过 30%"

      # 业务告警
      - alert: HighRiskReviewPending
        expr: human_review_pending{priority="high"} > 10
        for: 30m
        labels:
          severity: critical
        annotations:
          summary: "高风险复核任务积压"
          description: "高风险复核任务积压超过 10 个，超过 30 分钟未处理"

      - alert: ContractReviewHighRisk
        expr: increase(contract_review_total{risk_level="high"}[1h]) > 20
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "高风险合同审查数增加"
          description: "过去 1 小时高风险合同审查超过 20 个"
```

### 3.5 第五阶段：可视化（1周）

#### 3.5.1 Grafana Dashboard

```json
{
  "dashboard": {
    "title": "Agent Platform 监控大屏",
    "panels": [
      {
        "title": "请求 QPS",
        "type": "timeseries",
        "targets": [
          {
            "expr": "rate(agent_request_total[1m])",
            "legendFormat": "{{endpoint}}"
          }
        ]
      },
      {
        "title": "意图分布",
        "type": "piechart",
        "targets": [
          {
            "expr": "increase(agent_intent_total[1h])",
            "legendFormat": "{{intent_type}}"
          }
        ]
      },
      {
        "title": "LLM Token 消耗",
        "type": "timeseries",
        "targets": [
          {
            "expr": "rate(llm_prompt_tokens_total[5m])",
            "legendFormat": "Prompt"
          },
          {
            "expr": "rate(llm_completion_tokens_total[5m])",
            "legendFormat": "Completion"
          }
        ]
      },
      {
        "title": "调用链 Trace",
        "type": "tracing",
        "targets": [
          {
            "query": "{service=\"agent-platform\"}"
          }
        ]
      }
    ]
  }
}
```

---

## 四、文件结构

```
core/observability/
├── __init__.py
├── logging.py          # 结构化日志
├── trace.py            # Trace 管理
├── metrics.py          # Prometheus 指标
├── audit.py            # 审计日志
├── telemetry.py        # OpenTelemetry 集成
└── README.md           # 使用文档
```

---

## 五、实施计划

| 阶段 | 时间 | 内容 | 优先级 |
|------|------|------|--------|
| **第一阶段** | 1-2周 | 统一日志格式 + Trace 基础设施 | P0 |
| **第二阶段** | 2-3周 | 核心埋点（Agent/LLM/Tool） | P0 |
| **第三阶段** | 1-2周 | Prometheus 指标采集 | P1 |
| **第四阶段** | 1-2周 | OpenTelemetry + 告警规则 | P1 |
| **第五阶段** | 1周 | Grafana Dashboard | P2 |

**建议优先级：**
1. 先把日志和 Trace 做起来（P0）
2. 再做核心埋点（P0）
3. 最后做可视化和告警（P1-P2）

---

## 六、快速开始

```python
# 1. 初始化
from core.observability import init_telemetry, get_audit_logger, get_logger

# 开发环境
init_telemetry(service_name="agent-platform")

# 2. 获取日志器
logger = get_logger("intent_detector")
logger.info("意图识别完成", extra={"intent": "analytics"})

# 3. 记录审计
audit = get_audit_logger()
audit.log_agent_request(action="query", trace_id="tr_123")

# 4. 添加埋点
from core.observability.trace import traced

@traced(span_name="my_function")
async def my_function():
    pass
```

---

需要我帮你实现哪个部分吗？建议从"第一阶段：基础设施"开始，先把日志和 Trace 跑起来。
