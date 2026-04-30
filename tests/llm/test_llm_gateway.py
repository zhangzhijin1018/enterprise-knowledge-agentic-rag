"""LLM Gateway 测试。"""

from __future__ import annotations

from pydantic import BaseModel

from core.llm import LLMMessage, MockLLMGateway


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
