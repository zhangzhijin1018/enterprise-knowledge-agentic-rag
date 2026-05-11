"""
MCP (Model Context Protocol) 协议数据结构和类型定义

MCP 是一种让 AI 模型与外部工具/服务交互的协议。本模块定义：
- MCPRequest：调用请求
- MCPResponse：调用响应
- MCPError：错误信息
- ToolDefinition：工具定义
- MCPTool：工具元数据

Author: Enterprise Knowledge Agentic RAG Platform
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================================================
# 枚举定义
# ============================================================================

class MCPErrorCode(str, Enum):
    """
    MCP 错误代码

    - INVALID_PARAMS: 参数错误
    - METHOD_NOT_FOUND: 方法不存在
    - EXECUTION_ERROR: 执行错误
    - TIMEOUT: 超时
    - AUTH_FAILED: 认证失败
    - RATE_LIMITED: 限流
    - INTERNAL_ERROR: 内部错误
    """
    INVALID_PARAMS = "INVALID_PARAMS"
    METHOD_NOT_FOUND = "METHOD_NOT_FOUND"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    TIMEOUT = "TIMEOUT"
    AUTH_FAILED = "AUTH_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class MCPToolKind(str, Enum):
    """
    MCP 工具类型

    - function: 函数调用
    - resource: 资源访问
    - prompt: 提示模板
    """
    FUNCTION = "function"
    RESOURCE = "resource"
    PROMPT = "prompt"


# ============================================================================
# 错误定义
# ============================================================================

class MCPError(BaseModel):
    """
    MCP 错误信息

    当 MCP 调用失败时返回的错误详情
    """
    code: str = Field(description="错误代码")
    message: str = Field(description="错误消息")
    detail: Optional[dict] = Field(default=None, description="错误详情")


# ============================================================================
# 请求和响应
# ============================================================================

class MCPRequest(BaseModel):
    """
    MCP 调用请求

    用于调用 MCP 服务的方法
    """
    method: str = Field(description="要调用的方法名")
    params: dict[str, Any] = Field(default_factory=dict, description="方法参数")
    request_id: Optional[str] = Field(default=None, description="请求 ID（用于追踪）")
    timeout: int = Field(default=300, description="超时时间（秒）")


class MCPResponse(BaseModel):
    """
    MCP 调用响应

    MCP 服务执行后的返回结果
    """
    success: bool = Field(description="是否成功")
    result: Optional[Any] = Field(default=None, description="执行结果")
    error: Optional[MCPError] = Field(default=None, description="错误信息")
    artifacts: list[dict] = Field(default_factory=list, description="产物列表")
    metadata: dict[str, Any] = Field(default_factory=dict, description="额外元数据")
    request_id: Optional[str] = Field(default=None, description="关联的请求 ID")


# ============================================================================
# 工具定义
# ============================================================================

class MCPProperty(BaseModel):
    """
    JSON Schema 属性定义

    用于描述工具参数结构
    """
    type: str = Field(description="参数类型（如 string, number, boolean）")
    description: Optional[str] = Field(default=None, description="参数描述")
    default: Optional[Any] = Field(default=None, description="默认值")
    enum: list[Any] = Field(default_factory=list, description="枚举值")


class MCPParameters(BaseModel):
    """
    工具参数定义

    符合 JSON Schema 规范
    """
    type: str = Field(default="object", description="参数类型")
    properties: dict[str, MCPProperty] = Field(
        default_factory=dict, description="属性定义"
    )
    required: list[str] = Field(default_factory=list, description="必填参数")
    additional_properties: bool = Field(default=False, description="是否允许额外参数")


class MCPTool(BaseModel):
    """
    MCP 工具定义

    描述一个可调用的工具/方法
    """
    name: str = Field(description="工具名称")
    description: str = Field(description="工具描述")
    input_schema: MCPParameters = Field(description="输入参数定义")
    output_schema: Optional[dict] = Field(default=None, description="输出结构定义")
    kind: MCPToolKind = Field(default=MCPToolKind.FUNCTION, description="工具类型")
    tags: list[str] = Field(default_factory=list, description="标签")


class MCPToolList(BaseModel):
    """
    工具列表响应

    返回 MCP 服务支持的所有工具
    """
    tools: list[MCPTool] = Field(description="工具列表")
    server_info: dict[str, Any] = Field(
        default_factory=dict, description="服务端信息"
    )


# ============================================================================
# 流式响应
# ============================================================================

class MCPStreamEvent(BaseModel):
    """
    MCP 流式事件

    用于 SSE 流式响应
    """
    event_type: str = Field(description="事件类型")
    data: Any = Field(description="事件数据")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")


# ============================================================================
# MCP 服务信息
# ============================================================================

class MCPServerInfo(BaseModel):
    """
    MCP 服务信息

    用于服务发现和健康检查
    """
    name: str = Field(description="服务名称")
    version: str = Field(description="服务版本")
    description: Optional[str] = Field(default=None, description="服务描述")
    capabilities: list[str] = Field(default_factory=list, description="支持的能力")
    tools: list[str] = Field(default_factory=list, description="可用工具列表")


class MCPServerStatus(BaseModel):
    """
    MCP 服务状态

    用于健康检查
    """
    server_name: str = Field(description="服务名称")
    status: str = Field(description="状态（online/offline/busy）")
    current_requests: int = Field(default=0, description="当前请求数")
    max_concurrency: int = Field(default=10, description="最大并发")
    uptime_seconds: float = Field(description="运行时间")
    last_heartbeat: datetime = Field(
        default_factory=datetime.now, description="最后心跳"
    )
