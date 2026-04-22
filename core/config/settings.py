"""基础配置定义。

当前文件只定义项目骨架阶段需要的配置项，不连接任何外部系统。
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """项目基础配置。

    当前阶段仅用于统一管理环境变量名称与默认值，
    为后续 API、数据库、缓存、向量库和模型网关接入预留稳定入口。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 项目名称，用于日志、接口文档和服务标识。
    app_name: str = Field(
        default="Enterprise Knowledge Agentic RAG Platform",
        description="项目名称",
    )

    # 运行环境标识，例如 local、dev、test、prod。
    app_env: str = Field(default="local", description="运行环境")

    # 是否开启调试模式。当前仅用于开发阶段配置占位。
    app_debug: bool = Field(default=False, description="是否开启调试模式")

    # API 统一前缀。后续路由分组时将统一挂载在该前缀之下。
    api_prefix: str = Field(default="/api/v1", description="API 路由前缀")

    # OpenAPI 文档地址。可在生产环境按需关闭或调整。
    openapi_url: str = Field(default="/openapi.json", description="OpenAPI 文档地址")

    # PostgreSQL 数据库连接地址。
    # 当前阶段只保留配置占位，不在代码中建立真实连接。
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/enterprise_rag",
        description="PostgreSQL 连接地址",
    )

    # Redis 连接地址，未来可用于缓存和 Celery Broker。
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis 连接地址",
    )

    # Milvus 服务地址，未来用于向量检索和混合检索。
    milvus_uri: str = Field(
        default="http://localhost:19530",
        description="Milvus 服务地址",
    )

    # LLM 网关基础地址，未来用于接入 OpenAI-compatible Gateway 或私有化模型服务。
    llm_base_url: str = Field(
        default="http://localhost:8001/v1",
        description="LLM 网关基础地址",
    )

    # LLM API Key 示例值。
    # 这里只保留环境变量入口，不写任何真实密钥。
    llm_api_key: str = Field(default="your-api-key", description="LLM API Key 示例值")

    # 默认模型名称，未来供统一模型网关读取。
    default_llm_model: str = Field(
        default="gpt-4o-mini",
        description="默认大模型名称",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取全局单例配置。"""

    return Settings()
