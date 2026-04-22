"""健康检查路由。

当前仅提供最小健康检查接口，用于验证 FastAPI 应用骨架已正确创建。
"""

from fastapi import APIRouter

from apps.api.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """返回服务健康状态。"""

    return HealthResponse(status="ok")
