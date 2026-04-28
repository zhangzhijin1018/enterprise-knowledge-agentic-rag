"""DocumentChunkRepository 最小行为测试。"""

from __future__ import annotations

from core.repositories.document_chunk_repository import (
    DocumentChunkRepository,
    reset_in_memory_document_chunk_store,
)


def test_document_chunk_repository_in_memory_mode() -> None:
    """内存模式下应支持创建、查询、统计和删除切片。"""

    reset_in_memory_document_chunk_store()
    repository = DocumentChunkRepository(session=None)

    created = repository.create_chunks(
        [
            {
                "chunk_uuid": "chunk_parent_001",
                "document_id": "doc_001",
                "knowledge_base_id": "kb_001",
                "chunk_index": 1,
                "chunk_type": "parent_text",
                "parent_chunk_uuid": None,
                "level": 1,
                "page_start": 1,
                "page_end": 1,
                "section_title": "第一章 总则",
                "content_preview": "第一章总则内容",
                "token_count": 8,
                "metadata": {
                    "heading_path": ["第一章 总则"],
                    "clause_no": None,
                    "chunk_strategy_version": "v1",
                    "is_table": False,
                    "is_cross_page_table": False,
                    "table_group_id": None,
                    "table_part_no": None,
                    "char_count": 8,
                },
            },
            {
                "chunk_uuid": "chunk_child_001",
                "document_id": "doc_001",
                "knowledge_base_id": "kb_001",
                "chunk_index": 2,
                "chunk_type": "table_child",
                "parent_chunk_uuid": "chunk_parent_001",
                "level": 2,
                "page_start": 1,
                "page_end": 2,
                "section_title": "发电量统计表",
                "content_preview": "1月 | 100\n2月 | 120",
                "token_count": 20,
                "metadata": {
                    "heading_path": ["第二章 数据"],
                    "clause_no": None,
                    "chunk_strategy_version": "v1",
                    "is_table": True,
                    "is_cross_page_table": True,
                    "table_group_id": "tblgrp_001",
                    "table_part_no": 1,
                    "char_count": 20,
                    "table_title": "表1 发电量统计",
                    "column_names": ["月份", "发电量"],
                    "row_count": 2,
                },
            },
        ]
    )

    chunks = repository.list_by_document_id("doc_001")
    count = repository.count_by_document_id("doc_001")
    deleted = repository.delete_by_document_id("doc_001")

    assert len(created) == 2
    assert count == 2
    assert chunks[0]["chunk_uuid"] == "chunk_parent_001"
    assert chunks[1]["parent_chunk_uuid"] == "chunk_parent_001"
    assert chunks[1]["metadata"]["is_cross_page_table"] is True
    assert deleted == 2
    assert repository.count_by_document_id("doc_001") == 0

    reset_in_memory_document_chunk_store()
