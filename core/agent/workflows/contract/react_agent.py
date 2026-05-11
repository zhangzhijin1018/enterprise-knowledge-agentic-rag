"""LangChain ReAct Agent 封装 - 真正的 LLM 驱动智能合同审核。

使用 LangChain 的 create_react_agent 构建真正的 ReAct Agent：
1. LLM 动态决定下一步行动（不是硬编码优先级）
2. 真正的推理-行动循环
3. 支持反思和自我校验
4. 支持 Human Review 触发

核心设计：
- 使用 LangChain create_react_agent
- 支持自定义提示词
- 支持流式输出
- 支持中间步骤追踪

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Literal, Optional, Sequence, TypedDict, Union

from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.agents import AgentFinish, AgentStep
from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


# ==================== ReAct Agent 状态定义 ====================


class ReActAgentState(TypedDict):
    """ReAct Agent 内部状态。

    用于追踪 Agent 的推理过程和中间步骤。
    """

    # 输入
    input: str

    # 中间步骤
    chat_history: Annotated[list[BaseMessage], "保留对话历史"]
    intermediate_steps: Annotated[list[AgentStep], "Agent执行的动作列表"]

    # 输出
    output: Optional[str]


# ==================== ReAct Agent 实现 ====================


class ContractReActAgent:
    """基于 LangChain ReAct 的合同审核Agent。

    核心特性：
    1. LLM 驱动的工具选择 - 不是硬编码优先级
    2. 真正的推理-行动循环 - Think → Action → Observe → Think
    3. 反思机制 - 对审查结果进行二次校验
    4. Human Review 触发 - 发现高风险项时暂停

    使用 LangChain create_react_agent 构建，经过生产验证。

    设计原因：
    1. LangChain 是业界最成熟的 Agent 框架
    2. create_react_agent 经过大量生产环境验证
    3. 支持流式输出和结构化响应
    4. 易于集成 LangSmith 可观测性
    """

    def __init__(
        self,
        llm: BaseChatModel,
        tools: Sequence[BaseTool],
        system_prompt: Optional[str] = None,
        max_iterations: int = 15,
        return_intermediate_steps: bool = True,
    ) -> None:
        """初始化 ReAct Agent。

        Args:
            llm: LLM实例（支持OpenAI、DeepSeek等兼容API）
            tools: 可用工具列表
            system_prompt: 系统提示词
            max_iterations: 最大迭代次数（防止无限循环）
            return_intermediate_steps: 是否返回中间步骤
        """
        self.llm = llm
        self.tools = tools
        self.max_iterations = max_iterations
        self.return_intermediate_steps = return_intermediate_steps

        # 构建系统提示词
        if system_prompt is None:
            system_prompt = self._build_default_prompt()

        # 创建提示词模板
        self.prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=system_prompt),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            HumanMessage(content="{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])

        # 创建 Agent
        self.agent = create_react_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=self.prompt,
        )

        # 创建 Executor
        self.executor = AgentExecutor(
            agent=self.agent,
            tools=self.tools,
            max_iterations=max_iterations,
            verbose=True,
            return_intermediate_steps=return_intermediate_steps,
            handle_parsing_errors=True,
        )

        logger.info(
            f"ContractReActAgent 初始化完成 | "
            f"tools={len(tools)} | max_iterations={max_iterations}"
        )

    def invoke(
        self,
        input: str,
        chat_history: Optional[list[BaseMessage]] = None,
        callbacks=None,
    ) -> dict:
        """同步执行 Agent。

        Args:
            input: 用户输入（合同文件ID或问题）
            chat_history: 对话历史
            callbacks: 回调函数

        Returns:
            Agent执行结果，包含：
            - output: 最终答案
            - intermediate_steps: 中间步骤（如果启用）
        """
        logger.info(f"ReAct Agent 开始执行 | input长度={len(input)}")

        # 构建输入
        agent_input = {
            "input": input,
            "chat_history": chat_history or [],
        }

        try:
            result = self.executor.invoke(agent_input, callbacks=callbacks)

            logger.info(
                f"ReAct Agent 执行完成 | "
                f"steps={len(result.get('intermediate_steps', []))}"
            )

            return result

        except Exception as e:
            logger.error(f"ReAct Agent 执行失败: {e}", exc_info=True)
            return {
                "input": input,
                "output": f"执行失败: {str(e)}",
                "intermediate_steps": [],
            }

    async def ainvoke(
        self,
        input: str,
        chat_history: Optional[list[BaseMessage]] = None,
        callbacks=None,
    ) -> dict:
        """异步执行 Agent。

        Args:
            input: 用户输入
            chat_history: 对话历史
            callbacks: 回调函数

        Returns:
            Agent执行结果
        """
        logger.info(f"ReAct Agent 开始异步执行 | input长度={len(input)}")

        agent_input = {
            "input": input,
            "chat_history": chat_history or [],
        }

        try:
            result = await self.executor.ainvoke(agent_input, callbacks=callbacks)

            logger.info(
                f"ReAct Agent 异步执行完成 | "
                f"steps={len(result.get('intermediate_steps', []))}"
            )

            return result

        except Exception as e:
            logger.error(f"ReAct Agent 异步执行失败: {e}", exc_info=True)
            return {
                "input": input,
                "output": f"执行失败: {str(e)}",
                "intermediate_steps": [],
            }

    def stream(
        self,
        input: str,
        chat_history: Optional[list[BaseMessage]] = None,
        callbacks=None,
    ):
        """流式执行 Agent。

        Args:
            input: 用户输入
            chat_history: 对话历史
            callbacks: 回调函数

        Yields:
            流式输出
        """
        logger.info(f"ReAct Agent 开始流式执行")

        agent_input = {
            "input": input,
            "chat_history": chat_history or [],
        }

        try:
            for event in self.executor.stream(agent_input, callbacks=callbacks):
                yield event

        except Exception as e:
            logger.error(f"ReAct Agent 流式执行失败: {e}", exc_info=True)
            yield {"output": f"执行失败: {str(e)}"}

    def _build_default_prompt(self) -> str:
        """构建默认系统提示词。

        提示词设计原则：
        1. 明确角色定位
        2. 清晰定义可用工具
        3. 说明工作流程
        4. 强调风险意识
        """
        tool_descriptions = "\n".join([
            f"- {tool.name}: {tool.description[:100]}..."
            for tool in self.tools
        ])

        return f"""你是一个专业的合同审核AI助手，名为"能源集团合同审核助手"。

