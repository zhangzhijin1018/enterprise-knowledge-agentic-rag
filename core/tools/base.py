"""工具基类占位定义。

当前只定义工具抽象和元数据结构，不实现任何具体工具。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(slots=True)
class ToolMetadata:
    """工具元数据。

    该结构未来用于统一描述工具的权限、风险、超时和审计策略，
    让 Agent 在选择和执行工具前有稳定的约束入口。
    """

    # 工具唯一名称，供 Agent 和 Registry 检索。
    name: str

    # 工具中文说明，解释工具解决什么业务问题。
    description: str

    # 工具输入参数 Schema 占位。
    input_schema: Mapping[str, Any] = field(default_factory=dict)

    # 工具输出结果 Schema 占位。
    output_schema: Mapping[str, Any] = field(default_factory=dict)

    # 调用该工具所需权限标识。
    required_permission: str = ""

    # 风险等级，例如 low、medium、high。
    risk_level: str = "low"

    # 超时时间，单位秒。
    timeout: int = 30

    # 重试策略占位，后续可扩展为结构化配置。
    retry_policy: Mapping[str, Any] = field(default_factory=dict)

    # 是否记录工具审计。
    audit_enabled: bool = True

    # 是否默认要求人工复核。
    human_review_required: bool = False


class BaseTool(ABC):
    """所有内部工具的基础抽象。

    设计目标：
    - 统一工具元数据；
    - 统一执行入口；
    - 为后续权限校验、风险判断、审计记录预留扩展点。
    """

    metadata: ToolMetadata

    def __init__(self, metadata: ToolMetadata) -> None:
        """保存工具元数据。"""

        self.metadata = metadata

    @abstractmethod
    def execute(self, **kwargs: Any) -> Mapping[str, Any]:
        """执行工具逻辑。

        当前阶段只定义统一方法签名，具体工具会在后续模块中实现。
        """
