"""FastAPI 应用入口。

当前文件只提供最小可运行骨架：
- 创建 FastAPI app；
- 注册健康检查路由；
- 不实现任何业务逻辑、数据库连接或 Agent 工作流。
"""

from fastapi import FastAPI

from apps.api.routes import health_router


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例。"""

    app = FastAPI(
        title="Enterprise Knowledge Agentic RAG Platform API",
        description="新疆能源集团知识与生产经营智能 Agent 平台后端接口骨架。",
        version="0.1.0",
    )
    app.include_router(health_router)
    return app


app = create_app()
