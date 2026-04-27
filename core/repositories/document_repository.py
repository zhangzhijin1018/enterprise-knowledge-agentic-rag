"""文档元数据 Repository。

当前阶段只负责：
- 创建文档元数据；
- 查询单个文档；
- 分页查询文档列表；
- 更新解析状态；
- 更新索引状态。

Repository 继续遵循“数据库优先 + 内存回退”的模式，
从而保证本地无 PostgreSQL 时也能联调上传入口。
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from core.database.models import Document, KnowledgeBase

_KNOWLEDGE_BASES: dict[str, dict] = {}
_DOCUMENTS: dict[str, dict] = {}


def _utcnow() -> datetime:
    """返回带时区的当前 UTC 时间。"""

    return datetime.now(timezone.utc)


def _generate_prefixed_id(prefix: str) -> str:
    """生成带业务前缀的占位 ID。"""

    return f"{prefix}_{uuid4().hex[:12]}"


def reset_in_memory_document_store() -> None:
    """重置文档相关内存存储。

    该函数主要用于 API 测试和 repository 测试隔离，
    避免不同测试之间共享同一批文档元数据。
    """

    _KNOWLEDGE_BASES.clear()
    _DOCUMENTS.clear()


class DocumentRepository:
    """文档元数据数据访问层。"""

    def __init__(self, session: Session | None = None) -> None:
        """初始化文档 Repository。"""

        self.session = session

    def _use_database(self) -> bool:
        """判断当前是否启用真实数据库模式。"""

        return self.session is not None

    def _serialize_document(self, document: Document, knowledge_base_uuid: str) -> dict:
        """把 ORM 文档对象转换成 service 可直接使用的字典结构。"""

        return {
            "document_id": document.document_uuid,
            "knowledge_base_id": knowledge_base_uuid,
            "title": document.title,
            "filename": document.filename,
            "file_type": document.file_type,
            "file_size": document.file_size,
            "storage_uri": document.storage_uri,
            "business_domain": document.business_domain,
            "department_id": document.department_id,
            "security_level": document.security_level,
            "parse_status": document.parse_status,
            "index_status": document.index_status,
            "uploaded_by": document.uploaded_by,
            "metadata": document.metadata_json or {},
            "created_at": document.created_at,
            "updated_at": document.updated_at,
        }

    def _get_document_model(self, document_id: str) -> Document | None:
        """根据对外文档 ID 读取文档 ORM 对象。"""

        if not self._use_database():
            return None
        statement = select(Document).where(Document.document_uuid == document_id)
        return self.session.execute(statement).scalar_one_or_none()

    def _get_knowledge_base_model_by_uuid(self, knowledge_base_id: str) -> KnowledgeBase | None:
        """根据对外知识库 ID 读取知识库 ORM 对象。"""

        if not self._use_database():
            return None
        statement = select(KnowledgeBase).where(KnowledgeBase.kb_uuid == knowledge_base_id)
        return self.session.execute(statement).scalar_one_or_none()

    def _ensure_knowledge_base(
        self,
        knowledge_base_id: str,
        business_domain: str,
    ) -> tuple[int, str]:
        """确保目标知识库存在。

        当前阶段尚未实现知识库管理接口，
        但文档元数据表在数据库模式下又需要引用 knowledge_bases。
        因此这里采用最小占位策略：
        - 如果知识库已存在，直接复用；
        - 如果不存在，则创建一个最小占位知识库记录。

        这样能保证“文档上传入口”先跑通，而不会阻塞后续知识库模块独立实现。
        """

        knowledge_base = self._get_knowledge_base_model_by_uuid(knowledge_base_id)
        if knowledge_base is None:
            knowledge_base = KnowledgeBase(
                kb_uuid=knowledge_base_id,
                name=f"占位知识库-{knowledge_base_id}",
                business_domain=business_domain,
                description="当前为文档上传入口阶段自动创建的最小占位知识库",
                status="active",
                metadata_json={},
            )
            self.session.add(knowledge_base)
            self.session.flush()
            self.session.refresh(knowledge_base)
        return knowledge_base.id, knowledge_base.kb_uuid

    def create_document(
        self,
        document_id: str,
        knowledge_base_id: str,
        title: str,
        filename: str,
        file_type: str,
        file_size: int | None,
        storage_uri: str,
        business_domain: str,
        department_id: int | None,
        security_level: str | None,
        uploaded_by: int | None,
        metadata: dict | None = None,
    ) -> dict:
        """创建文档元数据记录。"""

        if self._use_database():
            knowledge_base_pk, knowledge_base_uuid = self._ensure_knowledge_base(
                knowledge_base_id=knowledge_base_id,
                business_domain=business_domain,
            )
            document = Document(
                document_uuid=document_id,
                knowledge_base_id=knowledge_base_pk,
                title=title,
                filename=filename,
                file_type=file_type,
                file_size=file_size,
                storage_uri=storage_uri,
                business_domain=business_domain,
                department_id=department_id,
                version_no=1,
                effective_date=None,
                security_level=security_level,
                access_scope={},
                parse_status="pending",
                index_status="pending",
                uploaded_by=uploaded_by,
                metadata_json=metadata or {},
            )
            self.session.add(document)
            self.session.flush()
            self.session.refresh(document)
            return self._serialize_document(document, knowledge_base_uuid=knowledge_base_uuid)

        now = _utcnow()
        if knowledge_base_id not in _KNOWLEDGE_BASES:
            _KNOWLEDGE_BASES[knowledge_base_id] = {
                "knowledge_base_id": knowledge_base_id,
                "name": f"占位知识库-{knowledge_base_id}",
                "business_domain": business_domain,
                "status": "active",
                "metadata": {},
                "created_at": now,
                "updated_at": now,
            }

        record = {
            "document_id": document_id,
            "knowledge_base_id": knowledge_base_id,
            "title": title,
            "filename": filename,
            "file_type": file_type,
            "file_size": file_size,
            "storage_uri": storage_uri,
            "business_domain": business_domain,
            "department_id": department_id,
            "security_level": security_level,
            "parse_status": "pending",
            "index_status": "pending",
            "uploaded_by": uploaded_by,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }
        _DOCUMENTS[document_id] = record
        return record

    def get_by_document_id(self, document_id: str) -> dict | None:
        """根据对外文档 ID 获取文档元数据。"""

        if self._use_database():
            document = self._get_document_model(document_id)
            if document is None:
                return None
            statement = select(KnowledgeBase).where(KnowledgeBase.id == document.knowledge_base_id)
            knowledge_base = self.session.execute(statement).scalar_one_or_none()
            knowledge_base_uuid = knowledge_base.kb_uuid if knowledge_base is not None else "kb_unknown"
            return self._serialize_document(document, knowledge_base_uuid=knowledge_base_uuid)

        return _DOCUMENTS.get(document_id)

    def list_documents(
        self,
        page: int = 1,
        page_size: int = 20,
        knowledge_base_id: str | None = None,
        business_domain: str | None = None,
        uploaded_by: int | None = None,
    ) -> tuple[list[dict], int]:
        """分页查询文档元数据列表。"""

        if self._use_database():
            statement = select(Document).order_by(desc(Document.created_at))
            rows = list(self.session.execute(statement).scalars())

            serialized_rows = []
            for document in rows:
                statement = select(KnowledgeBase).where(KnowledgeBase.id == document.knowledge_base_id)
                knowledge_base = self.session.execute(statement).scalar_one_or_none()
                kb_uuid = knowledge_base.kb_uuid if knowledge_base is not None else "kb_unknown"
                serialized_rows.append(self._serialize_document(document, knowledge_base_uuid=kb_uuid))

            if knowledge_base_id is not None:
                serialized_rows = [
                    item for item in serialized_rows if item["knowledge_base_id"] == knowledge_base_id
                ]
            if business_domain is not None:
                serialized_rows = [
                    item for item in serialized_rows if item["business_domain"] == business_domain
                ]
            if uploaded_by is not None:
                serialized_rows = [item for item in serialized_rows if item["uploaded_by"] == uploaded_by]

            total = len(serialized_rows)
            start = (page - 1) * page_size
            end = start + page_size
            return serialized_rows[start:end], total

        items = list(_DOCUMENTS.values())
        if knowledge_base_id is not None:
            items = [item for item in items if item["knowledge_base_id"] == knowledge_base_id]
        if business_domain is not None:
            items = [item for item in items if item["business_domain"] == business_domain]
        if uploaded_by is not None:
            items = [item for item in items if item["uploaded_by"] == uploaded_by]

        items.sort(key=lambda item: item["created_at"], reverse=True)
        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        return items[start:end], total

    def update_parse_status(self, document_id: str, parse_status: str) -> dict | None:
        """更新文档解析状态。"""

        if self._use_database():
            document = self._get_document_model(document_id)
            if document is None:
                return None
            document.parse_status = parse_status
            self.session.flush()
            statement = select(KnowledgeBase).where(KnowledgeBase.id == document.knowledge_base_id)
            knowledge_base = self.session.execute(statement).scalar_one_or_none()
            kb_uuid = knowledge_base.kb_uuid if knowledge_base is not None else "kb_unknown"
            return self._serialize_document(document, knowledge_base_uuid=kb_uuid)

        record = self.get_by_document_id(document_id)
        if record is None:
            return None
        record["parse_status"] = parse_status
        record["updated_at"] = _utcnow()
        return record

    def update_index_status(self, document_id: str, index_status: str) -> dict | None:
        """更新文档索引状态。"""

        if self._use_database():
            document = self._get_document_model(document_id)
            if document is None:
                return None
            document.index_status = index_status
            self.session.flush()
            statement = select(KnowledgeBase).where(KnowledgeBase.id == document.knowledge_base_id)
            knowledge_base = self.session.execute(statement).scalar_one_or_none()
            kb_uuid = knowledge_base.kb_uuid if knowledge_base is not None else "kb_unknown"
            return self._serialize_document(document, knowledge_base_uuid=kb_uuid)

        record = self.get_by_document_id(document_id)
        if record is None:
            return None
        record["index_status"] = index_status
        record["updated_at"] = _utcnow()
        return record
