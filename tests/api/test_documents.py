"""Documents API 最小测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from core.config import get_settings
from core.repositories.document_repository import reset_in_memory_document_store


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    """创建文档 API 测试客户端。

    这里把本地上传目录切到 pytest 的临时目录，
    避免测试写入真实工作区的 `storage/uploads/`。
    """

    monkeypatch.setenv("LOCAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    reset_in_memory_document_store()
    with TestClient(app) as test_client:
        yield test_client
    reset_in_memory_document_store()
    get_settings.cache_clear()


def build_auth_headers(user_id: int = 401, username: str = "document_api_user") -> dict[str, str]:
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


def test_upload_get_and_list_document(client: TestClient) -> None:
    """上传文档后应能查询详情和列表。"""

    headers = build_auth_headers()

    upload_response = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"file": ("新能源业务管理办法.txt", b"mock document content", "text/plain")},
        data={
            "knowledge_base_id": "kb_policy_001",
            "business_domain": "policy",
            "department_id": "101",
            "security_level": "internal",
        },
    )
    upload_payload = upload_response.json()

    assert upload_response.status_code == 200
    assert upload_payload["success"] is True
    assert upload_payload["data"]["parse_status"] == "pending"
    assert upload_payload["data"]["index_status"] == "pending"
    assert upload_payload["meta"]["is_async"] is True

    document_id = upload_payload["data"]["document_id"]

    detail_response = client.get(
        f"/api/v1/documents/{document_id}",
        headers=headers,
    )
    detail_payload = detail_response.json()

    assert detail_response.status_code == 200
    assert detail_payload["data"]["document_id"] == document_id
    assert detail_payload["data"]["knowledge_base_id"] == "kb_policy_001"
    assert detail_payload["data"]["business_domain"] == "policy"
    assert detail_payload["data"]["parse_status"] == "pending"

    list_response = client.get("/api/v1/documents", headers=headers)
    list_payload = list_response.json()

    assert list_response.status_code == 200
    assert list_payload["data"]["total"] == 1
    assert list_payload["data"]["items"][0]["document_id"] == document_id
