"""统一 LLM Gateway。

业务代码不能直接调用具体模型 SDK，原因是：
1. 模型供应商会变化，业务层不应该跟着改；
2. 超时、重试、trace、结构化输出和审计需要统一治理；
3. 测试环境不能强依赖真实外部 API key。

因此本模块提供：
- `LLMGateway` 抽象接口；
- `OpenAICompatibleLLMGateway` 生产接入骨架；
- `MockLLMGateway` 单元测试和本地开发用实现。
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any, TypeVar
from urllib import error, request

from pydantic import BaseModel

from core.common import error_codes
from core.common.exceptions import AppException
from core.config.settings import Settings, get_settings
from core.llm.models import LLMCallMetadata, LLMMessage, LLMRequest, LLMResponse
from core.llm.structured import parse_structured_json

T = TypeVar("T", bound=BaseModel)


class LLMGateway(ABC):
    """LLM 网关抽象接口。"""

    @abstractmethod
    def chat(
        self,
        *,
        messages: list[LLMMessage],
        model: str | None = None,
        timeout_seconds: int | None = None,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """执行 Chat 调用。"""

    def generate(
        self,
        *,
        prompt: str,
        model: str | None = None,
        timeout_seconds: int | None = None,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """执行单 prompt 生成。

        当前内部复用 chat，保持接口稳定；未来如果某些私有化服务有
        completion-only 接口，可以在具体 Gateway 中覆盖。
        """

        return self.chat(
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
            timeout_seconds=timeout_seconds,
            trace_id=trace_id,
            metadata=metadata,
        )

    def structured_output(
        self,
        *,
        messages: list[LLMMessage],
        output_schema: type[T],
        model: str | None = None,
        timeout_seconds: int | None = None,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> T:
        """生成并解析结构化输出。

        业务层最终只能拿到 Pydantic 对象，不能直接把自由文本当成执行指令。
        对经营分析来说，这一点尤其重要：LLM 可以辅助规划，但不能直接生成 SQL。
        """

        structured_metadata = dict(metadata or {})
        structured_metadata.setdefault("output_schema", output_schema.__name__)
        response = self.chat(
            messages=messages,
            model=model,
            timeout_seconds=timeout_seconds,
            trace_id=trace_id,
            metadata=structured_metadata,
        )
        return parse_structured_json(response.content, output_schema)


class OpenAICompatibleLLMGateway(LLMGateway):
    """OpenAI-compatible LLM Gateway 最小实现骨架。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def chat(
        self,
        *,
        messages: list[LLMMessage],
        model: str | None = None,
        timeout_seconds: int | None = None,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """调用 OpenAI-compatible `/chat/completions` 接口。

        这里使用标准库 urllib，避免为了本轮骨架引入额外重型依赖。
        生产环境可在这个类内部替换为更完整的 HTTP client、重试和审计实现。
        """

        resolved_model = model or self.settings.llm_model_name
        resolved_timeout = timeout_seconds or self.settings.llm_timeout_seconds
        started_at = time.monotonic()
        if not self.settings.llm_api_key or self.settings.llm_api_key == "your-api-key":
            raise AppException(
                error_code=error_codes.LLM_CALL_FAILED,
                message="LLM_API_KEY 未配置，无法调用 OpenAI-compatible Gateway",
                status_code=503,
                detail={"provider": self.settings.llm_provider},
            )

        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        body = {
            "model": resolved_model,
            "messages": [message.model_dump() for message in messages],
            "temperature": 0,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.settings.llm_api_key}",
        }
        req = request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=resolved_timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AppException(
                error_code=error_codes.LLM_CALL_FAILED,
                message="LLM Gateway 调用失败",
                status_code=502,
                detail={"reason": str(exc), "provider": self.settings.llm_provider},
            ) from exc

        content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        response_metadata = dict(metadata or {})
        response_metadata["llm_call"] = self._build_call_metadata(
            metadata=response_metadata,
            model=resolved_model,
            provider=self.settings.llm_provider,
            trace_id=trace_id,
            latency_ms=(time.monotonic() - started_at) * 1000,
            success=True,
        ).model_dump()
        return LLMResponse(
            content=content,
            model=resolved_model,
            provider=self.settings.llm_provider,
            usage=payload.get("usage", {}),
            trace_id=trace_id,
            metadata=response_metadata,
        )

    def _build_call_metadata(
        self,
        *,
        metadata: dict[str, Any],
        model: str,
        provider: str,
        trace_id: str | None,
        latency_ms: float,
        success: bool,
        error_code: str | None = None,
    ) -> LLMCallMetadata:
        """构造 LLM 调用轻量元信息。

        只从上游 metadata 中抽取 prompt_name、component 等“可观测字段”，
        不保存完整 prompt 和完整模型输出，避免把敏感业务上下文写进快照。
        """

        return LLMCallMetadata(
            trace_id=trace_id,
            run_id=metadata.get("run_id"),
            component=metadata.get("component"),
            prompt_name=metadata.get("prompt_name"),
            prompt_version=metadata.get("prompt_version"),
            model=model,
            provider=provider,
            output_schema=metadata.get("output_schema"),
            latency_ms=round(latency_ms, 3),
            success=success,
            error_code=error_code,
            validator_result=metadata.get("validator_result"),
            fallback_used=metadata.get("fallback_used"),
        )


class MockLLMGateway(LLMGateway):
    """测试用 LLM Gateway。

    Mock 只返回预设内容，不访问网络，保证单元测试可重复、可离线运行。
    """

    def __init__(self, *, response_content: str | None = None, structured_payload: dict | None = None) -> None:
        self.response_content = response_content
        self.structured_payload = structured_payload
        self.calls: list[LLMRequest] = []

    def chat(
        self,
        *,
        messages: list[LLMMessage],
        model: str | None = None,
        timeout_seconds: int | None = None,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        resolved_model = model or "mock-model"
        started_at = time.monotonic()
        self.calls.append(
            LLMRequest(
                model=resolved_model,
                messages=messages,
                timeout_seconds=timeout_seconds or 30,
                trace_id=trace_id,
                metadata=metadata or {},
            )
        )
        content = self.response_content
        if content is None:
            content = json.dumps(self.structured_payload or {}, ensure_ascii=False)
        response_metadata = dict(metadata or {})
        response_metadata["llm_call"] = LLMCallMetadata(
            trace_id=trace_id,
            run_id=response_metadata.get("run_id"),
            component=response_metadata.get("component"),
            prompt_name=response_metadata.get("prompt_name"),
            prompt_version=response_metadata.get("prompt_version"),
            model=resolved_model,
            provider="mock",
            output_schema=response_metadata.get("output_schema"),
            latency_ms=round((time.monotonic() - started_at) * 1000, 3),
            success=True,
            validator_result=response_metadata.get("validator_result"),
            fallback_used=response_metadata.get("fallback_used"),
        ).model_dump()
        return LLMResponse(
            content=content,
            model=resolved_model,
            provider="mock",
            trace_id=trace_id,
            metadata=response_metadata,
        )
