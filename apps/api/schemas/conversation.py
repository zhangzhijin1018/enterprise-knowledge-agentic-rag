"""多轮会话接口 Schema。"""

from pydantic import BaseModel, Field


class ConversationListItem(BaseModel):
    """会话列表项。"""

    # 对外稳定会话标识。
    conversation_id: str = Field(description="会话 ID")

    # 会话标题。当前阶段由首条用户问题自动截断生成。
    title: str | None = Field(default=None, description="会话标题")

    # 当前主要路由，例如 chat、analytics、contract_review。
    current_route: str | None = Field(default=None, description="当前业务路由")

    # 会话当前状态，例如 active、cancelled。
    current_status: str = Field(description="会话状态")

    # 最近一次任务运行 ID。
    last_run_id: str | None = Field(default=None, description="最近运行 ID")

    # 更新时间，使用 ISO 8601 字符串返回，便于前端直接展示。
    updated_at: str = Field(description="更新时间")


class ConversationMessageItem(BaseModel):
    """会话消息项。"""

    # 对外稳定消息标识。
    message_id: str = Field(description="消息 ID")

    # 消息角色，如 user、assistant。
    role: str = Field(description="消息角色")

    # 消息类型，如 text、answer、clarification。
    message_type: str = Field(description="消息类型")

    # 消息正文。
    content: str = Field(description="消息内容")

    # 关联运行 ID，用于把消息和任务运行串起来。
    related_run_id: str | None = Field(default=None, description="关联运行 ID")

    # 创建时间。
    created_at: str = Field(description="创建时间")
