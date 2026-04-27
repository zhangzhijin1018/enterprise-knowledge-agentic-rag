"""澄清与槽位补充接口 Schema。"""

from pydantic import BaseModel, Field


class ClarificationReplyRequest(BaseModel):
    """澄清回复请求模型。"""

    # 用户针对系统澄清问题给出的补充回答。
    reply: str = Field(description="用户补充信息")
