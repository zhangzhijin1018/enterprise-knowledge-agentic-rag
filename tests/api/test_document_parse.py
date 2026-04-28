"""Document parse API 最小测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from core.config import get_settings
from core.repositories.document_chunk_repository import (
    DocumentChunkRepository,
    reset_in_memory_document_chunk_store,
)
from core.repositories.document_repository import DocumentRepository, reset_in_memory_document_store


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    """创建文档解析 API 测试客户端。"""

    monkeypatch.setenv("LOCAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    reset_in_memory_document_store()
    reset_in_memory_document_chunk_store()
    with TestClient(app) as test_client:
        yield test_client
    reset_in_memory_document_store()
    reset_in_memory_document_chunk_store()
    get_settings.cache_clear()


def build_auth_headers(user_id: int = 501, username: str = "document_parse_api_user") -> dict[str, str]:
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


def test_parse_document_generates_parent_child_and_table_chunks(client: TestClient, monkeypatch) -> None:
    """上传文档后应能完成解析、切片并生成父子块和跨页表格关联。"""

    status_transitions: list[str] = []
    original_update_parse_status = DocumentRepository.update_parse_status

    def spy_update_parse_status(self, document_id: str, parse_status: str):
        status_transitions.append(parse_status)
        return original_update_parse_status(self, document_id, parse_status)

    monkeypatch.setattr(DocumentRepository, "update_parse_status", spy_update_parse_status)

    headers = build_auth_headers()
    markdown_content = """# 新能源月度经营报告

## 第一部分 经营概览
本月发电量同比增长，收入稳步提升，整体趋势向好。

表1 发电量统计
| 月份 | 发电量 |
| --- | --- |
| 1月 | 100 |
| 2月 | 120 |
[[PAGE:2]]
| 月份 | 发电量 |
| --- | --- |
| 3月 | 130 |
| 4月 | 140 |

## 第二部分 结论
后续继续提升效率，并优化运行管理制度。
"""

    upload_response = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"file": ("新能源月度经营报告.md", markdown_content.encode("utf-8"), "text/markdown")},
        data={
            "knowledge_base_id": "kb_report_001",
            "business_domain": "report",
            "security_level": "internal",
        },
    )
    document_id = upload_response.json()["data"]["document_id"]

    parse_response = client.post(
        f"/api/v1/documents/{document_id}/parse",
        headers=headers,
    )
    parse_payload = parse_response.json()

    assert parse_response.status_code == 200
    assert parse_payload["data"]["document_id"] == document_id
    assert parse_payload["data"]["parse_status"] == "succeeded"
    assert parse_payload["data"]["chunk_count"] > 0
    assert parse_payload["data"]["parent_chunk_count"] > 0
    assert parse_payload["data"]["child_chunk_count"] > 0
    assert status_transitions == ["processing", "succeeded"]

    detail_response = client.get(f"/api/v1/documents/{document_id}", headers=headers)
    detail_payload = detail_response.json()

    assert detail_response.status_code == 200
    assert detail_payload["data"]["parse_status"] == "succeeded"
    assert detail_payload["data"]["chunk_count"] == parse_payload["data"]["chunk_count"]

    chunk_repository = DocumentChunkRepository(session=None)
    chunks = chunk_repository.list_by_document_id(document_id)

    assert any(item["chunk_type"] == "parent_text" and item["level"] == 1 for item in chunks)
    assert any(
        item["chunk_type"] == "child_text" and item["level"] == 2 and item["parent_chunk_uuid"]
        for item in chunks
    )
    assert any(item["chunk_type"] == "table_parent" for item in chunks)
    assert any(item["chunk_type"] == "table_child" for item in chunks)
    assert any(item["chunk_type"] == "table_summary" for item in chunks)
    assert any(item["metadata"].get("is_cross_page_table") is True for item in chunks)
    assert any(item["metadata"].get("table_group_id") for item in chunks if item["metadata"].get("is_table"))
