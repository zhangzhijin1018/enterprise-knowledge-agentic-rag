"""文档入库应用服务。

该服务负责把“已经完成解析与切片的文档”推进到完整知识入库阶段：
1. 校验文档已解析成功；
2. 选择适合主检索的 chunk；
3. 生成 dense + sparse 向量；
4. 写入向量库；
5. 更新 chunk 与 document 的入库状态；
6. 返回最小可验证结果。

核心设计原则：
- 子块主召回：`child_text`、`table_summary`、必要时 `table_child`
- 父块回扩：`parent_text`、`table_parent` 暂时主要作为命中后的上下文补全对象

这样做的原因：
- 父块太长，直接作为主检索对象会稀释检索精度；
- 子块更适合向量化和精准召回；
- 命中子块后，再通过 `parent_chunk_uuid` 回查父块，能同时兼顾“准”和“全”。
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.common import error_codes
from core.common.exceptions import AppException
from core.common.response import build_response_meta
from core.embedding.gateway import EmbeddingGateway
from core.repositories.document_chunk_repository import DocumentChunkRepository
from core.repositories.document_repository import DocumentRepository
from core.security.auth import UserContext
from core.vectorstore.base import BaseVectorStore


class DocumentIngestionService:
    """文档完整入库服务。"""

    INDEXABLE_CHUNK_TYPES = {"child_text", "table_summary", "table_child"}

    def __init__(
        self,
        document_repository: DocumentRepository,
        document_chunk_repository: DocumentChunkRepository,
        embedding_gateway: EmbeddingGateway,
        vector_store: BaseVectorStore,
    ) -> None:
        """初始化服务依赖。"""

        self.document_repository = document_repository
        self.document_chunk_repository = document_chunk_repository
        self.embedding_gateway = embedding_gateway
        self.vector_store = vector_store

    def ingest_document(self, document_id: str, user_context: UserContext) -> dict:
        """执行完整文档入库流程。"""

        document = self._get_accessible_document_or_raise(document_id, user_context)
        if document["parse_status"] != "succeeded":
            raise AppException(
                error_code=error_codes.DOCUMENT_NOT_PARSED,
                message="文档尚未解析成功，不能执行向量入库",
                status_code=400,
                detail={
                    "document_id": document_id,
                    "parse_status": document["parse_status"],
                },
            )

        all_chunks = self.document_chunk_repository.list_by_document_id(document_id)
        indexable_chunks = [
            chunk for chunk in all_chunks if chunk["chunk_type"] in self.INDEXABLE_CHUNK_TYPES
        ]
        if not indexable_chunks:
            raise AppException(
                error_code=error_codes.DOCUMENT_NO_INDEXABLE_CHUNKS,
                message="当前文档没有可入库的主检索切片",
                status_code=400,
                detail={"document_id": document_id},
            )

        # 状态流转说明：
        # - ingest 开始时先把整份文档标记为 processing；
        # - 只有全部主检索切片入库成功后，才切到 succeeded；
        # - 任一核心步骤失败，都要明确切到 failed。
        self.document_repository.update_index_status(
            document_id,
            "processing",
            metadata_updates={
                "indexing_provider": "milvus",
                "embedding_model": self.embedding_gateway.model_name,
            },
        )

        try:
            texts = [chunk["content_preview"] for chunk in indexable_chunks]
            embeddings = self.embedding_gateway.embed_texts(texts)

            # 重入库前先删旧向量，避免同一 document_id 混入多版检索对象。
            self.vector_store.delete_by_document_id(document_id)

            vector_payloads = [
                self._build_vector_record(
                    document=document,
                    chunk=chunk,
                    embedding=embedding,
                )
                for chunk, embedding in zip(indexable_chunks, embeddings, strict=True)
            ]
            upserted_records = self.vector_store.upsert_chunks(vector_payloads)

            indexed_at = datetime.now(timezone.utc)
            self.document_chunk_repository.bulk_update_index_info(
                [
                    {
                        "chunk_uuid": record["chunk_uuid"],
                        "index_status": "succeeded",
                        "milvus_primary_key": record["milvus_primary_key"],
                        "embedding_model": self.embedding_gateway.model_name,
                        "indexed_at": indexed_at,
                        "metadata_updates": {
                            "dense_vector_ready": True,
                            "sparse_vector_ready": True,
                            "vectorstore_provider": "milvus",
                        },
                    }
                    for record in upserted_records
                ]
            )

            self.document_repository.update_index_status(
                document_id,
                "succeeded",
                metadata_updates={
                    "indexed_chunk_count": len(upserted_records),
                    "indexable_chunk_types": sorted(self.INDEXABLE_CHUNK_TYPES),
                    "embedding_model": self.embedding_gateway.model_name,
                    "vectorstore_provider": "milvus",
                },
            )

            return {
                "data": {
                    "document_id": document_id,
                    "parse_status": document["parse_status"],
                    "index_status": "succeeded",
                    "chunk_count": len(all_chunks),
                    "indexed_chunk_count": len(upserted_records),
                },
                "meta": build_response_meta(
                    is_async=False,
                    status="succeeded",
                    sub_status="indexing_completed",
                ),
            }
        except AppException:
            self._mark_ingestion_failed(document_id, indexable_chunks, "应用级入库失败")
            raise
        except Exception as exc:
            self._mark_ingestion_failed(document_id, indexable_chunks, str(exc))
            raise AppException(
                error_code=error_codes.DOCUMENT_INGEST_FAILED,
                message="文档入库失败",
                status_code=500,
                detail={
                    "document_id": document_id,
                    "reason": str(exc),
                },
            ) from exc

    def _build_vector_record(self, document: dict, chunk: dict, embedding: dict) -> dict:
        """构造向量库写入对象。

        为什么这里要显式展开 metadata filter 字段：
        - PostgreSQL 存完整文档主数据；
        - 向量库只存检索前过滤所需的最小充分字段；
        - 这样检索时才能在向量库层先做过滤，而不是先召回再在应用层过滤。
        """

        metadata = dict(chunk.get("metadata") or {})
        access_scope = dict(document.get("access_scope") or {}) if isinstance(document.get("access_scope"), dict) else {}

        return {
            "chunk_uuid": chunk["chunk_uuid"],
            "milvus_primary_key": chunk["chunk_uuid"],
            "document_id": chunk["document_id"],
            "parent_chunk_uuid": chunk.get("parent_chunk_uuid"),
            "knowledge_base_id": chunk["knowledge_base_id"],
            "business_domain": document["business_domain"],
            "department_id": document["department_id"],
            "security_level": document["security_level"],
            "uploaded_by": document["uploaded_by"],
            "allowed_role_codes": access_scope.get("allowed_role_codes", []),
            "allowed_department_ids": access_scope.get("allowed_department_ids", []),
            "chunk_type": chunk["chunk_type"],
            "page_start": chunk.get("page_start"),
            "page_end": chunk.get("page_end"),
            "is_table": bool(metadata.get("is_table")),
            "table_group_id": metadata.get("table_group_id"),
            "dense_vector": embedding["dense_vector"],
            "sparse_vector": embedding["sparse_vector"],
            "content": chunk["content_preview"],
            "content_preview": chunk["content_preview"],
            "metadata": metadata,
        }

    def _mark_ingestion_failed(self, document_id: str, indexable_chunks: list[dict], reason: str) -> None:
        """标记文档与切片入库失败。"""

        self.document_repository.update_index_status(
            document_id,
            "failed",
            metadata_updates={"last_index_error": reason},
        )
        self.document_chunk_repository.bulk_update_index_info(
            [
                {
                    "chunk_uuid": chunk["chunk_uuid"],
                    "index_status": "failed",
                    "last_index_error": reason,
                }
                for chunk in indexable_chunks
            ]
        )

    def _get_accessible_document_or_raise(self, document_id: str, user_context: UserContext) -> dict:
        """读取当前用户可访问的文档。"""

        document = self.document_repository.get_by_document_id(document_id)
        if document is None:
            raise AppException(
                error_code=error_codes.DOCUMENT_NOT_FOUND,
                message="指定文档不存在",
                status_code=404,
                detail={"document_id": document_id},
            )

        if document["uploaded_by"] is not None and document["uploaded_by"] != user_context.user_id:
            raise AppException(
                error_code=error_codes.PERMISSION_DENIED,
                message="当前用户无权操作该文档",
                status_code=403,
                detail={
                    "document_id": document_id,
                    "owner_user_id": document["uploaded_by"],
                    "current_user_id": user_context.user_id,
                },
            )

        return document
