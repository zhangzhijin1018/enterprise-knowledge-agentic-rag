"""文档切片 Repository。

当前阶段只负责：
- 批量写入切片；
- 根据文档读取切片；
- 统计切片数量；
- 重解析前删除旧切片。

该层不承载切片策略本身，
只负责把已经生成好的切片结果安全落库或写入内存回退存储。
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from core.database.models import DocumentChunk

_DOCUMENT_CHUNKS: dict[str, list[dict]] = {}


def _utcnow() -> datetime:
    """返回带时区的当前 UTC 时间。"""

    return datetime.now(timezone.utc)


def _generate_prefixed_id(prefix: str) -> str:
    """生成带业务前缀的占位 ID。"""

    return f"{prefix}_{uuid4().hex[:12]}"


def reset_in_memory_document_chunk_store() -> None:
    """重置文档切片内存存储。"""

    _DOCUMENT_CHUNKS.clear()


class DocumentChunkRepository:
    """文档切片数据访问层。"""

    def __init__(self, session: Session | None = None) -> None:
        """初始化文档切片 Repository。"""

        self.session = session

    def _use_database(self) -> bool:
        """判断当前是否启用真实数据库模式。"""

        return self.session is not None

    def _serialize_chunk(self, chunk: DocumentChunk) -> dict:
        """把 ORM 切片对象转换成统一字典结构。"""

        return {
            "chunk_uuid": chunk.chunk_uuid,
            "document_id": chunk.document_id,
            "knowledge_base_id": chunk.knowledge_base_id,
            "chunk_index": chunk.chunk_index,
            "chunk_type": chunk.chunk_type,
            "parent_chunk_uuid": chunk.parent_chunk_uuid,
            "level": chunk.level,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "section_title": chunk.section_title,
            "content_preview": chunk.content_preview,
            "token_count": chunk.token_count,
            "metadata": chunk.metadata_json or {},
            "milvus_primary_key": chunk.milvus_primary_key,
            "index_status": chunk.index_status,
            "embedding_model": chunk.embedding_model,
            "indexed_at": chunk.indexed_at,
            "last_index_error": chunk.last_index_error,
            "created_at": chunk.created_at,
        }

    def create_chunks(self, chunks: list[dict]) -> list[dict]:
        """批量创建文档切片。

        设计说明：
        - parse 服务会在重解析前先删旧切片，再调用这里写入新切片；
        - 这里不负责判断“该不该重解析”，只负责高效批量落库；
        - 如果调用方没有提供 `chunk_uuid`，这里会自动补一个占位值。
        """

        if not chunks:
            return []

        if self._use_database():
            orm_chunks = []
            for item in chunks:
                chunk = DocumentChunk(
                    chunk_uuid=item.get("chunk_uuid") or _generate_prefixed_id("chunk"),
                    document_id=item["document_id"],
                    knowledge_base_id=item["knowledge_base_id"],
                    chunk_index=item["chunk_index"],
                    chunk_type=item["chunk_type"],
                    parent_chunk_uuid=item.get("parent_chunk_uuid"),
                    level=item["level"],
                    page_start=item.get("page_start"),
                    page_end=item.get("page_end"),
                    section_title=item.get("section_title"),
                    content_preview=item["content_preview"],
                    token_count=item["token_count"],
                    metadata_json=item.get("metadata", {}),
                    milvus_primary_key=item.get("milvus_primary_key"),
                    index_status=item.get("index_status", "pending"),
                    embedding_model=item.get("embedding_model"),
                    indexed_at=item.get("indexed_at"),
                    last_index_error=item.get("last_index_error"),
                )
                orm_chunks.append(chunk)
                self.session.add(chunk)

            self.session.flush()
            for chunk in orm_chunks:
                self.session.refresh(chunk)
            return [self._serialize_chunk(chunk) for chunk in orm_chunks]

        created = []
        for item in chunks:
            record = {
                "chunk_uuid": item.get("chunk_uuid") or _generate_prefixed_id("chunk"),
                "document_id": item["document_id"],
                "knowledge_base_id": item["knowledge_base_id"],
                "chunk_index": item["chunk_index"],
                "chunk_type": item["chunk_type"],
                "parent_chunk_uuid": item.get("parent_chunk_uuid"),
                "level": item["level"],
                "page_start": item.get("page_start"),
                "page_end": item.get("page_end"),
                "section_title": item.get("section_title"),
                "content_preview": item["content_preview"],
                "token_count": item["token_count"],
                "metadata": item.get("metadata", {}),
                "milvus_primary_key": item.get("milvus_primary_key"),
                "index_status": item.get("index_status", "pending"),
                "embedding_model": item.get("embedding_model"),
                "indexed_at": item.get("indexed_at"),
                "last_index_error": item.get("last_index_error"),
                "created_at": _utcnow(),
            }
            created.append(record)
        _DOCUMENT_CHUNKS.setdefault(chunks[0]["document_id"], []).extend(created)
        _DOCUMENT_CHUNKS[chunks[0]["document_id"]].sort(key=lambda item: item["chunk_index"])
        return created

    def list_by_document_id(self, document_id: str, chunk_types: list[str] | None = None) -> list[dict]:
        """根据文档 ID 读取切片列表。"""

        if self._use_database():
            statement = (
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document_id)
                .order_by(DocumentChunk.chunk_index.asc())
            )
            rows = list(self.session.execute(statement).scalars())
            serialized = [self._serialize_chunk(item) for item in rows]
            if chunk_types:
                serialized = [item for item in serialized if item["chunk_type"] in chunk_types]
            return serialized

        records = list(_DOCUMENT_CHUNKS.get(document_id, []))
        if chunk_types:
            records = [item for item in records if item["chunk_type"] in chunk_types]
        return records

    def get_by_chunk_uuid(self, chunk_uuid: str) -> dict | None:
        """根据 chunk_uuid 获取单个切片。"""

        if self._use_database():
            statement = select(DocumentChunk).where(DocumentChunk.chunk_uuid == chunk_uuid)
            chunk = self.session.execute(statement).scalar_one_or_none()
            return self._serialize_chunk(chunk) if chunk is not None else None

        for items in _DOCUMENT_CHUNKS.values():
            for item in items:
                if item["chunk_uuid"] == chunk_uuid:
                    return item
        return None

    def list_by_chunk_uuids(self, chunk_uuids: list[str]) -> list[dict]:
        """批量读取切片。"""

        if not chunk_uuids:
            return []

        if self._use_database():
            statement = select(DocumentChunk).where(DocumentChunk.chunk_uuid.in_(chunk_uuids))
            rows = list(self.session.execute(statement).scalars())
            serialized = [self._serialize_chunk(item) for item in rows]
            serialized.sort(key=lambda item: chunk_uuids.index(item["chunk_uuid"]))
            return serialized

        records: list[dict] = []
        for chunk_uuid in chunk_uuids:
            record = self.get_by_chunk_uuid(chunk_uuid)
            if record is not None:
                records.append(record)
        return records

    def count_by_document_id(self, document_id: str) -> int:
        """统计某个文档的切片数量。"""

        if self._use_database():
            statement = select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document_id)
            return int(self.session.execute(statement).scalar_one())

        return len(_DOCUMENT_CHUNKS.get(document_id, []))

    def delete_by_document_id(self, document_id: str) -> int:
        """按文档 ID 删除旧切片。

        这个接口的核心用途是支持“重解析”：
        - 先删旧 chunk；
        - 再写新 chunk；
        - 避免同一文档出现多套不同版本切片混在一起。
        """

        if self._use_database():
            statement = delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
            result = self.session.execute(statement)
            self.session.flush()
            return int(result.rowcount or 0)

        deleted = len(_DOCUMENT_CHUNKS.get(document_id, []))
        _DOCUMENT_CHUNKS.pop(document_id, None)
        return deleted

    def update_index_info(
        self,
        chunk_uuid: str,
        index_status: str,
        milvus_primary_key: str | None = None,
        embedding_model: str | None = None,
        indexed_at: datetime | None = None,
        last_index_error: str | None = None,
        metadata_updates: dict | None = None,
    ) -> dict | None:
        """更新单个切片的入库状态。"""

        if self._use_database():
            statement = select(DocumentChunk).where(DocumentChunk.chunk_uuid == chunk_uuid)
            chunk = self.session.execute(statement).scalar_one_or_none()
            if chunk is None:
                return None

            chunk.index_status = index_status
            if milvus_primary_key is not None:
                chunk.milvus_primary_key = milvus_primary_key
            if embedding_model is not None:
                chunk.embedding_model = embedding_model
            if indexed_at is not None:
                chunk.indexed_at = indexed_at
            if last_index_error is not None:
                chunk.last_index_error = last_index_error
            if metadata_updates:
                merged_metadata = dict(chunk.metadata_json or {})
                merged_metadata.update(metadata_updates)
                chunk.metadata_json = merged_metadata
            self.session.flush()
            return self._serialize_chunk(chunk)

        for items in _DOCUMENT_CHUNKS.values():
            for item in items:
                if item["chunk_uuid"] != chunk_uuid:
                    continue
                item["index_status"] = index_status
                if milvus_primary_key is not None:
                    item["milvus_primary_key"] = milvus_primary_key
                if embedding_model is not None:
                    item["embedding_model"] = embedding_model
                if indexed_at is not None:
                    item["indexed_at"] = indexed_at
                if last_index_error is not None:
                    item["last_index_error"] = last_index_error
                if metadata_updates:
                    merged_metadata = dict(item.get("metadata") or {})
                    merged_metadata.update(metadata_updates)
                    item["metadata"] = merged_metadata
                return item
        return None

    def bulk_update_index_info(self, updates: list[dict]) -> list[dict]:
        """批量更新切片入库状态。"""

        updated_records: list[dict] = []
        for item in updates:
            updated = self.update_index_info(
                chunk_uuid=item["chunk_uuid"],
                index_status=item["index_status"],
                milvus_primary_key=item.get("milvus_primary_key"),
                embedding_model=item.get("embedding_model"),
                indexed_at=item.get("indexed_at"),
                last_index_error=item.get("last_index_error"),
                metadata_updates=item.get("metadata_updates"),
            )
            if updated is not None:
                updated_records.append(updated)
        return updated_records
