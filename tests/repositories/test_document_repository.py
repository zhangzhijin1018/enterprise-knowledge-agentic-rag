"""DocumentRepository 最小行为测试。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.config.settings import Settings
from core.database.base import Base
from core.database.session import build_engine, get_session_factory, reset_database_runtime_state
from core.repositories.document_repository import DocumentRepository
from core.repositories.document_repository import reset_in_memory_document_store


def test_document_repository_in_memory_mode() -> None:
    """内存模式下应支持文档元数据创建和查询。"""

    reset_in_memory_document_store()
    repository = DocumentRepository(session=None)

    document = repository.create_document(
        document_id="doc_test_001",
        knowledge_base_id="kb_test_001",
        title="测试文档",
        filename="测试文档.txt",
        file_type="txt",
        file_size=123,
        storage_uri="/tmp/mock.txt",
        business_domain="policy",
        department_id=1,
        security_level="internal",
        uploaded_by=1,
        metadata={"source": "unit_test"},
    )

    detail = repository.get_by_document_id("doc_test_001")
    items, total = repository.list_documents(page=1, page_size=20, uploaded_by=1)

    assert document["document_id"] == "doc_test_001"
    assert detail is not None
    assert detail["filename"] == "测试文档.txt"
    assert total == 1
    assert items[0]["document_id"] == "doc_test_001"

    reset_in_memory_document_store()


def test_document_repository_database_mode() -> None:
    """数据库模式下应支持最小文档元数据持久化。"""

    reset_database_runtime_state()
    settings = Settings(
        database_enabled=True,
        use_in_memory_repository=False,
        database_url="sqlite+pysqlite:///:memory:",
    )
    engine = build_engine(settings=settings)
    assert engine is not None
    Base.metadata.create_all(engine)

    session_factory = get_session_factory(settings=settings)
    assert session_factory is not None

    session: Session = session_factory()
    try:
        repository = DocumentRepository(session=session)
        repository.create_document(
            document_id="doc_test_db_001",
            knowledge_base_id="kb_test_db_001",
            title="数据库测试文档",
            filename="数据库测试文档.pdf",
            file_type="pdf",
            file_size=456,
            storage_uri="/tmp/mock.pdf",
            business_domain="project",
            department_id=2,
            security_level="confidential",
            uploaded_by=2,
            metadata={"source": "db_test"},
        )
        session.commit()

        detail = repository.get_by_document_id("doc_test_db_001")
        items, total = repository.list_documents(page=1, page_size=20, uploaded_by=2)

        assert detail is not None
        assert detail["knowledge_base_id"] == "kb_test_db_001"
        assert total == 1
        assert items[0]["document_id"] == "doc_test_db_001"
    finally:
        session.close()
        reset_database_runtime_state()
