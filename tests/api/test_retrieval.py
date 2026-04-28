"""Retrieval API 测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from core.config import get_settings
from core.repositories.document_chunk_repository import reset_in_memory_document_chunk_store
from core.repositories.document_repository import reset_in_memory_document_store
from core.vectorstore import reset_in_memory_vector_store


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    """创建检索 API 测试客户端。"""

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


def build_auth_headers(user_id: int = 901, username: str = "retrieval_api_user") -> dict[str, str]:
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


def _upload_parse_ingest_document(
    client: TestClient,
    headers: dict[str, str],
    filename: str,
    content: str,
    knowledge_base_id: str,
    business_domain: str,
) -> str:
    """完成上传、解析、入库最小闭环。"""

    upload_response = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"file": (filename, content.encode("utf-8"), "text/markdown")},
        data={
            "knowledge_base_id": knowledge_base_id,
            "business_domain": business_domain,
            "security_level": "internal",
        },
    )
    document_id = upload_response.json()["data"]["document_id"]
    assert client.post(f"/api/v1/documents/{document_id}/parse", headers=headers).status_code == 200
    assert client.post(f"/api/v1/documents/{document_id}/ingest", headers=headers).status_code == 200
    return document_id


def test_retrieval_search_returns_minimal_hybrid_results_with_parent_context(client: TestClient) -> None:
    """最小 hybrid retrieval 应返回命中结果和父块回扩。"""

    headers = build_auth_headers()
    _upload_parse_ingest_document(
        client=client,
        headers=headers,
        filename="制度政策.md",
        content="""# 新能源制度

## 第一章 总则
新能源业务运行管理制度要求严格执行巡检和值守制度。
""",
        knowledge_base_id="kb_retrieval_001",
        business_domain="policy",
    )

    response = client.post(
        "/api/v1/retrieval/search",
        headers=headers,
        json={
            "query": "新能源运行管理制度",
            "top_k": 3,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["data"]["total"] >= 1
    first_item = payload["data"]["items"][0]
    assert first_item["chunk_type"] in {"child_text", "table_summary", "table_child"}
    assert first_item["score"] > 0
    assert first_item["parent_chunk"] is not None


def test_retrieval_search_supports_metadata_filter(client: TestClient) -> None:
    """metadata filter 至少应支持业务域和知识库过滤。"""

    headers = build_auth_headers(user_id=902, username="retrieval_filter_user")
    _upload_parse_ingest_document(
        client=client,
        headers=headers,
        filename="制度文档.md",
        content="""# 制度文档

## 第一章 总则
制度管理要求严格执行审批制度与巡检制度。
""",
        knowledge_base_id="kb_policy_filter_001",
        business_domain="policy",
    )
    _upload_parse_ingest_document(
        client=client,
        headers=headers,
        filename="经营报告.md",
        content="""# 经营报告

## 第一部分
经营分析显示发电量和收入持续增长。
""",
        knowledge_base_id="kb_report_filter_001",
        business_domain="report",
    )

    filtered_response = client.post(
        "/api/v1/retrieval/search",
        headers=headers,
        json={
            "query": "制度",
            "business_domain": "policy",
            "knowledge_base_ids": ["kb_policy_filter_001"],
            "top_k": 5,
        },
    )
    payload = filtered_response.json()

    assert filtered_response.status_code == 200
    assert payload["data"]["total"] >= 1
    assert all(item["document_id"] for item in payload["data"]["items"])
    assert all(item["metadata"].get("is_table") in {True, False} for item in payload["data"]["items"])
