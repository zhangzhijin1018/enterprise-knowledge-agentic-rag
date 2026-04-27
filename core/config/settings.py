"""基础配置定义。

当前阶段重点不是把所有外部系统都连起来，
而是先把配置入口定稳，保证后续数据库、模型网关、MCP、A2A 接入时，
不需要再回头重构配置结构。
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

    # 日志级别。
    # 当前主要用于控制 API 请求日志和基础应用日志输出强度，
    # 后续接入结构化日志、Trace 和审计日志时也会复用这个入口。
    log_level: str = Field(default="INFO", description="日志级别")

    # 本地开发是否允许在未提供认证头时回退到 mock 用户。
    # 这样做是为了兼顾两类诉求：
    # 1. 本地前后端联调时，不必一开始就接入真实登录系统；
    # 2. 又能逐步把“显式用户上下文解析”这条链路搭起来。
    auth_allow_local_mock: bool = Field(
        default=True,
        description="本地开发是否允许回退到 mock 用户",
    )

    # API 统一前缀。后续路由分组时将统一挂载在该前缀之下。
    api_prefix: str = Field(default="/api/v1", description="API 路由前缀")

    # OpenAPI 文档地址。可在生产环境按需关闭或调整。
    openapi_url: str = Field(default="/openapi.json", description="OpenAPI 文档地址")

    # 当前是否启用真实数据库连接。
    # 第一阶段默认关闭，让应用在没有 PostgreSQL 的情况下也能跑起来。
    database_enabled: bool = Field(default=False, description="是否启用真实数据库连接")

    # PostgreSQL 数据库连接地址。
    # 当前阶段只保留配置占位，不在代码中建立真实连接。
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/enterprise_rag",
        description="PostgreSQL 连接地址",
    )

    # SQLAlchemy 是否输出 SQL 日志。
    # 后续本地排查 ORM 查询问题时可打开。
    database_echo: bool = Field(default=False, description="是否输出 SQLAlchemy SQL 日志")

    # 当前是否使用内存版 Repository。
    # 第一阶段最小闭环先走该模式，后续接入真实数据库时可切换。
    use_in_memory_repository: bool = Field(default=True, description="是否启用内存版 Repository")

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
