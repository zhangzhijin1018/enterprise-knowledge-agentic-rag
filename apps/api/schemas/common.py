"""API 通用响应模型。"""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """健康检查响应模型。"""

    # 当前服务状态。当前阶段固定返回 ok，用于最小健康检查。
    status: str = Field(description="服务健康状态")
