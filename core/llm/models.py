"""LLM 网关通用数据模型。

本模块只定义“平台内部如何描述一次模型调用”，不绑定任何具体 SDK。
这样做的原因是：
1. 企业项目里模型来源经常变化，可能是 vLLM、阿里百炼、DeepSeek 或 OpenAI-compatible API；
2. 业务代码只应该依赖稳定的请求 / 响应契约；
3. 超时、trace、结构化输出和审计字段需要统一，不应该散落在每个业务节点里。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    """一次 Chat 调用中的单条消息。"""

    # 消息角色，保持 OpenAI-compatible 风格，便于后续直接映射到模型网关。
    role: Literal["system", "user", "assistant", "tool"] = Field(description="消息角色")
    # 消息正文。Prompt Registry 渲染后的模板内容会进入这里。
    content: str = Field(description="消息正文")


class LLMRequest(BaseModel):
    """统一 LLM 请求模型。"""

    # 模型名称。生产环境可配置为 Qwen / DeepSeek / OpenAI-compatible 模型。
    model: str = Field(description="模型名称")
    # Chat messages。统一使用 messages 可以兼容绝大多数 OpenAI-compatible 服务。
    messages: list[LLMMessage] = Field(default_factory=list, description="聊天消息列表")
    # 单次请求超时时间，避免业务 workflow 被模型调用无限拖住。
    timeout_seconds: int = Field(default=30, description="模型调用超时时间")
    # trace_id 用于把 LLM 调用和上游 workflow / task_run 串起来。
    trace_id: str | None = Field(default=None, description="链路追踪 ID")
    # 额外元数据，便于审计与调试，不参与模型语义。
    metadata: dict[str, Any] = Field(default_factory=dict, description="调用元数据")


class LLMResponse(BaseModel):
    """统一 LLM 响应模型。"""

    # 模型返回的文本内容。结构化输出会再经过 Pydantic 解析。
    content: str = Field(description="模型原始文本输出")
    # 模型名称，便于审计和问题排查。
    model: str = Field(description="实际使用模型名称")
    # provider 名称，例如 openai_compatible / mock。
    provider: str = Field(description="模型提供方")
    # token 用量当前先预留；不同私有化网关可能返回字段不同。
    usage: dict[str, Any] = Field(default_factory=dict, description="token 使用信息")
    # trace_id 回传，保证调用链上下游可串联。
    trace_id: str | None = Field(default=None, description="链路追踪 ID")
    # 额外响应元数据。
    metadata: dict[str, Any] = Field(default_factory=dict, description="响应元数据")
