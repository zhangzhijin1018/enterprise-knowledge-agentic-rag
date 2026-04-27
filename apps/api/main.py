"""FastAPI 应用入口。

当前文件负责最小可运行的应用装配：
- 创建 FastAPI app；
- 注册健康检查与 `/api/v1` 业务路由；
- 装配请求上下文中间件；
- 注册统一异常处理；

注意：
- 不在 main.py 中写业务逻辑；
- 业务编排应始终放在 service / repository / agent 等分层中。
"""

from fastapi import FastAPI

from apps.api.middlewares import attach_request_context
from apps.api.routers import chat_router, clarifications_router, conversations_router
from apps.api.routes import health_router
from core.common.exceptions import register_exception_handlers
from core.config import configure_logging, get_settings


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例。"""

    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title=settings.app_name,
        description="新疆能源集团知识与生产经营智能 Agent 平台后端接口骨架。",
        version="0.1.0",
        openapi_url=settings.openapi_url,
    )

    app.middleware("http")(attach_request_context)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(chat_router, prefix=settings.api_prefix)
    app.include_router(conversations_router, prefix=settings.api_prefix)
    app.include_router(clarifications_router, prefix=settings.api_prefix)
    return app


app = create_app()
