"""Document ingest API 测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from core.config import get_settings
from core.repositories.document_chunk_repository import reset_in_memory_document_chunk_store
from core.repositories.document_repository import DocumentRepository, reset_in_memory_document_store
from core.vectorstore import reset_in_memory_vector_store


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    """创建文档入库 API 测试客户端。"""

    monkeypatch.setenv("LOCAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    reset_in_memory_document_store()
    reset_in_memory_document_chunk_store()
    reset_in_memory_vector_store()
    with TestClient(app) as test_client:
        yield test_client
    reset_in_memory_document_store()
    reset_in_memory_document_chunk_store()
    reset_in_memory_vector_store()
    get_settings.cache_clear()


def build_auth_headers(user_id: int = 801, username: str = "document_ingest_api_user") -> dict[str, str]:
    """构造最小测试认证头。"""

    return {
        "Authorization": "Bearer local-api-token",
        "X-User-Id": str(user_id),
        "X-Username": username,
        "X-Display-Name": username,
        "X-User-Roles": "employee",
        "X-User-Permissions": "document:read,document:write",
        "X-Department-Code": "knowledge-center",
    }


def test_document_ingest_success_after_parse(client: TestClient, monkeypatch) -> None:
    """文档解析成功后应能完成最小入库闭环。"""

    transitions: list[str] = []
    original_update_index_status = DocumentRepository.update_index_status

    def spy_update_index_status(self, document_id: str, index_status: str, metadata_updates=None):
        transitions.append(index_status)
        return original_update_index_status(self, document_id, index_status, metadata_updates)

    monkeypatch.setattr(DocumentRepository, "update_index_status", spy_update_index_status)

    headers = build_auth_headers()
    markdown_content = """# 新能源管理制度

## 第一章 总则
集团新能源业务应严格遵循安全生产和运行管理制度。

表1 责任分工
| 岗位 | 职责 |
| --- | --- |
| 站长 | 总体负责 |
| 值长 | 运行值守 |
"""

    upload_response = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"file": ("新能源管理制度.md", markdown_content.encode("utf-8"), "text/markdown")},
        data={
            "knowledge_base_id": "kb_ingest_001",
            "business_domain": "policy",
            "security_level": "internal",
        },
    )
    document_id = upload_response.json()["data"]["document_id"]

    parse_response = client.post(f"/api/v1/documents/{document_id}/parse", headers=headers)
    assert parse_response.status_code == 200

    ingest_response = client.post(f"/api/v1/documents/{document_id}/ingest", headers=headers)
    ingest_payload = ingest_response.json()

    assert ingest_response.status_code == 200
    assert ingest_payload["data"]["document_id"] == document_id
    assert ingest_payload["data"]["parse_status"] == "succeeded"
    assert ingest_payload["data"]["index_status"] == "succeeded"
    assert ingest_payload["data"]["chunk_count"] > 0
    assert ingest_payload["data"]["indexed_chunk_count"] > 0
    assert transitions == ["processing", "succeeded"]

    detail_response = client.get(f"/api/v1/documents/{document_id}", headers=headers)
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["index_status"] == "succeeded"


def test_document_ingest_should_fail_when_parse_not_completed(client: TestClient) -> None:
    """未解析成功的文档不允许直接入库。"""

    headers = build_auth_headers(user_id=802, username="document_ingest_guard_user")

    upload_response = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"file": ("未解析文档.txt", b"only upload", "text/plain")},
        data={
            "knowledge_base_id": "kb_ingest_002",
            "business_domain": "general",
            "security_level": "internal",
        },
    )
    document_id = upload_response.json()["data"]["document_id"]

    ingest_response = client.post(f"/api/v1/documents/{document_id}/ingest", headers=headers)
    payload = ingest_response.json()

    assert ingest_response.status_code == 400
    assert payload["error_code"] == "DOCUMENT_NOT_PARSED"
