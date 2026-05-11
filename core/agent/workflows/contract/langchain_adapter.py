"""LangChain LLM 适配器 - 连接项目 LLM Gateway。

将项目的 LLMGateway 适配为 LangChain 兼容的 BaseChatModel。
支持：
1. 同步/异步调用
2. 流式输出
3. 结构化输出

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
from typing import (
    Any,
    AsyncIterator,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Type,
    Union,
)

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ChatMessage,
    ChatResult,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, LLMResult
from langchain_core.runnables import RunnableConfig
from pydantic import ConfigDict

from core.llm.gateway import LLMGateway
from core.llm.models import LLMMessage as ProjectLLMMessage

logger = logging.getLogger(__name__)


class LangChainLLMAdapter(BaseChatModel):
    """LangChain LLM 适配器。

    将项目的 LLMGateway 适配为 LangChain 兼容的 BaseChatModel。

    支持：
    - 同步/异步调用
    - 流式输出
    - 结构化输出（通过 with_config）

    使用方式：
    ```python
    from core.agent.workflows.contract.langchain_adapter import LangChainLLMAdapter
    from core.llm.gateway import OpenAICompatibleLLMGateway

    # 创建适配器
    llm_gateway = OpenAICompatibleLLMGateway()
    llm = LangChainLLMAdapter(llm_gateway=llm_gateway)

    # 使用 LangChain 的 with_config 设置结构化输出
    from langchain_core.output_parsers import JsonOutputParser
    parser = JsonOutputParser()

    chain = llm | parser
    result = chain.invoke("你的问题")
    ```
    """

    model_config = ConfigDict(
        populate_by_name=True,
    )

    # LLM Gateway 实例
    llm_gateway: LLMGateway

    # 模型名称（可选，会覆盖 gateway 的默认配置）
    model_name: Optional[str] = None

    # 温度参数
    temperature: float = 0.0

    # 超时时间（秒）
    timeout_seconds: Optional[int] = 60

    def _convert_messages_to_project_format(
        self, messages: List[BaseMessage]
    ) -> List[ProjectLLMMessage]:
        """将 LangChain 消息格式转换为项目内部格式。"""
        converted = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                converted.append(
                    ProjectLLMMessage(role="user", content=msg.content)
                )
            elif isinstance(msg, AIMessage):
                # 处理带函数的AI消息
                if msg.additional_kwargs.get("function_call"):
                    # 函数调用格式
                    converted.append(
                        ProjectLLMMessage(
                            role="assistant",
                            content=str(msg.additional_kwargs["function_call"]),
                        )
                    )
                else:
                    converted.append(
                        ProjectLLMMessage(role="assistant", content=msg.content)
                    )
            elif isinstance(msg, SystemMessage):
                converted.append(
                    ProjectLLMMessage(role="system", content=msg.content)
                )
            elif isinstance(msg, ChatMessage):
                converted.append(
                    ProjectLLMMessage(role=msg.role, content=msg.content)
                )
            elif isinstance(msg, FunctionMessage):
                converted.append(
                    ProjectLLMMessage(
                        role="function",
                        content=msg.content,
                        name=msg.name,
                    )
                )
            else:
                converted.append(
                    ProjectLLMMessage(role="user", content=str(msg.content))
                )
        return converted

    def _convert_project_message_to_langchain(
        self, content: str, **kwargs
    ) -> AIMessage:
        """将项目消息格式转换为 LangChain 消息。"""
        additional_kwargs = {}
        if kwargs.get("function_call"):
            additional_kwargs["function_call"] = kwargs["function_call"]
        return AIMessage(content=content, additional_kwargs=additional_kwargs)

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """生成聊天结果。"""
        # 转换消息格式
        project_messages = self._convert_messages_to_project_format(messages)

        # 调用 Gateway
        try:
            response = self.llm_gateway.chat(
                messages=project_messages,
                model=self.model_name,
                timeout_seconds=self.timeout_seconds,
            )

            # 转换响应
            ai_message = self._convert_project_message_to_langchain(
                response.content
            )

            # 构建 ChatResult
            generation = ChatGeneration(message=ai_message)
            return ChatResult(generations=[generation])

        except Exception as e:
            logger.error(f"LLM 调用失败: {e}", exc_info=True)
            # 返回错误消息
            error_message = AIMessage(content=f"LLM 调用失败: {str(e)}")
            return ChatResult(generations=[ChatGeneration(message=error_message)])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """异步生成聊天结果。"""
        # 转换消息格式
        project_messages = self._convert_messages_to_project_format(messages)

        # 调用 Gateway
        try:
            response = self.llm_gateway.chat(
                messages=project_messages,
                model=self.model_name,
                timeout_seconds=self.timeout_seconds,
            )

            # 转换响应
            ai_message = self._convert_project_message_to_langchain(
                response.content
            )

            # 构建 ChatResult
            generation = ChatGeneration(message=ai_message)
            return ChatResult(generations=[generation])

        except Exception as e:
            logger.error(f"LLM 异步调用失败: {e}", exc_info=True)
            error_message = AIMessage(content=f"LLM 调用失败: {str(e)}")
            return ChatResult(generations=[ChatGeneration(message=error_message)])

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """流式生成。

        注意：当前实现为简化版本，完整流式支持需要 Gateway 实现流式接口。
        """
        # 当前简化实现：先获取完整响应，再逐字 yield
        result = self._generate(messages, stop, run_manager, **kwargs)
        content = result.generations[0].message.content

        # 逐字 yield
        for char in content:
            yield ChatGenerationChunk(message=AIMessage(content=char))
            if run_manager:
                run_manager.on_llm_new_token(char)

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """异步流式生成。"""
        # 简化实现
        for chunk in self._stream(messages, stop, run_manager, **kwargs):
            yield chunk

    @property
    def _llm_type(self) -> str:
        """LLM 类型标识。"""
        return "project_gateway"


# ==================== 工厂函数 ====================


def create_langchain_llm(
    llm_gateway: Optional[LLMGateway] = None,
    model_name: Optional[str] = None,
    temperature: float = 0.0,
) -> LangChainLLMAdapter:
    """创建 LangChain LLM 适配器。

    Args:
        llm_gateway: LLM Gateway 实例（可选，默认使用配置创建）
        model_name: 模型名称（可选）
        temperature: 温度参数

    Returns:
        LangChainLLMAdapter 实例
    """
    if llm_gateway is None:
        from core.config.settings import get_settings

        settings = get_settings()
        if settings.llm_api_key and settings.llm_api_key != "your-api-key":
            from core.llm.gateway import OpenAICompatibleLLMGateway

            llm_gateway = OpenAICompatibleLLMGateway(settings=settings)
        else:
            from core.llm.gateway import MockLLMGateway

            llm_gateway = MockLLMGateway()

    return LangChainLLMAdapter(
        llm_gateway=llm_gateway,
        model_name=model_name,
        temperature=temperature,
    )


# ==================== 快捷函数 ====================


def get_contract_agent_llm() -> LangChainLLMAdapter:
    """获取合同审核 Agent 专用的 LLM。

    Returns:
        配置好的 LangChainLLMAdapter
    """
    return create_langchain_llm(temperature=0.0)