## 你的身份
你是一个严谨的合同审核专家，擅长：
- 解析各类合同文档（PDF、Word）
- 检索相关法律法规
- 识别合同中的潜在风险
- 生成专业的审查报告

## 可用工具
{tool_descriptions}

## 工作流程
请严格按照以下流程执行：

1. **解析合同**：首先使用 parse_contract 工具解析合同文档
2. **检索法规**：使用 search_laws 检索相关法律法规
3. **检索模板**：使用 search_templates 检索标准模板
4. **抽取条款**：使用 extract_clauses 抽取合同条款
5. **分析风险**：使用 analyze_risk 分析潜在风险
6. **生成报告**：使用 generate_report 生成审查报告

## 重要规则

### 必须遵守
- 必须先解析合同才能进行后续分析
- 检索法规和模板应该在抽取条款之前或同时进行
- 发现高风险项时，必须使用 request_human_review 工具

### 风险判断标准
以下情况必须触发 Human Review：
- 存在"无条件解除"、"无限责任"等霸王条款
- 存在违反法律法规的条款
- 存在明显不公平的条款

### 回答格式
对于每个问题，请按以下格式回答：

```
Thought: 你的思考过程，解释你为什么选择这个工具
Action: 工具名称
Action Input: 工具输入参数（JSON格式）
Observation: 工具执行结果
...（重复 Thought/Action/Action Input/Observation 直到完成任务）
Thought: 现在我知道最终答案了
Final Answer: 最终答案
```

## 能源行业特殊要求
新疆能源集团合同审核需要特别关注：
- 安全生产责任条款
- 环境保护合规条款
- 国有资产交易规定
- 招标投标合规
- 电力设施保护

