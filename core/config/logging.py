"""日志配置占位模块。

后续会在这里统一定义结构化日志、Trace ID 注入和日志格式配置。
当前仅提供最小占位函数，避免过早引入复杂日志实现。
"""

from typing import Any


def build_logging_config() -> dict[str, Any]:
    """返回基础日志配置占位结构。"""

    return {
        "version": 1,
        "disable_existing_loggers": False,
    }
