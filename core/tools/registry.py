"""工具注册中心占位实现。

当前只提供最基础的注册与查询能力，不预置任何具体工具。
"""

from __future__ import annotations

from typing import Iterable

from core.tools.base import BaseTool


class ToolRegistry:
    """工具注册中心。

    后续所有 Agent 可调用工具都应先注册到这里，再通过统一流程完成：
    参数校验、权限判断、风险评估、执行和审计。
    """

    def __init__(self) -> None:
        """初始化空注册表。"""

        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """注册一个工具。

        当前只做名称唯一性约束，后续会扩展为更完整的校验流程。
        """

        tool_name = tool.metadata.name
        if tool_name in self._tools:
            raise ValueError(f"Tool already registered: {tool_name}")
        self._tools[tool_name] = tool

    def get(self, tool_name: str) -> BaseTool | None:
        """根据工具名称获取工具实例。"""

        return self._tools.get(tool_name)

    def list_names(self) -> Iterable[str]:
        """返回当前已注册的工具名称列表。"""

        return tuple(self._tools.keys())