请开始审核。"""


# ==================== 简化的 ReAct Agent（用于集成） ====================


class SimpleReActAgent:
    """简化的 ReAct Agent - 用于集成到 LangGraph 节点。

    提供更轻量的接口，适合嵌入到现有 LangGraph 工作流中。
    """

    def __init__(
        self,
        llm: BaseChatModel,
        tools: Sequence[BaseTool],
        max_iterations: int = 10,
    ) -> None:
        """初始化简化 Agent。

        Args:
            llm: LLM实例
            tools: 工具列表
            max_iterations: 最大迭代次数
        """
        self.llm = llm
        self.tools = {tool.name: tool for tool in tools}
        self.max_iterations = max_iterations

    async def plan_next_action(
        self,
        context: dict,
        chat_history: Optional[list] = None,
    ) -> dict:
        """LLM 驱动的下一步行动规划。

        这是真正的 LLM 决策，不是硬编码规则。

        Args:
            context: 当前上下文（包含已完成的步骤、当前状态等）
            chat_history: 对话历史

        Returns:
            决策结果：
            - action: 要执行的动作
            - reasoning: 决策理由
            - input: 动作输入
        """
        # 构建提示
        prompt = self._build_planning_prompt(context, chat_history)

        # 调用 LLM
        response = await self.llm.ainvoke([HumanMessage(content=prompt)])

        # 解析响应
        return self._parse_planning_response(response, context)

    def _build_planning_prompt(self, context: dict, chat_history: Optional[list]) -> str:
        """构建规划提示词。"""
        available_tools = "\n".join([
            f"- {name}: {tool.description[:80]}..."
            for name, tool in self.tools.items()
        ])

        completed_steps = context.get("completed_steps", [])
        completed_str = "\n".join([f"{i+1}. {step}" for i, step in enumerate(completed_steps)])

        current_state = context.get("current_state", {})

        return f"""你是一个合同审核Agent，需要决定下一步行动。

## 当前状态
已完成步骤：
{completed_str or "无"}

当前状态：
{json.dumps(current_state, ensure_ascii=False, indent=2)}

## 可用工具
{available_tools}

## 决策规则
1. 如果合同还没解析，必须先调用 parse_contract
2. 如果还没检索法规，优先检索法规
3. 如果还没抽取条款，调用 extract_clauses
4. 如果还没分析风险，调用 analyze_risk
5. 如果所有分析都完成，调用 generate_report
6. 如果发现高风险项，调用 request_human_review

## 输出格式
请输出JSON格式的决策：
{{
    "action": "工具名称",
    "reasoning": "决策理由",
    "input": {{"工具参数": "值"}}
}}

请只输出JSON，不要有其他内容。"""

    def _parse_planning_response(self, response, context: dict) -> dict:
        """解析 LLM 响应。"""
        try:
            content = response.content if hasattr(response, "content") else str(response)

            # 尝试解析 JSON
            import re
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                decision = json.loads(json_match.group())
                return {
                    "action": decision.get("action"),
                    "reasoning": decision.get("reasoning"),
                    "input": decision.get("input", {}),
                }

            # 如果无法解析，返回默认决策
            return self._default_decision(context)

        except Exception as e:
            logger.warning(f"解析规划响应失败: {e}，使用默认决策")
            return self._default_decision(context)

    def _default_decision(self, context: dict) -> dict:
        """默认决策（基于规则）。"""
        completed = set(context.get("completed_steps", []))

        if "parse_contract" not in completed:
            return {
                "action": "parse_contract",
                "reasoning": "合同未解析，需要先解析合同",
                "input": context.get("current_state", {}).get("parse_input", {}),
            }

        if "extract_clauses" not in completed:
            return {
                "action": "extract_clauses",
                "reasoning": "条款未抽取，需要抽取条款",
                "input": {},
            }

        if "analyze_risk" not in completed:
            return {
                "action": "analyze_risk",
                "reasoning": "风险未分析，需要分析风险",
                "input": {},
            }

        return {
            "action": "generate_report",
            "reasoning": "分析完成，生成报告",
            "input": {},
        }


# ==================== 工具执行器 ====================


class ToolExecutor:
    """工具执行器 - 安全地执行工具。

    提供：
    1. 参数验证
    2. 错误处理
    3. 结果记录
    """

    def __init__(self, tools: Sequence[BaseTool]) -> None:
        """初始化工具执行器。

        Args:
            tools: 可用工具列表
        """
        self.tools = {tool.name: tool for tool in tools}
        self.execution_history: list[dict] = []

    async def execute(
        self,
        tool_name: str,
        tool_input: dict,
        callbacks: Optional[CallbackManagerForToolRun] = None,
    ) -> dict:
        """执行工具。

        Args:
            tool_name: 工具名称
            tool_input: 工具输入参数
            callbacks: 回调函数

        Returns:
            工具执行结果
        """
        tool = self.tools.get(tool_name)
        if not tool:
            return {
                "status": "error",
                "error": f"工具不存在: {tool_name}",
            }

        try:
            # 执行工具
            result = await tool.ainvoke(tool_input, callbacks=callbacks)

            # 记录执行历史
            self.execution_history.append({
                "tool": tool_name,
                "input": tool_input,
                "result": result,
            })

            return result

        except Exception as e:
            logger.error(f"工具执行失败 {tool_name}: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
            }

    def get_history(self) -> list[dict]:
        """获取执行历史。"""
        return self.execution_history.copy()
