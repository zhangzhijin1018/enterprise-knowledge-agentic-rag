"""DocumentIngestionService 测试。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.common.exceptions import AppException
from core.config.settings import Settings
from core.embedding.gateway import EmbeddingGateway
from core.repositories.document_chunk_repository import (
    DocumentChunkRepository,
    reset_in_memory_document_chunk_store,
)
from core.repositories.document_repository import DocumentRepository, reset_in_memory_document_store
from core.security.auth import UserContext
from core.services.document_ingestion_service import DocumentIngestionService
from core.vectorstore import MilvusStore, reset_in_memory_vector_store


@pytest.fixture(autouse=True)
def reset_state() -> None:
    """重置内存状态。"""

    reset_in_memory_document_store()
    reset_in_memory_document_chunk_store()
    reset_in_memory_vector_store()
    yield
    reset_in_memory_document_store()
    reset_in_memory_document_chunk_store()
    reset_in_memory_vector_store()


def build_user_context(user_id: int = 1001) -> UserContext:
    """构造最小用户上下文。"""

    return UserContext(
        user_id=user_id,
        username=f"user_{user_id}",
        display_name=f"user_{user_id}",
        roles=["employee"],
        department_code="knowledge-center",
        permissions=["document:read", "document:write"],
    )


def test_document_ingestion_service_runs_in_memory_flow() -> None:
    """内存模式下应能完成最小入库闭环。"""

    document_repository = DocumentRepository(session=None)
    chunk_repository = DocumentChunkRepository(session=None)
    embedding_gateway = EmbeddingGateway(settings=Settings())
    vector_store = MilvusStore(collection_name="unit_test_chunks")
    service = DocumentIngestionService(
        document_repository=document_repository,
        document_chunk_repository=chunk_repository,
        embedding_gateway=embedding_gateway,
        vector_store=vector_store,
    )

    document_repository.create_document(
        document_id="doc_ingest_service_001",
        knowledge_base_id="kb_ingest_service_001",
        title="制度文档",
        filename="制度文档.md",
        file_type="md",
        file_size=100,
        storage_uri="/tmp/mock.md",
        business_domain="policy",
        department_id=11,
        security_level="internal",
        uploaded_by=1001,
        metadata={},
    )
    document_repository.update_parse_status("doc_ingest_service_001", "succeeded")

    now = datetime.now(timezone.utc)
    chunk_repository.create_chunks(
        [
            {
                "chunk_uuid": "chunk_parent_service_001",
                "document_id": "doc_ingest_service_001",
                "knowledge_base_id": "kb_ingest_service_001",
                "chunk_index": 1,
                "chunk_type": "parent_text",
                "parent_chunk_uuid": None,
                "level": 1,
                "page_start": 1,
                "page_end": 1,
                "section_title": "第一章 总则",
                "content_preview": "父块内容",
                "token_count": 4,
                "metadata": {
                    "heading_path": ["第一章 总则"],
                    "clause_no": None,
                    "chunk_strategy_version": "v1",
                    "is_table": False,
                    "is_cross_page_table": False,
                    "table_group_id": None,
                    "table_part_no": None,
                    "char_count": 4,
                },
                "created_at": now,
            },
            {
                "chunk_uuid": "chunk_child_service_001",
                "document_id": "doc_ingest_service_001",
                "knowledge_base_id": "kb_ingest_service_001",
                "chunk_index": 2,
                "chunk_type": "child_text",
                "parent_chunk_uuid": "chunk_parent_service_001",
                "level": 2,
                "page_start": 1,
                "page_end": 1,
                "section_title": "第一章 总则",
                "content_preview": "新能源制度要求严格执行巡检制度",
                "token_count": 16,
                "metadata": {
                    "heading_path": ["第一章 总则"],
                    "clause_no": None,
                    "chunk_strategy_version": "v1",
                    "is_table": False,
                    "is_cross_page_table": False,
                    "table_group_id": None,
                    "table_part_no": None,
                    "char_count": 16,
                },
                "created_at": now,
            },
        ]
    )

    result = service.ingest_document("doc_ingest_service_001", build_user_context())

    assert result["data"]["index_status"] == "succeeded"
    assert result["data"]["indexed_chunk_count"] == 1
    updated_chunk = chunk_repository.get_by_chunk_uuid("chunk_child_service_001")
    assert updated_chunk is not None
    assert updated_chunk["index_status"] == "succeeded"
    assert updated_chunk["embedding_model"] == "BAAI/bge-m3"


def test_document_ingestion_service_blocks_unparsed_document() -> None:
    """未解析成功的文档不允许执行入库。"""

    document_repository = DocumentRepository(session=None)
    chunk_repository = DocumentChunkRepository(session=None)
    service = DocumentIngestionService(
        document_repository=document_repository,
        document_chunk_repository=chunk_repository,
        embedding_gateway=EmbeddingGateway(settings=Settings()),
        vector_store=MilvusStore(collection_name="unit_test_chunks"),
    )

    document_repository.create_document(
        document_id="doc_ingest_service_002",
        knowledge_base_id="kb_ingest_service_002",
        title="待解析文档",
        filename="待解析文档.txt",
        file_type="txt",
        file_size=12,
        storage_uri="/tmp/mock.txt",
        business_domain="general",
        department_id=12,
        security_level="internal",
        uploaded_by=1001,
        metadata={},
    )

    with pytest.raises(AppException) as exc_info:
        service.ingest_document("doc_ingest_service_002", build_user_context())

    assert exc_info.value.error_code == "DOCUMENT_NOT_PARSED"
