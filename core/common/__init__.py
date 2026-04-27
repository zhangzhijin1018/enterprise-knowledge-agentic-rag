"""公共基础能力包。

该包用于承载跨 API、Service、Repository 复用的基础能力，
例如统一响应、统一异常、通用工具函数等。
"""

from core.common import error_codes
from core.common.exceptions import AppException
from core.common.response import build_error_response, build_success_response

__all__ = [
    "error_codes",
    "AppException",
    "build_success_response",
    "build_error_response",
]
