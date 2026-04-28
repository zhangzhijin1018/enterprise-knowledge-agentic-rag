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

    # 是否允许启用真实数据库模式。
    # 这个配置不是说“只要为 True 就一定连数据库”，
    # 而是表示“如果已经提供了 DATABASE_URL，并且没有强制回退到内存仓储，
    # 那么系统允许优先进入真实数据库模式”。
    #
    # 这样设计的原因是：
    # 1. 本地没有 PostgreSQL 时，项目仍然能自动回退到内存模式启动；
    # 2. 一旦提供 DATABASE_URL，系统默认优先走真实数据库，不要求再改代码；
    # 3. 如果某些本地调试场景想强制走内存模式，仍可通过 use_in_memory_repository 控制。
    database_enabled: bool = Field(default=True, description="是否允许启用真实数据库模式")

    # PostgreSQL 数据库连接地址。
    # 当前默认不写死连接串，原因是：
    # - 没有配置数据库时，项目应能自动回退到内存模式；
    # - 有配置数据库时，再进入真实数据库模式；
    # - 避免默认示例值让系统误判“数据库已经配置好”。
    database_url: str | None = Field(
        default=None,
        description="PostgreSQL 连接地址，通过环境变量 DATABASE_URL 提供",
    )

    # SQLAlchemy 是否输出 SQL 日志。
    # 后续本地排查 ORM 查询问题时可打开。
    database_echo: bool = Field(default=False, description="是否输出 SQLAlchemy SQL 日志")

    # 是否强制使用内存版 Repository。
    # 默认值设为 False，表示：
    # - 如果已经配置了 DATABASE_URL，则系统默认优先走真实数据库；
    # - 如果没有配置 DATABASE_URL，则系统自动回退到内存模式；
    # - 只有显式设为 True，才表示“即使配置了数据库也先不用”。
    use_in_memory_repository: bool = Field(default=False, description="是否强制启用内存版 Repository")

    # 数据库连接预检。
    # 对 PostgreSQL 连接池来说，pool_pre_ping 能在长连接失效后自动探活，
    # 降低“空闲连接已断开但应用仍复用旧连接”的风险。
    database_pool_pre_ping: bool = Field(default=True, description="是否开启数据库连接预检")

    # 连接回收时间，单位秒。
    # 该配置主要为 PostgreSQL 场景预留，用于减少长连接过久后被中间网络设备回收导致的错误。
    database_pool_recycle: int = Field(default=1800, description="数据库连接回收时间（秒）")

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

    # 本地开发阶段的文档上传目录。
    # 当前阶段文档文件先直接写到工作区内的 `storage/uploads/`，
    # 这样可以在不引入对象存储的前提下把“上传 -> 元数据落库”链路跑通。
    # 后续如果切换到 MinIO、OSS、S3，只需要替换 DocumentService 中的存储实现。
    local_upload_dir: str = Field(
        default="storage/uploads",
        description="本地开发上传目录",
    )

    # Embedding 网关 provider 名称。
    # 当前按 BGE-M3 设计，但保留 provider 抽象，
    # 这样后续切换私有化 embedding 服务时无需改业务层。
    embedding_provider: str = Field(
        default="bge_m3",
        description="Embedding Provider 名称",
    )

    # 默认 embedding 模型名称。
    # 当前阶段即使本地没有真实模型，也会把该字段写入索引元数据，
    # 便于后续追踪“这批向量是按哪个模型生成的”。
    embedding_model_name: str = Field(
        default="BAAI/bge-m3",
        description="Embedding 模型名称",
    )

    # 是否允许优先尝试真实 embedding 模型。
    # 默认关闭的原因是：
    # - 当前阶段的目标是先把“完整入库闭环”跑通；
    # - 本地环境未必已经准备好真实模型权重；
    # - 如果默认一上来就尝试加载真实模型，测试和开发启动会明显变慢。
    embedding_allow_real_model: bool = Field(
        default=False,
        description="是否允许尝试真实 embedding 模型",
    )

    # 向量存储 provider 名称。
    # 当前默认按 Milvus 设计，但允许本地内存回退。
    vectorstore_provider: str = Field(
        default="milvus",
        description="向量存储 Provider 名称",
    )

    # Milvus collection 名称。
    milvus_collection_name: str = Field(
        default="document_chunks_v1",
        description="Milvus Collection 名称",
    )

    # 检索默认返回条数。
    retrieval_default_top_k: int = Field(
        default=5,
        description="检索默认返回条数",
    )

    # 是否允许经营分析 Planner 使用 LLM fallback 做槽位补强。
    # 默认关闭的原因是：
    # - 当前阶段优先保证本地规则稳定、可测、可解释；
    # - 只有在明确需要时，才让 LLM 作为“规则不足时的补强器”，
    #   而不是成为主要决策来源。
    analytics_planner_enable_llm_fallback: bool = Field(
        default=False,
        description="是否启用经营分析 Planner 的 LLM fallback",
    )

    # LLM fallback 的默认模型名称。
    # 当前阶段主要用于记录和调试，不代表已经强绑定某个 SDK。
    analytics_planner_llm_model: str = Field(
        default="gpt-4o-mini",
        description="经营分析 Planner fallback 模型名称",
    )

    # SQL Gateway 默认超时，单位毫秒。
    sql_gateway_default_timeout_ms: int = Field(
        default=3000,
        description="SQL Gateway 默认超时（毫秒）",
    )

    # SQL Gateway 默认返回行数上限。
    sql_gateway_default_row_limit: int = Field(
        default=500,
        description="SQL Gateway 默认返回行数上限",
    )

    # 真实经营分析数据源的唯一标识。
    # 当前阶段一旦配置了真实只读库，Schema Registry 会优先把它当作默认 data_source，
    # 这样 AnalyticsService 不需要为“本地样例源”和“真实企业源”写两套逻辑。
    analytics_real_data_source_key: str = Field(
        default="enterprise_readonly",
        description="真实经营分析数据源标识",
    )

    # 真实经营分析数据源连接地址。
    # 该配置允许使用 PostgreSQL、MySQL 或 SQLite 文件库做最小只读接入，
    # 当前阶段最重要的是把“配置化接入 + data_source routing”边界做对。
    analytics_real_data_source_url: str | None = Field(
        default=None,
        description="真实经营分析数据源连接地址",
    )

    # 访问真实经营分析数据源所需的附加权限。
    # 当前阶段先做最小字符串权限校验，
    # 后续如果接更正式 RBAC / ABAC，可以把这个字段映射到完整权限模型。
    analytics_real_data_source_required_permission: str | None = Field(
        default="analytics:query:enterprise",
        description="访问真实经营分析数据源所需权限",
    )

    # SQL Gateway 当前采用的 transport 模式。
    # 目前默认是 `inprocess_mcp_server`，表示 Gateway 通过进程内 SQL MCP server 调用执行链路；
    # 后续如果切成远端 MCP server，只需要扩展 transport 实现，而不需要改 AnalyticsService。
    analytics_sql_gateway_transport_mode: str = Field(
        default="inprocess_mcp_server",
        description="经营分析 SQL Gateway transport 模式",
    )

    @property
    def is_database_configured(self) -> bool:
        """判断是否已经提供真实数据库连接配置。

        注意：
        - 这里只判断“有没有配置 DATABASE_URL”，不代表一定会启用数据库模式；
        - 是否真正进入数据库模式，还要结合 database_enabled 和 use_in_memory_repository 一起判断。
        """

        return bool(self.database_url and self.database_url.strip())

    @property
    def should_use_database(self) -> bool:
        """判断当前是否应优先使用真实数据库。

        决策规则：
        1. 必须允许数据库模式；
        2. 必须真的配置了 DATABASE_URL；
        3. 不能显式要求强制回退到内存模式。

        这个属性是第二轮“数据库模式选择”最核心的统一入口，
        Session、Repository、测试和后续启动日志都应尽量围绕它判断。
        """

        return (
            self.database_enabled
            and self.is_database_configured
            and not self.use_in_memory_repository
        )

    @property
    def repository_mode(self) -> str:
        """返回当前 Repository 模式。

        返回值：
        - `database`：代表优先使用真实数据库；
        - `in_memory`：代表回退到内存仓储。

        该字段主要用于调试、日志和后续启动信息展示。
        """

        return "database" if self.should_use_database else "in_memory"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取全局单例配置。"""

    return Settings()
