"""结构化日志模块。

该模块提供统一的日志格式和组件级日志分类。

核心设计：
---------
1. 结构化输出（JSON 格式），便于日志收集和分析
2. 自动注入 trace_id、run_id 等上下文
3. 组件级日志分类，便于定位问题
4. 支持多级别日志（DEBUG、INFO、WARNING、ERROR）

为什么需要结构化日志？
---------------------
传统日志格式：
    2024-01-15 14:30:00 INFO - 意图识别完成

问题：
- 无法按字段搜索（如只查看某个 trace_id 的日志）
- 难以和其他系统集成
- 日志分析困难

结构化日志格式：
    {
        "timestamp": "2024-01-15T14:30:00.000Z",
        "level": "INFO",
        "trace_id": "tr_abc123",
        "run_id": "run_xyz789",
        "component": "intent_detector",
        "event": "intent_detected",
        "message": "意图识别完成",
        "extra": {
            "intent_type": "analytics_query",
            "confidence": 0.92
        }
    }

优点：
- 可以按任意字段搜索和过滤
- 可以和 Elasticsearch/Loki 无缝集成
- 可以生成结构化报表
- 便于 Trace 关联

使用示例：
    from core.observability.logging import setup_logging, get_logger

    # 初始化（应用启动时调用一次）
    setup_logging(service_name="agent-platform")

    # 获取组件日志器
    logger = get_logger("intent_detector")

    # 记录日志
    logger.info(
        event="intent_detected",
        message="意图识别完成",
        extra={
            "intent_type": "analytics_query",
            "confidence": 0.92,
        },
        duration_ms=45
    )
"""

from __future__ import annotations

import logging
import json
import sys
import os
from datetime import datetime, timezone
from typing import Any, Optional
from functools import lru_cache

from core.observability.context import (
    get_trace_id,
    get_run_id,
    get_user_id,
    get_conversation_id,
)

# ============================================================================
# 日志级别映射
# ============================================================================

# Python logging 级别到字符串的映射
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

# 颜色代码（用于终端彩色输出）
COLOR_CODES = {
    "DEBUG": "\033[36m",     # 青色
    "INFO": "\033[32m",      # 绿色
    "WARNING": "\033[33m",    # 黄色
    "ERROR": "\033[31m",     # 红色
    "CRITICAL": "\033[35m",  # 紫色
    "RESET": "\033[0m",
}

# 是否启用彩色输出
ENABLE_COLOR = sys.stdout.isatty() and os.getenv("NO_COLOR") is None


# ============================================================================
# 自定义日志格式化器
# ============================================================================

