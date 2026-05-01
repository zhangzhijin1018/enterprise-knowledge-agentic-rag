"""LLM Gateway 测试。"""

from __future__ import annotations

from pydantic import BaseModel

import pytest

from core.common import error_codes
from core.common.exceptions import AppException
from core.config.settings import Settings
from core.llm import LLMMessage, MockLLMGateway, OpenAICompatibleLLMGateway


class DemoStructuredOutput(BaseModel):
    """测试用结构化输出。"""

    answer: str
    confidence: float


def test_mock_llm_gateway_returns_structured_output() -> None:
    """MockLLMGateway 应支持离线结构化输出解析。"""

    gateway = MockLLMGateway(
        structured_payload={
            "answer": "ok",
            "confidence": 0.9,
        }
    )

    result = gateway.structured_output(
        messages=[LLMMessage(role="user", content="返回 JSON")],
        output_schema=DemoStructuredOutput,
    )

    assert result.answer == "ok"
    assert result.confidence == 0.9
    assert len(gateway.calls) == 1


def test_mock_llm_gateway_records_trace_and_metadata() -> None:
    """LLM 调用应保留 trace 与 metadata，便于后续审计扩展。"""

    gateway = MockLLMGateway(response_content='{"answer":"ok","confidence":1}')

    gateway.chat(
        messages=[LLMMessage(role="user", content="hello")],
        trace_id="tr_test",
        metadata={"component": "unit_test"},
    )

    assert gateway.calls[0].trace_id == "tr_test"
    assert gateway.calls[0].metadata["component"] == "unit_test"


def test_mock_llm_gateway_returns_lightweight_call_metadata() -> None:
    """LLM 响应 metadata 只应包含轻量调用摘要，不保存完整 prompt。"""

    gateway = MockLLMGateway(response_content='{"answer":"ok","confidence":1}')

    response = gateway.chat(
        messages=[LLMMessage(role="user", content="这里是完整 prompt，不应进入 trace metadata")],
        trace_id="tr_meta",
        metadata={
            "run_id": "run_1",
            "component": "unit_test",
            "prompt_name": "analytics/demo",
            "prompt_version": "v1",
            "output_schema": "DemoStructuredOutput",
        },
    )

    llm_call = response.metadata["llm_call"]
    assert llm_call["trace_id"] == "tr_meta"
    assert llm_call["run_id"] == "run_1"
    assert llm_call["prompt_name"] == "analytics/demo"
    assert llm_call["output_schema"] == "DemoStructuredOutput"
    assert llm_call["success"] is True
    assert "完整 prompt" not in str(llm_call)


def test_openai_compatible_gateway_requires_api_key() -> None:
    """未配置真实 API Key 时应返回统一 LLM 调用错误，而不是访问外网。"""

    gateway = OpenAICompatibleLLMGateway(settings=Settings(llm_api_key="your-api-key"))

    with pytest.raises(AppException) as exc_info:
        gateway.chat(messages=[LLMMessage(role="user", content="hello")])

    assert exc_info.value.error_code == error_codes.LLM_CALL_FAILED
