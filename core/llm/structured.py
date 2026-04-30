"""LLM 结构化输出解析工具。"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from core.common import error_codes
from core.common.exceptions import AppException

T = TypeVar("T", bound=BaseModel)


def parse_structured_json(content: str, output_schema: type[T]) -> T:
    """把模型输出解析成 Pydantic 结构化对象。

    LLM 即使被 prompt 约束为 JSON，也可能包一层 Markdown code block。
    这里做最小、可控的提取和校验：
    - 只接受 JSON object；
    - 解析失败统一抛 AppException；
    - 后续业务只能拿到 Pydantic 对象，而不是自由文本。
    """

    candidate = _extract_json_object(content)
    try:
        payload = json.loads(candidate)
        return output_schema.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise AppException(
            error_code=error_codes.ANALYTICS_QUERY_FAILED,
            message="LLM 结构化输出解析失败",
            status_code=502,
            detail={"reason": str(exc)},
        ) from exc


def _extract_json_object(content: str) -> str:
    """提取 JSON object 文本。

    这个函数不做复杂自然语言修复，原因是结构化输出失败应该被观测到，
    而不是在业务层悄悄猜测模型原意。
    """

    text = (content or "").strip()
    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    if fenced_match:
        return fenced_match.group(1)
    if text.startswith("{") and text.endswith("}"):
        return text
    json_match = re.search(r"(\{.*\})", text, flags=re.S)
    if json_match:
        return json_match.group(1)
    return text