class StructuredLogFormatter(logging.Formatter):
    """
    结构化日志格式化器

    功能：
    1. 输出 JSON 格式日志
    2. 自动注入 trace_id、run_id 等上下文
    3. 支持终端彩色输出

    设计原理：
    ----------
    logging.Formatter 是 Python 日志系统的核心组件，
    负责将 LogRecord 转换为字符串。
    """

    def __init__(self, service_name: str = "agent-platform"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        """
        格式化日志记录

        Args:
            record: Python logging.LogRecord 对象

        Returns:
            格式化的日志字符串
        """
        # 构建日志数据结构
        log_data = {
            # 时间戳（ISO 8601 格式）
            "timestamp": datetime.now(timezone.utc).isoformat(),

            # 日志级别
            "level": record.levelname,

            # 服务信息
            "service": self.service_name,
            "logger": record.name,

            # 核心消息
            "message": record.getMessage(),

            # 上下文信息（从 contextvars 获取）
            "trace_id": get_trace_id(),
            "run_id": get_run_id(),
            "conversation_id": get_conversation_id(),
            "user_id": get_user_id(),
        }

        # 添加组件信息（通过 extra 传递）
        if hasattr(record, "component"):
            log_data["component"] = record.component
        if hasattr(record, "event"):
            log_data["event"] = record.event
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms

        # 添加额外数据（通过 extra 传递）
        if hasattr(record, "extra_data"):
            log_data["extra"] = record.extra_data

        # 添加异常信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # 添加源代码信息（调试时有用）
        if record.pathname:
            log_data["source"] = {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            }

        # 返回 JSON 格式
        return json.dumps(log_data, ensure_ascii=False, default=str)


class ColoredConsoleFormatter(logging.Formatter):
    """
    彩色控制台格式化器

    用于开发环境，提供易读的彩色输出

    格式：
        [2024-01-15 14:30:00] [INFO] [intent_detector] 意图识别完成
            trace_id: tr_abc123
            intent_type: analytics_query
            confidence: 0.92
    """

    def format(self, record: logging.LogRecord) -> str:
        # 基础信息行
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        level = record.levelname
        component = getattr(record, "component", record.name)

        # 颜色
        color = COLOR_CODES.get(level, "") if ENABLE_COLOR else ""
        reset = COLOR_CODES["RESET"] if ENABLE_COLOR else ""

        # 第一行：基础信息
        lines = [
            f"[{timestamp}] [{color}{level}{reset}] [{component}] {record.getMessage()}"
        ]

        # 第二行：trace_id
        trace_id = get_trace_id()
        if trace_id:
            lines.append(f"    trace_id: {trace_id}")

        # 第三行：duration_ms
        if hasattr(record, "duration_ms"):
            lines.append(f"    duration_ms: {record.duration_ms:.2f}")

        # 第四行：extra 数据
        if hasattr(record, "extra_data") and record.extra_data:
            for key, value in record.extra_data.items():
                lines.append(f"    {key}: {value}")

        # 异常信息
        if record.exc_info:
            lines.append(f"    exception: {self.formatException(record.exc_info)}")

        return "\n".join(lines)


# ============================================================================
# 自定义 LogRecord
# ============================================================================

class StructuredLogRecord(logging.LogRecord):
    """
    自定义日志记录

    通过 extra 属性传递额外的结构化数据
    """

    def __init__(self, *args, **kwargs):
        # 提取自定义字段
        self.component = kwargs.pop("component", None)
        self.event = kwargs.pop("event", None)
        self.duration_ms = kwargs.pop("duration_ms", None)
        self.extra_data = kwargs.pop("extra", {})

        super().__init__(*args, **kwargs)


# ============================================================================
# 组件日志器
# ============================================================================

class ComponentLogger:
    """
    组件级日志器

    功能：
    1. 为组件提供统一的日志接口
    2. 自动带上组件名称
    3. 支持结构化额外数据

    设计原理：
    ---------
    传统 logger.warning("意图识别完成") 只输出文本，
    ComponentLogger 提供了：
    - 统一的日志格式
    - 结构化的 extra 数据
    - 便于追踪的 event 字段

    使用示例：
        logger = ComponentLogger("intent_detector")
        logger.info(
            event="intent_detected",
            message="意图识别完成",
            extra={"intent_type": "rag_qa", "confidence": 0.95}
        )
    """

    def __init__(self, component: str):
        """
        初始化组件日志器

        Args:
            component: 组件名称，如 "intent_detector"、"rag_agent" 等
        """
        self.component = component
        # 使用 "agent.{component}" 作为 logger name
        self.logger = logging.getLogger(f"agent.{component}")

    def _log(
        self,
        level: int,
        event: str,
        message: str,
        extra: dict[str, Any] | None = None,
        duration_ms: float | None = None,
        exc_info: bool = False,
    ) -> None:
        """
        内部日志方法

        Args:
            level: 日志级别
            event: 事件名称（如 "intent_detected"）
            message: 日志消息
            extra: 额外的结构化数据
            duration_ms: 执行时长（毫秒）
            exc_info: 是否包含异常信息
        """
        # 构建 kwargs
        kwargs = {
            "extra": {
                "component": self.component,
                "event": event,
                **(extra or {}),
            }
        }

        if duration_ms is not None:
            kwargs["extra"]["duration_ms"] = duration_ms

        # 记录日志
        self.logger.log(
            level,
            message,
            exc_info=exc_info,
            component=self.component,
            event=event,
            extra_data=extra,
            duration_ms=duration_ms,
        )

    def debug(
        self,
        event: str,
        message: str,
        extra: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """记录 DEBUG 级别日志"""
        self._log(logging.DEBUG, event, message, extra, duration_ms)

    def info(
        self,
        event: str,
        message: str,
        extra: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """记录 INFO 级别日志"""
        self._log(logging.INFO, event, message, extra, duration_ms)

    def warning(
        self,
        event: str,
        message: str,
        extra: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """记录 WARNING 级别日志"""
        self._log(logging.WARNING, event, message, extra, duration_ms)

    def error(
        self,
        event: str,
        message: str,
        extra: dict[str, Any] | None = None,
        duration_ms: float | None = None,
        exc_info: bool = True,
    ) -> None:
        """记录 ERROR 级别日志"""
        self._log(logging.ERROR, event, message, extra, duration_ms, exc_info)

    def critical(
        self,
        event: str,
        message: str,
        extra: dict[str, Any] | None = None,
        duration_ms: float | None = None,
        exc_info: bool = True,
    ) -> None:
        """记录 CRITICAL 级别日志"""
        self._log(logging.CRITICAL, event, message, extra, duration_ms, exc_info)

    # ==================== 业务场景专用方法 ====================

    def log_request_start(
        self,
        endpoint: str,
        method: str = "POST",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """记录请求开始"""
        self.info(
            event="request_start",
            message=f"{method} {endpoint} 开始",
            extra={"endpoint": endpoint, "method": method, **(extra or {})},
        )

    def log_request_end(
        self,
        endpoint: str,
        status_code: int,
        duration_ms: float,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """记录请求结束"""
        level = logging.INFO if status_code < 400 else logging.WARNING
        event = "request_end"
        self._log(
            level,
            event,
            f"{endpoint} 完成，状态码: {status_code}",
            extra={"endpoint": endpoint, "status_code": status_code, **(extra or {})},
            duration_ms=duration_ms,
        )

    def log_agent_start(
        self,
        agent_name: str,
        intent_type: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """记录 Agent 执行开始"""
        self.info(
            event="agent_start",
            message=f"Agent {agent_name} 开始执行",
            extra={"agent_name": agent_name, "intent_type": intent_type, **(extra or {})},
        )

    def log_agent_end(
        self,
        agent_name: str,
        intent_type: str,
        duration_ms: float,
        success: bool = True,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """记录 Agent 执行结束"""
        level = logging.INFO if success else logging.ERROR
        event = "agent_end"
        self._log(
            level,
            event,
            f"Agent {agent_name} 执行{'成功' if success else '失败'}",
            extra={
                "agent_name": agent_name,
                "intent_type": intent_type,
                "success": success,
                **(extra or {}),
            },
            duration_ms=duration_ms,
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
        """记录 LLM 调用"""
        level = logging.INFO if success else logging.ERROR
        self._log(
            level,
            "llm_call",
            f"LLM 调用 {'成功' if success else '失败'}: {model}",
            extra={
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "error": error,
            },
            duration_ms=duration_ms,
        )

    def log_tool_call(
        self,
        tool_name: str,
        duration_ms: float,
        success: bool = True,
        error: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """记录工具调用"""
        level = logging.INFO if success else logging.WARNING
        self._log(
            level,
            "tool_call",
            f"工具调用 {'成功' if success else '失败'}: {tool_name}",
            extra={
                "tool_name": tool_name,
                "error": error,
                **(extra or {}),
            },
            duration_ms=duration_ms,
        )


# ============================================================================
# 全局配置
# ============================================================================

# 全局日志配置
_logging_initialized = False
_service_name = "agent-platform"


def setup_logging(
    service_name: str = "agent-platform",
    level: str = "INFO",
    enable_console_colors: bool = True,
) -> None:
    """
    初始化日志系统

    建议在应用启动时调用一次

    Args:
        service_name: 服务名称
        level: 日志级别
        enable_console_colors: 是否启用控制台彩色输出

    使用示例：
        setup_logging(
            service_name="agent-platform",
            level="INFO"
        )
    """
    global _logging_initialized, _service_name
    _service_name = service_name

    if _logging_initialized:
        return

    # 创建根日志器
    root_logger = logging.getLogger("agent")
    root_logger.setLevel(LOG_LEVELS.get(level.upper(), logging.INFO))

    # 清除已有的 handlers
    root_logger.handlers.clear()

    # 创建控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(LOG_LEVELS.get(level.upper(), logging.INFO))

    # 选择格式化器
    if enable_console_colors and sys.stdout.isatty():
        formatter = ColoredConsoleFormatter()
    else:
        formatter = StructuredLogFormatter(service_name=service_name)

    console_handler.setFormatter(formatter)

    # 添加处理器
    root_logger.addHandler(console_handler)

    # 防止日志传播到 root logger
    root_logger.propagate = False

    # 注册自定义 LogRecord 工厂
    logging.setLogRecordFactory(StructuredLogRecord)

    _logging_initialized = True


@lru_cache(maxsize=128)
def get_logger(component: str) -> ComponentLogger:
    """
    获取组件日志器

    使用 lru_cache 缓存，同一组件多次调用返回同一实例

    Args:
        component: 组件名称

    Returns:
        ComponentLogger 实例

    使用示例：
        logger = get_logger("intent_detector")
        logger.info("意图识别完成")
    """
    return ComponentLogger(component)


def get_root_logger() -> logging.Logger:
    """获取根日志器"""
    return logging.getLogger("agent")


# ============================================================================
# 便捷函数
# ============================================================================

def log_entry_exit(func):
    """
    函数入口/出口日志装饰器

    自动记录函数的执行时间和状态

    使用示例：
        @log_entry_exit
        def my_function():
            pass
    """
    import time
    import functools

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        logger.debug(
            event="function_entry",
            message=f"进入函数: {func.__name__}",
        )

        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            duration_ms = (time.time() - start_time) * 1000
            logger.debug(
                event="function_exit",
                message=f"退出函数: {func.__name__}",
                duration_ms=duration_ms,
            )
            return result
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                event="function_error",
                message=f"函数异常: {func.__name__}: {e}",
                duration_ms=duration_ms,
                exc_info=True,
            )
            raise

    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        logger.debug(
            event="function_entry",
            message=f"进入异步函数: {func.__name__}",
        )

        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            duration_ms = (time.time() - start_time) * 1000
            logger.debug(
                event="function_exit",
                message=f"退出异步函数: {func.__name__}",
                duration_ms=duration_ms,
            )
            return result
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                event="function_error",
                message=f"异步函数异常: {func.__name__}: {e}",
                duration_ms=duration_ms,
                exc_info=True,
            )
            raise

    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper
