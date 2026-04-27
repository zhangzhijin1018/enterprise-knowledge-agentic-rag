"""日志配置模块。

当前阶段不引入额外日志框架，而是先把最小可用的 Python logging 配置稳定下来。

这样做的目标不是“把日志系统一次性做完”，而是先满足以下工程需求：
1. API 请求至少要有统一的入口日志；
2. 日志级别要能通过配置控制；
3. 后续接入结构化日志、Trace、审计日志时，不需要推翻当前入口。
"""

from __future__ import annotations

from logging.config import dictConfig
from typing import Any

_LOGGING_CONFIGURED = False


def build_logging_config(log_level: str = "INFO") -> dict[str, Any]:
    """返回基础 logging 配置。

    参数：
    - log_level: 根日志级别，例如 INFO、DEBUG、WARNING。

    说明：
    - 当前只保留控制台输出，便于本地开发和最小服务调试；
    - 格式中保留时间、级别、logger 名称和消息体，
      先满足排障可读性，后续再升级为 JSON 结构化日志。
    """

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
            }
        },
        "root": {
            "level": log_level.upper(),
            "handlers": ["console"],
        },
    }


def configure_logging(log_level: str = "INFO") -> None:
    """配置应用基础日志。

    为什么做成幂等：
    - FastAPI app factory 在测试场景中可能被多次创建；
    - 如果每次创建应用都重置 logging，容易导致重复 handler 或污染测试输出；
    - 所以这里采用“本进程只初始化一次”的最小策略。
    """

    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    dictConfig(build_logging_config(log_level=log_level))
    _LOGGING_CONFIGURED = True
