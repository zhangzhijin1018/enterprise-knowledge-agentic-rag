"""最小检索验证服务。

本服务当前不是最终版 RAG 检索编排器，
而是用于验证“完整入库闭环 + hybrid retrieval + 父块回扩”已经成立。

当前能力边界：
- 主检索对象：`child_text`、`table_summary`、`table_child`
- 混合检索：dense + sparse
- 命中后父块回扩：根据 `parent_chunk_uuid` 回查父块
- 预留后续接入 reranker、治理排序和更复杂检索策略
"""

from __future__ import annotations

from core.common import error_codes
from core.common.exceptions import AppException
from core.common.response import build_response_meta
from core.config.settings import Settings
from core.embedding.gateway import EmbeddingGateway
from core.repositories.document_chunk_repository import DocumentChunkRepository
from core.repositories.document_repository import DocumentRepository
from core.security.auth import UserContext
from core.vectorstore.base import BaseVectorStore


class RetrievalService:
    """最小检索验证服务。"""

    DEFAULT_CHUNK_TYPES = ["child_text", "table_summary", "table_child"]

    def __init__(
        self,
        document_repository: DocumentRepository,
        document_chunk_repository: DocumentChunkRepository,
        embedding_gateway: EmbeddingGateway,
        vector_store: BaseVectorStore,
        settings: Settings,
    ) -> None:
        """初始化依赖。"""

        self.document_repository = document_repository
        self.document_chunk_repository = document_chunk_repository
        self.embedding_gateway = embedding_gateway
        self.vector_store = vector_store
        self.settings = settings

    def search(
        self,
        query: str,
        user_context: UserContext,
        top_k: int | None = None,
        knowledge_base_ids: list[str] | None = None,
        business_domain: str | None = None,
        chunk_types: list[str] | None = None,
    ) -> dict:
        """执行最小 hybrid retrieval。"""

        if not query.strip():
            raise AppException(
                error_code=error_codes.RETRIEVAL_FAILED,
                message="检索查询不能为空",
                status_code=400,
                detail={},
            )

        query_embedding = self.embedding_gateway.embed_query(query)
        accessible_documents, _ = self.document_repository.list_documents(
            page=1,
            page_size=1000,
            uploaded_by=user_context.user_id,
        )
        accessible_document_ids = [item["document_id"] for item in accessible_documents]

        filters = {
            "uploaded_by": user_context.user_id,
        }
        if knowledge_base_ids:
            filters["knowledge_base_id"] = knowledge_base_ids
        if business_domain:
            filters["business_domain"] = business_domain
        if accessible_document_ids:
            filters["document_id"] = accessible_document_ids

        search_results = self.vector_store.search(
            dense_vector=query_embedding["dense_vector"],
            sparse_vector=query_embedding["sparse_vector"],
            top_k=top_k or self.settings.retrieval_default_top_k,
            filters=filters,
            chunk_types=chunk_types or self.DEFAULT_CHUNK_TYPES,
        )

        parent_chunk_uuids = list(
            {
                item["parent_chunk_uuid"]
                for item in search_results
                if item.get("parent_chunk_uuid")
            }
        )
        parent_chunks = {
            chunk["chunk_uuid"]: chunk
            for chunk in self.document_chunk_repository.list_by_chunk_uuids(parent_chunk_uuids)
        }

        items = [
            {
                "chunk_uuid": item["chunk_uuid"],
                "document_id": item["document_id"],
                "parent_chunk_uuid": item.get("parent_chunk_uuid"),
                "chunk_type": item["chunk_type"],
                "score": item["score"],
                "content_preview": item["content_preview"],
                "metadata": item.get("metadata") or {},
                "parent_chunk": parent_chunks.get(item.get("parent_chunk_uuid")),
            }
            for item in search_results
        ]

        return {
            "data": {
                "items": items,
                "total": len(items),
            },
            "meta": build_response_meta(
                total=len(items),
                status="succeeded",
                sub_status="hybrid_retrieval_completed",
            ),
        }
