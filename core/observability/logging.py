"""结构化日志模块。

该模块使用 structlog 提供企业级结构化日志能力。

为什么用 structlog？
---------------------
structlog 是 Python 结构化日志的事实标准，具有以下优势：

1. **标准化**：社区广泛采用，生产验证
2. **功能完整**：开箱即用的 JSON 输出、上下文绑定、渲染器
3. **性能优秀**：异步友好的设计
4. **易于配置**：声明式配置，无需手写 Formatter
5. **生态集成**：与 logging、OpenTelemetry 无缝集成

对比自研方案：
- 自研：手写 Formatter、Filter、LogRecord，代码量大
- structlog：声明式配置，几行代码搞定

核心概念：
---------
1. BoundLogger：绑定上下文的日志器，自动带上预定义字段
2. Processor：处理器链，控制字段添加、过滤、渲染
3. Renderer：渲染器，将日志转为字符串/JSON
4. Contextvars：异步安全的上下文传递

使用示例：
    from core.observability.logging import get_logger

    # 获取组件日志器
    logger = get_logger("intent_detector")

    # 记录日志（自动带上 trace_id、run_id 等上下文）
    logger.info("意图识别完成",
        intent_type="analytics_query",
        confidence=0.92,
        duration_ms=45
    )

    # 输出格式：
    # {
    #     "event": "意图识别完成",
    #     "intent_type": "analytics_query",
    #     "confidence": 0.92,
    #     "duration_ms": 45,
    #     "trace_id": "tr_abc123",
    #     "logger": "intent_detector",
    #     "timestamp": "2024-01-15T14:30:00.000Z"
    # }

设计原理：
---------
1. 使用 structlog.stdlib.BoundLogger 绑定组件名
2. 通过 structlog.contextvars 绑定 trace_id、run_id 等上下文
3. 生产环境使用 JSONRenderer，开发环境使用 ConsoleRenderer
4. 自动添加 timestamp、log_level 等标准字段
"""

from __future__ import annotations

import logging
import sys
import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

# 导入 structlog 核心组件
import structlog
from structlog.stdlib import (
    BoundLogger,
    LoggerFactory,
    add_log_level,
   Processor,
)
from structlog.types import EventDict, WrappedLogger
from structlog.configuration import Configuration

# 导入上下文管理（用于 trace_id、run_id 传递）
from core.observability.context import (
    get_trace_id,
    get_run_id,
    get_user_id,
    get_conversation_id,
)


# ============================================================================
# 配置常量
# ============================================================================

# 日志级别映射
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

# 是否启用彩色输出（仅开发环境）
ENABLE_COLOR = sys.stdout.isatty() and os.getenv("NO_COLOR") is None


# ============================================================================
# 自定义 Processor（处理器）
# ============================================================================

