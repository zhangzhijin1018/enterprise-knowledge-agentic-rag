"""智能问答接口 Schema。"""

from pydantic import BaseModel, Field


class HistoryMessageInput(BaseModel):
    """历史消息输入模型。

    当前阶段允许前端传最近几轮历史消息，
    但真正的会话可信来源仍应是服务端持久化记录。
    该字段主要用于：
    - 前端首版联调；
    - 后续对比“前端携带历史”和“服务端会话回放”的差异；
    - 预留跨端恢复会话的输入契约。
    """

    # 消息角色，例如 user 或 assistant。
    role: str = Field(description="消息角色")

    # 消息原文内容。
    content: str = Field(description="消息内容")


class ChatRequest(BaseModel):
    """提交问答请求的最小输入模型。"""

    # 用户问题原文。
    query: str = Field(description="用户问题")

    # 多轮对话时传已有会话 ID；首轮会话可为空，由服务端自动创建。
    conversation_id: str | None = Field(default=None, description="会话 ID")

    # 前端可选传最近历史消息，服务端仍以持久化会话为准。
    history_messages: list[HistoryMessageInput] = Field(
        default_factory=list,
        description="最近历史消息",
    )

    # 业务提示，例如 policy、safety、analytics。
    business_hint: str | None = Field(default=None, description="业务提示")

    # 限制候选知识库范围。当前最小骨架仅保留字段，不实际参与检索。
    knowledge_base_ids: list[str] = Field(default_factory=list, description="候选知识库 ID 列表")

    # 是否流式返回。当前最小骨架统一按非流式处理。
    stream: bool = Field(default=False, description="是否流式返回")


class CitationItem(BaseModel):
    """引用信息模型。

    当前阶段返回 mock citation，
    主要是为了从第一天起就把“答案必须可溯源”的接口格式定下来。
    """

    # 文档 ID。
    document_id: str = Field(description="文档 ID")

    # 文档标题。
    document_title: str = Field(description="文档标题")

    # 切片 ID。
    chunk_id: str = Field(description="切片 ID")

    # 页码。
    page_no: int = Field(description="页码")

    # 摘录片段。
    snippet: str = Field(description="引用片段")
