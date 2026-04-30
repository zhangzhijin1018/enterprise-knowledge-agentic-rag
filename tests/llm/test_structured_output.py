"""LLM 结构化输出解析测试。"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from core.common import error_codes
from core.common.exceptions import AppException
from core.llm.structured import parse_structured_json


class DemoOutput(BaseModel):
    """测试用结构化输出。"""

    answer: str
    confidence: float


def test_parse_structured_json_reports_parse_error() -> None:
    """非法 JSON 应返回明确的解析错误码。"""

    with pytest.raises(AppException) as exc_info:
        parse_structured_json("不是 JSON", DemoOutput)

    assert exc_info.value.error_code == error_codes.LLM_OUTPUT_PARSE_FAILED


def test_parse_structured_json_reports_validation_error() -> None:
    """JSON 合法但不符合 Schema 时，应返回明确的校验错误码。"""

    with pytest.raises(AppException) as exc_info:
        parse_structured_json('{"answer": "ok"}', DemoOutput)

    assert exc_info.value.error_code == error_codes.LLM_OUTPUT_VALIDATION_FAILED