def add_trace_context_processor(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """
    添加 Trace 上下文的 Processor

    Processor 是 structlog 的核心概念，每个日志调用都会经过处理器链。
    这个处理器自动添加 trace_id、run_id 等上下文字段。

    为什么用 Processor？
    - 日志调用时自动注入，无需手动传参
    - 统一管理，避免遗漏
    - 支持动态获取（如从 contextvars 读取）

    Args:
        logger: 底层日志器（logging.Logger）
        method_name: 日志方法名（info、warning 等）
        event_dict: 事件字典（包含 message、extra 等）

    Returns:
        处理后的事件字典
    """
    # 从 contextvars 获取当前上下文
    trace_id = get_trace_id()
    run_id = get_run_id()
    user_id = get_user_id()
    conversation_id = get_conversation_id()

    # 添加到事件字典
    if trace_id:
        event_dict["trace_id"] = trace_id
    if run_id:
        event_dict["run_id"] = run_id
    if user_id:
        event_dict["user_id"] = user_id
    if conversation_id:
        event_dict["conversation_id"] = conversation_id

    # 添加服务信息
    event_dict["service"] = "agent-platform"

    return event_dict


def rename_event_key_processor(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """
    将 "event" 字段重命名为 "message"

    structlog 默认使用 "event" 作为日志消息字段，
    但很多系统习惯用 "message"。这个 Processor 做转换。

    转换前：{"event": "意图识别完成", "extra": {...}}
    转换后：{"message": "意图识别完成", "extra": {...}}

    Args:
        event_dict: 事件字典

    Returns:
        处理后的事件字典
    """
    # 如果有 event 字段且没有 message 字段，则复制
    if "event" in event_dict and "message" not in event_dict:
        event_dict["message"] = event_dict.pop("event")

    return event_dict


def add_timestamp_processor(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """
    添加 ISO 8601 格式时间戳

    ISO 8601 是日志时间戳的标准格式，便于跨系统解析。

    Args:
        event_dict: 事件字典

    Returns:
        添加 timestamp 字段的事件字典
    """
    event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
    return event_dict


def add_log_level_processor(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """
    添加标准化的日志级别字段

    structlog 自动处理，但这里确保格式统一。

    Args:
        event_dict: 事件字典

    Returns:
        添加 level 字段的事件字典
    """
    event_dict["level"] = method_name.upper()
    return event_dict


def add_source_info_processor(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """
    添加源代码位置信息（仅开发环境）

    便于定位日志来源，但生产环境可能不需要。

    Args:
        event_dict: 事件字典

    Returns:
        添加 source 字段的事件字典
    """
    # 获取调用栈信息
    frame = sys._getframe()
    try:
        # 向上找调用者（通常是 3-4 层）
        for _ in range(4):
            frame = frame.f_back
            if frame is None:
                break

        if frame:
            event_dict["source"] = {
                "file": os.path.basename(frame.f_code.co_filename),
                "line": frame.f_lineno,
                "function": frame.f_code.co_name,
            }
    finally:
        del frame

    return event_dict


# ============================================================================
# 渲染器（Renderer）
# ============================================================================

def console_renderer(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> str:
    """
    控制台彩色渲染器

    开发环境使用，将日志渲染为易读的彩色格式。

    格式：
        [2024-01-15 14:30:00] [INFO] [intent_detector] 意图识别完成
            trace_id: tr_abc123
            intent_type: analytics_query
            confidence: 0.92
            duration_ms: 45

    为什么不用 JSON 格式？
    - JSON 不利于人类阅读
    - 开发时需要快速定位问题
    - 彩色输出便于区分不同级别的日志
    """
    # 颜色代码
    COLORS = {
        "DEBUG": "\033[36m",     # 青色
        "INFO": "\033[32m",      # 绿色
        "WARNING": "\033[33m",   # 黄色
        "ERROR": "\033[31m",     # 红色
        "CRITICAL": "\033[35m",  # 紫色
        "RESET": "\033[0m",
    }

    level = event_dict.pop("level", "INFO")
    timestamp = event_dict.pop("timestamp", "")
    logger_name = event_dict.pop("logger", "")
    component = event_dict.pop("component", logger_name)

    # 颜色
    color = COLORS.get(level, "") if ENABLE_COLOR else ""
    reset = COLORS["RESET"] if ENABLE_COLOR else ""

    # 第一行：基础信息
    lines = [
        f"[{timestamp}] [{color}{level}{reset}] [{component}] {event_dict.get('message', '')}"
    ]

    # trace_id
    if "trace_id" in event_dict:
        lines.append(f"    trace_id: {event_dict.pop('trace_id')}")

    # 其他字段
    for key, value in event_dict.items():
        if key not in ("message", "event"):
            lines.append(f"    {key}: {value}")

    return "\n".join(lines)


def json_renderer(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> str:
    """
    JSON 渲染器

    生产环境使用，输出结构化 JSON，便于日志收集和分析。

    格式：
        {
            "timestamp": "2024-01-15T14:30:00.000Z",
            "level": "INFO",
            "logger": "intent_detector",
            "message": "意图识别完成",
            "trace_id": "tr_abc123",
            "intent_type": "analytics_query",
            "confidence": 0.92
        }

    为什么要用 JSON？
    - 便于日志系统收集和索引（如 ELK、Loki）
    - 便于查询和过滤
    - 便于结构化分析
    """
    import json

    return json.dumps(event_dict, ensure_ascii=False, default=str)


# ============================================================================
# Logger 配置
# ============================================================================

# 全局配置标志
_logging_initialized = False
_service_name = "agent-platform"


def setup_logging(
    service_name: str = "agent-platform",
    level: str = "INFO",
    json_output: bool | None = None,
) -> None:
    """
    初始化 structlog 日志系统

    这是应用启动时必须调用的初始化函数，配置整个日志系统。

    为什么需要初始化？
    - structlog 需要预先配置处理器链
    - 确定是 JSON 输出还是控制台输出
    - 设置日志级别

    Args:
        service_name: 服务名称，用于标识日志来源
        level: 日志级别，可选值：DEBUG、INFO、WARNING、ERROR
        json_output: 是否输出 JSON 格式。
                     None 表示：生产环境（JSON）vs 开发环境（控制台）

    使用示例：
        # 开发环境（自动检测）
        setup_logging()

        # 强制 JSON 输出（生产环境）
        setup_logging(json_output=True)

        # 强制控制台输出（开发调试）
        setup_logging(json_output=False)
    """
    global _logging_initialized, _service_name
    _service_name = service_name

    if _logging_initialized:
        # 避免重复初始化
        return

    # 自动判断输出格式
    # 生产环境（不是 tty 或明确指定）：JSON
    # 开发环境（是 tty 且未指定）：控制台
    if json_output is None:
        json_output = not sys.stdout.isatty()

    # 构建处理器链
    processors = [
        # 1. 添加调用栈位置（开发环境）
        structlog.contextvars.merge_contextvars,
        # 2. 添加 trace 上下文
        add_trace_context_processor,
        # 3. 重命名 event -> message
        rename_event_key_processor,
        # 4. 添加时间戳
        add_timestamp_processor,
        # 5. 添加日志级别
        structlog.stdlib.add_log_level,
        # 6. 添加源代码信息（开发环境）
        structbot_processors,
        # 7. 渲染输出
        console_renderer if not json_output else json_renderer,
    ]

    # 如果是生产环境，移除源代码信息处理器（性能优化）
    if json_output:
        processors = [p for p in processors if p != add_source_info_processor]

    # 配置 structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # 配置标准库 logging
    # 将 structlog 和标准 logging 桥接
    # 这样使用 logging.getLogger() 的代码也能用 structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=LOG_LEVELS.get(level.upper(), logging.INFO),
    )

    # 设置第三方库的日志级别，避免噪音
    # 这些库通常不需要详细的结构化日志
    for lib in ["uvicorn", "uvicorn.access", "fastapi", "httpx", "httpcore"]:
        logging.getLogger(lib).setLevel(logging.WARNING)

    _logging_initialized = True


# 为了避免未使用警告，这里提供一个占位符
# 实际使用时，add_source_info_processor 会被添加到处理器链
structbot_processors = add_source_info_processor


# ============================================================================
# 组件日志器
# ============================================================================

class ComponentLogger:
    """
    组件级日志器

    为每个组件提供独立的日志器实例，自动带上组件名称。

    为什么需要组件日志器？
    - 统一组件的日志格式
    - 便于按组件过滤日志
    - 强制添加 event 字段

    使用示例：
        logger = ComponentLogger("intent_detector")
        logger.info(
            event="意图识别完成",
            intent_type="analytics_query",
            confidence=0.92,
            duration_ms=45
        )

        # 输出：
        # [2024-01-15 14:30:00] [INFO] [intent_detector] 意图识别完成
        #     trace_id: tr_abc123
        #     intent_type: analytics_query
        #     confidence: 0.92
        #     duration_ms: 45
    """

    def __init__(self, component: str):
        """
        初始化组件日志器

        Args:
            component: 组件名称，如 "intent_detector"、"rag_agent" 等
        """
        self.component = component
        # 使用 structlog.get_logger 获取日志器
        # 结构：agent.<component>
        self._logger = structlog.get_logger(f"agent.{component}")

    def _log(
        self,
        level: str,
        event: str,
        message: str | None = None,
        **kwargs: Any,
    ) -> None:
        """
        内部日志方法

        Args:
            level: 日志级别（debug、info、warning、error、critical）
            event: 事件名称（如 "intent_detected"）
            message: 日志消息（可省略，简化为只用 event）
            **kwargs: 额外的结构化字段
        """
        # 如果没有提供 message，使用 event 作为 message
        if message is None:
            message = event

        # 调用 structlog 的方法
        log_method = getattr(self._logger, level, self._logger.info)
        log_method(event, message=message, component=self.component, **kwargs)

    def debug(self, event: str, message: str | None = None, **kwargs: Any) -> None:
        """记录 DEBUG 级别日志"""
        self._log("debug", event, message, **kwargs)

    def info(self, event: str, message: str | None = None, **kwargs: Any) -> None:
        """记录 INFO 级别日志"""
        self._log("info", event, message, **kwargs)

    def warning(self, event: str, message: str | None = None, **kwargs: Any) -> None:
        """记录 WARNING 级别日志"""
        self._log("warning", event, message, **kwargs)

    def error(self, event: str, message: str | None = None, **kwargs: Any) -> None:
        """记录 ERROR 级别日志"""
        self._log("error", event, message, **kwargs)

    def critical(self, event: str, message: str | None = None, **kwargs: Any) -> None:
        """记录 CRITICAL 级别日志"""
        self._log("critical", event, message, **kwargs)

    # ==================== 业务场景专用方法 ====================

    def log_request_start(
        self,
        endpoint: str,
        method: str = "POST",
        **kwargs: Any,
    ) -> None:
        """记录请求开始

        Args:
            endpoint: 请求路径
            method: HTTP 方法
        """
        self.info(
            event="request_start",
            message=f"{method} {endpoint} 开始",
            endpoint=endpoint,
            method=method,
            **kwargs,
        )

    def log_request_end(
        self,
        endpoint: str,
        status_code: int,
        duration_ms: float,
        **kwargs: Any,
    ) -> None:
        """记录请求结束

        Args:
            endpoint: 请求路径
            status_code: HTTP 状态码
            duration_ms: 耗时（毫秒）
        """
        # 根据状态码决定日志级别
        if status_code >= 500:
            self.error(
                event="request_end",
                message=f"{endpoint} 完成，状态码: {status_code}",
                endpoint=endpoint,
                status_code=status_code,
                duration_ms=duration_ms,
                **kwargs,
            )
        elif status_code >= 400:
            self.warning(
                event="request_end",
                message=f"{endpoint} 完成，状态码: {status_code}",
                endpoint=endpoint,
                status_code=status_code,
                duration_ms=duration_ms,
                **kwargs,
            )
        else:
            self.info(
                event="request_end",
                message=f"{endpoint} 完成，状态码: {status_code}",
                endpoint=endpoint,
                status_code=status_code,
                duration_ms=duration_ms,
                **kwargs,
            )

    def log_agent_start(
        self,
        agent_name: str,
        intent_type: str,
        **kwargs: Any,
    ) -> None:
        """记录 Agent 执行开始

        Args:
            agent_name: Agent 名称
            intent_type: 意图类型
        """
        self.info(
            event="agent_start",
            message=f"Agent {agent_name} 开始执行",
            agent_name=agent_name,
            intent_type=intent_type,
            **kwargs,
        )

    def log_agent_end(
        self,
        agent_name: str,
        intent_type: str,
        duration_ms: float,
        success: bool = True,
        **kwargs: Any,
    ) -> None:
        """记录 Agent 执行结束

        Args:
            agent_name: Agent 名称
            intent_type: 意图类型
            duration_ms: 耗时（毫秒）
            success: 是否成功
        """
        if success:
            self.info(
                event="agent_end",
                message=f"Agent {agent_name} 执行成功",
                agent_name=agent_name,
                intent_type=intent_type,
                duration_ms=duration_ms,
                success=success,
                **kwargs,
            )
        else:
            self.error(
                event="agent_end",
                message=f"Agent {agent_name} 执行失败",
                agent_name=agent_name,
                intent_type=intent_type,
                duration_ms=duration_ms,
                success=success,
                **kwargs,
            )

    def log_llm_call(
        self,
        model: str,
        duration_ms: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        """记录 LLM 调用

        Args:
            model: 模型名称
            duration_ms: 耗时（毫秒）
            prompt_tokens: 提示词 Token 数
            completion_tokens: 完成 Token 数
            success: 是否成功
            error: 错误信息
        """
        if success:
            self.info(
                event="llm_call",
                message=f"LLM 调用成功: {model}",
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                duration_ms=duration_ms,
            )
        else:
            self.error(
                event="llm_call",
                message=f"LLM 调用失败: {model}",
                model=model,
                duration_ms=duration_ms,
                error=error,
            )

    def log_tool_call(
        self,
        tool_name: str,
        duration_ms: float,
        success: bool = True,
        error: str | None = None,
        **kwargs: Any,
    ) -> None:
        """记录工具调用

        Args:
            tool_name: 工具名称
            duration_ms: 耗时（毫秒）
            success: 是否成功
            error: 错误信息
        """
        if success:
            self.info(
                event="tool_call",
                message=f"工具调用成功: {tool_name}",
                tool_name=tool_name,
                duration_ms=duration_ms,
                **kwargs,
            )
        else:
            self.warning(
                event="tool_call",
                message=f"工具调用失败: {tool_name}",
                tool_name=tool_name,
                duration_ms=duration_ms,
                error=error,
                **kwargs,
            )


# ============================================================================
# 便捷函数
# ============================================================================

@lru_cache(maxsize=128)
def get_logger(component: str) -> ComponentLogger:
    """
    获取组件日志器

    使用 lru_cache 缓存，同一组件多次调用返回同一实例。

    为什么用 lru_cache？
    - 避免重复创建 Logger 实例
    - 提高性能
    - 内存友好

    Args:
        component: 组件名称

    Returns:
        ComponentLogger 实例

    使用示例：
        logger = get_logger("intent_detector")
        logger.info("意图识别完成", extra={"intent": "analytics"})
    """
    return ComponentLogger(component)


def get_root_logger() -> BoundLogger:
    """
    获取根日志器

    用于需要获取底层 structlog 的场景（通常不需要）。

    Returns:
        structlog BoundLogger
    """
    return structlog.get_logger()


# ============================================================================
# 与标准 logging 的桥接
# ============================================================================

def get_standard_logger(name: str) -> logging.Logger:
    """
    获取标准 logging 日志器

    用于需要使用标准 logging API 的场景（如第三方库桥接）。

    为什么需要桥接？
    - 一些第三方库只接受 logging.Logger
    - 可以将这些日志器桥接到 structlog

    Args:
        name: 日志器名称

    Returns:
        标准 logging.Logger
    """
    return logging.getLogger(name)
