"""API 依赖注入模块。

当前阶段先把最关键的一层依赖注入打通：
- 数据库 Session 依赖；
- Repository 依赖；
- Service 依赖；

这样做的业务意义是：
1. router 不直接 new service/repository，职责更干净；
2. 后续从内存实现切到真实 PostgreSQL 时，API 层不需要再改；
3. 单元测试和接口测试时，更容易替换某一层依赖。
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.workflow import ChatWorkflowFacade
from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.agent.control_plane.sql_builder import SQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
from core.config import get_settings
from core.database.session import get_db_session
from core.embedding.gateway import EmbeddingGateway
from core.repositories.conversation_repository import ConversationRepository
from core.repositories.document_chunk_repository import DocumentChunkRepository
from core.repositories.document_repository import DocumentRepository
from core.repositories.sql_audit_repository import SQLAuditRepository
from core.repositories.task_run_repository import TaskRunRepository
from core.security.auth import UserContext
from core.security.auth import resolve_user_context_from_request
from core.services.analytics_service import AnalyticsService
from core.services.chat_service import ChatService
from core.services.clarification_service import ClarificationService
from core.services.conversation_service import ConversationService
from core.services.document_ingestion_service import DocumentIngestionService
from core.services.document_parse_service import DocumentParseService
from core.services.document_service import DocumentService
from core.services.retrieval_service import RetrievalService
from core.tools.sql.sql_gateway import SQLGateway
from core.vectorstore import MilvusStore


def get_session() -> Iterator[Session | None]:
    """提供数据库 Session 依赖。

    模式规则：
    - 如果已经配置 DATABASE_URL，且未强制回退到内存模式，则默认优先提供真实 Session；
    - 如果没有配置数据库，或者显式要求使用内存模式，则返回 `None`；
    - 这样可以保证第二轮尽量不改外层 API 契约，同时让真实数据库接入边界更清晰。
    """

    yield from get_db_session()


def get_current_user_context(request: Request) -> UserContext:
    """提供当前用户上下文依赖。

    当前阶段采用“Bearer 占位 + Header 透传 + 本地 mock 回退”的策略：
    - 正式调用链路可以显式传入用户上下文头；
    - 本地开发在未接认证系统前仍可直接联调；
    - 后续接 JWT / SSO 时，router 和 service 都不需要再改。
    """

    settings = get_settings()
    user_context = resolve_user_context_from_request(
        request,
        allow_local_mock=settings.auth_allow_local_mock,
    )
    request.state.user_context = user_context
    return user_context


def get_conversation_repository(
    session: Session | None = Depends(get_session),
) -> ConversationRepository:
    """提供会话 Repository 依赖。"""

    return ConversationRepository(session=session)


def get_task_run_repository(
    session: Session | None = Depends(get_session),
) -> TaskRunRepository:
    """提供任务运行 Repository 依赖。"""

    return TaskRunRepository(session=session)


def get_sql_audit_repository(
    session: Session | None = Depends(get_session),
) -> SQLAuditRepository:
    """提供 SQL 审计 Repository 依赖。"""

    return SQLAuditRepository(session=session)


def get_document_repository(
    session: Session | None = Depends(get_session),
) -> DocumentRepository:
    """提供文档 Repository 依赖。"""

    return DocumentRepository(session=session)


def get_document_chunk_repository(
    session: Session | None = Depends(get_session),
) -> DocumentChunkRepository:
    """提供文档切片 Repository 依赖。"""

    return DocumentChunkRepository(session=session)


def get_embedding_gateway() -> EmbeddingGateway:
    """提供 Embedding Gateway 依赖。"""

    return EmbeddingGateway(settings=get_settings())


def get_vector_store() -> MilvusStore:
    """提供向量存储依赖。"""

    settings = get_settings()
    return MilvusStore(collection_name=settings.milvus_collection_name)


def get_schema_registry() -> SchemaRegistry:
    """提供经营分析 Schema Registry 依赖。"""

    return SchemaRegistry(settings=get_settings())


def get_metric_catalog(
    schema_registry: SchemaRegistry = Depends(get_schema_registry),
) -> MetricCatalog:
    """提供经营分析 Metric Catalog 依赖。"""

    default_data_source = schema_registry.get_default_data_source()
    return MetricCatalog(
        default_data_source=default_data_source.key,
        default_table_name=default_data_source.default_table,
    )


def get_llm_analytics_planner_gateway() -> LLMAnalyticsPlannerGateway:
    """提供经营分析 LLM fallback 网关。"""

    return LLMAnalyticsPlannerGateway(settings=get_settings())


def get_analytics_planner(
    metric_catalog: MetricCatalog = Depends(get_metric_catalog),
    llm_planner_gateway: LLMAnalyticsPlannerGateway = Depends(get_llm_analytics_planner_gateway),
) -> AnalyticsPlanner:
    """提供经营分析 Planner 依赖。"""

    return AnalyticsPlanner(
        metric_catalog=metric_catalog,
        llm_planner_gateway=llm_planner_gateway,
    )


def get_sql_builder(
    schema_registry: SchemaRegistry = Depends(get_schema_registry),
    metric_catalog: MetricCatalog = Depends(get_metric_catalog),
) -> SQLBuilder:
    """提供规则式 SQL Builder 依赖。"""

    return SQLBuilder(
        schema_registry=schema_registry,
        metric_catalog=metric_catalog,
    )


def get_sql_guard() -> SQLGuard:
    """提供 SQL Guard 依赖。"""

    return SQLGuard(allowed_tables=["analytics_metrics_daily"])


def get_sql_gateway(
    schema_registry: SchemaRegistry = Depends(get_schema_registry),
) -> SQLGateway:
    """提供 SQL Gateway 依赖。

    当前阶段默认通过“进程内 SQL MCP Server”执行，
    既能保持 MCP-compatible contract，又不强依赖独立服务部署。
    """

    return SQLGateway(
        schema_registry=schema_registry,
        settings=get_settings(),
    )


def get_chat_service(
    conversation_repository: ConversationRepository = Depends(get_conversation_repository),
    task_run_repository: TaskRunRepository = Depends(get_task_run_repository),
) -> ChatService:
    """提供 ChatService 依赖。"""

    workflow_facade = ChatWorkflowFacade(
        conversation_repository=conversation_repository,
        task_run_repository=task_run_repository,
    )
    return ChatService(chat_workflow_facade=workflow_facade)


def get_conversation_service(
    conversation_repository: ConversationRepository = Depends(get_conversation_repository),
) -> ConversationService:
    """提供 ConversationService 依赖。"""

    return ConversationService(conversation_repository=conversation_repository)


def get_clarification_service(
    conversation_repository: ConversationRepository = Depends(get_conversation_repository),
    task_run_repository: TaskRunRepository = Depends(get_task_run_repository),
) -> ClarificationService:
    """提供 ClarificationService 依赖。"""

    return ClarificationService(
        conversation_repository=conversation_repository,
        task_run_repository=task_run_repository,
    )


def get_document_service(
    document_repository: DocumentRepository = Depends(get_document_repository),
    document_chunk_repository: DocumentChunkRepository = Depends(get_document_chunk_repository),
) -> DocumentService:
    """提供 DocumentService 依赖。"""

    return DocumentService(
        document_repository=document_repository,
        document_chunk_repository=document_chunk_repository,
        settings=get_settings(),
    )


def get_document_parse_service(
    document_repository: DocumentRepository = Depends(get_document_repository),
    document_chunk_repository: DocumentChunkRepository = Depends(get_document_chunk_repository),
) -> DocumentParseService:
    """提供 DocumentParseService 依赖。"""

    return DocumentParseService(
        document_repository=document_repository,
        document_chunk_repository=document_chunk_repository,
        settings=get_settings(),
    )


def get_document_ingestion_service(
    document_repository: DocumentRepository = Depends(get_document_repository),
    document_chunk_repository: DocumentChunkRepository = Depends(get_document_chunk_repository),
    embedding_gateway: EmbeddingGateway = Depends(get_embedding_gateway),
    vector_store: MilvusStore = Depends(get_vector_store),
) -> DocumentIngestionService:
    """提供 DocumentIngestionService 依赖。"""

    return DocumentIngestionService(
        document_repository=document_repository,
        document_chunk_repository=document_chunk_repository,
        embedding_gateway=embedding_gateway,
        vector_store=vector_store,
    )


def get_retrieval_service(
    document_repository: DocumentRepository = Depends(get_document_repository),
    document_chunk_repository: DocumentChunkRepository = Depends(get_document_chunk_repository),
    embedding_gateway: EmbeddingGateway = Depends(get_embedding_gateway),
    vector_store: MilvusStore = Depends(get_vector_store),
) -> RetrievalService:
    """提供 RetrievalService 依赖。"""

    return RetrievalService(
        document_repository=document_repository,
        document_chunk_repository=document_chunk_repository,
        embedding_gateway=embedding_gateway,
        vector_store=vector_store,
        settings=get_settings(),
    )


def get_analytics_service(
    conversation_repository: ConversationRepository = Depends(get_conversation_repository),
    task_run_repository: TaskRunRepository = Depends(get_task_run_repository),
    sql_audit_repository: SQLAuditRepository = Depends(get_sql_audit_repository),
    analytics_planner: AnalyticsPlanner = Depends(get_analytics_planner),
    sql_builder: SQLBuilder = Depends(get_sql_builder),
    sql_guard: SQLGuard = Depends(get_sql_guard),
    sql_gateway: SQLGateway = Depends(get_sql_gateway),
    schema_registry: SchemaRegistry = Depends(get_schema_registry),
    metric_catalog: MetricCatalog = Depends(get_metric_catalog),
) -> AnalyticsService:
    """提供 AnalyticsService 依赖。"""

    return AnalyticsService(
        conversation_repository=conversation_repository,
        task_run_repository=task_run_repository,
        sql_audit_repository=sql_audit_repository,
        analytics_planner=analytics_planner,
        sql_builder=sql_builder,
        sql_guard=sql_guard,
        sql_gateway=sql_gateway,
        schema_registry=schema_registry,
        metric_catalog=metric_catalog,
    )
