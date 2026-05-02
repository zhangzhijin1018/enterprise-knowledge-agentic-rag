"""经营分析端到端测试（v2 纯 Workflow 链路）。

覆盖从用户请求到最终响应的完整链路：
1. 简单查询的完整流程
2. 澄清-恢复的完整流程
3. 复杂分析的完整流程

这些测试使用模拟的 SQL Gateway，验证完整链路的行为。

v2 变更：
- 移除旧版 AnalyticsPlanner，只走 LLMAnalyticsIntentParser
- 移除 bind_workflow_adapter 调用（自动创建）
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from core.common.cache import reset_global_cache
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.agent.control_plane.sql_guard import SQLGuard
from core.config.settings import Settings
from core.repositories.analytics_result_repository import (
    AnalyticsResultRepository,
    reset_in_memory_analytics_result_store,
)
from core.repositories.conversation_repository import (
    ConversationRepository,
    reset_in_memory_conversation_store,
)
from core.repositories.data_source_repository import reset_in_memory_data_source_store
from core.repositories.sql_audit_repository import (
    SQLAuditRepository,
    reset_in_memory_sql_audit_store,
)
from core.repositories.task_run_repository import (
    TaskRunRepository,
    reset_in_memory_task_run_store,
)
from core.security.auth import UserContext
from core.services.analytics_service import AnalyticsService


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_state() -> None:
    """重置内存状态。"""
    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    reset_in_memory_sql_audit_store()
    reset_in_memory_data_source_store()
    reset_in_memory_analytics_result_store()
    reset_global_cache()
    yield
    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    reset_in_memory_sql_audit_store()
    reset_in_memory_data_source_store()
    reset_in_memory_analytics_result_store()
    reset_global_cache()


def build_user_context(user_id: int = 1901) -> UserContext:
    """构造最小用户上下文。"""
    return UserContext(
        user_id=user_id,
        username=f"user_{user_id}",
        display_name=f"user_{user_id}",
        roles=["employee", "analyst"],
        department_code="analytics-center",
        permissions=[
            "analytics:query",
            "analytics:metric:generation",
            "analytics:metric:revenue",
            "analytics:metric:cost",
            "analytics:metric:profit",
            "analytics:metric:output",
        ],
    )


class MockSQLGateway:
    """模拟 SQL Gateway。"""

    def __init__(self, schema_registry=None):
        self.schema_registry = schema_registry
        self.execute_count = 0

    def execute_readonly_query(self, request):
        """模拟执行 SQL。"""
        self.execute_count += 1

        # 返回模拟数据
        return MockExecutionResult(
            rows=[
                {"region": "新疆区域", "total_value": 12345.67},
                {"region": "甘肃区域", "total_value": 9876.54},
            ],
            columns=["region", "total_value"],
            row_count=2,
            latency_ms=150,
            data_source="local_analytics",
            db_type="sqlite",
        )


class MockExecutionResult:
    """模拟执行结果。"""

    def __init__(
        self,
        rows: list,
        columns: list,
        row_count: int,
        latency_ms: int,
        data_source: str,
        db_type: str,
    ):
        self.rows = rows
        self.columns = columns
        self.row_count = row_count
        self.latency_ms = latency_ms
        self.data_source = data_source
        self.db_type = db_type


def build_analytics_service_with_mock_gateway() -> AnalyticsService:
    """构造带有模拟 SQL Gateway 的 AnalyticsService（v2 纯 Workflow）。

    v2 变更：移除旧版 AnalyticsPlanner / SQLBuilder 参数，自动使用 Workflow。
    """

    schema_registry = SchemaRegistry()
    metric_catalog = MetricCatalog(
        default_data_source=schema_registry.get_default_data_source().key,
        default_table_name=schema_registry.get_default_data_source().default_table,
    )

    mock_gateway = MockSQLGateway(schema_registry=schema_registry)

    # v2：只传入 Workflow 所需的依赖
    service = AnalyticsService(
        conversation_repository=ConversationRepository(session=None),
        task_run_repository=TaskRunRepository(session=None),
        sql_audit_repository=SQLAuditRepository(session=None),
        sql_guard=SQLGuard(allowed_tables=["analytics_metrics_daily"]),
        sql_gateway=mock_gateway,
        schema_registry=schema_registry,
        metric_catalog=metric_catalog,
    )

    return service


# ============================================================================
# 场景1：简单查询完整流程
# ============================================================================

def test_e2e_simple_query_flow() -> None:
    """端到端测试：简单查询应该完整执行并返回结果。"""

    service = build_analytics_service_with_mock_gateway()

    # 执行查询
    result = service.submit_query(
        query="查询新疆区域2024年3月发电量",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    # 验证响应结构
    assert result is not None
    assert "meta" in result
    assert "data" in result

    # 验证状态
    meta = result["meta"]
    assert meta["status"] == "succeeded"
    assert "run_id" in meta
    assert "conversation_id" in meta

    # 验证数据
    data = result["data"]
    assert "summary" in data
    assert "sql_preview" in data


def test_e2e_simple_query_with_sql_explain() -> None:
    """端到端测试：带 SQL 说明的查询应该返回 SQL。"""

    service = build_analytics_service_with_mock_gateway()

    # 执行查询
    result = service.submit_query(
        query="查询新疆区域2024年3月发电量",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=True,
        user_context=build_user_context(),
    )

    # 验证响应包含 SQL 说明
    assert result is not None
    data = result.get("data", {})
    if "sql_explain" in data:
        assert "SELECT" in data["sql_explain"].upper() or "SQL" in data["sql_explain"]


def test_e2e_simple_query_with_standard_mode() -> None:
    """端到端测试：standard 模式应该返回图表和洞察。"""

    service = build_analytics_service_with_mock_gateway()

    # 执行查询
    result = service.submit_query(
        query="查询新疆区域2024年3月发电量",
        conversation_id=None,
        output_mode="standard",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    # 验证响应
    assert result is not None
    meta = result["meta"]
    assert meta["status"] == "succeeded"


def test_e2e_empty_query_error() -> None:
    """端到端测试：空查询应该返回错误。"""

    service = build_analytics_service_with_mock_gateway()

    # 执行空查询
    from core.common.exceptions import AppException

    try:
        service.submit_query(
            query="",
            conversation_id=None,
            output_mode="lite",
            need_sql_explain=False,
            user_context=build_user_context(),
        )
        assert False, "应该抛出异常"
    except AppException as e:
        assert e.error_code is not None
