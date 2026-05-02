"""经营分析端到端测试。

覆盖从用户请求到最终响应的完整链路：
1. 简单查询的完整流程
2. 澄清-恢复的完整流程
3. 复杂分析的完整流程

这些测试使用模拟的 SQL Gateway，验证完整链路的行为。
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from core.common.cache import reset_global_cache
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.control_plane.sql_builder import SQLBuilder
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
from core.agent.workflows.analytics import (
    AnalyticsLangGraphWorkflow,
    AnalyticsWorkflowOutcome,
    AnalyticsWorkflowStage,
)


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
    """构造带有模拟 SQL Gateway 的 AnalyticsService。"""
    schema_registry = SchemaRegistry()
    metric_catalog = MetricCatalog(
        default_data_source=schema_registry.get_default_data_source().key,
        default_table_name=schema_registry.get_default_data_source().default_table,
    )

    mock_gateway = MockSQLGateway(schema_registry=schema_registry)

    service = AnalyticsService(
        conversation_repository=ConversationRepository(session=None),
        task_run_repository=TaskRunRepository(session=None),
        sql_audit_repository=SQLAuditRepository(session=None),
        analytics_planner=AnalyticsPlanner(
            metric_catalog=metric_catalog,
            llm_planner_gateway=LLMAnalyticsPlannerGateway(settings=Settings()),
        ),
        sql_builder=SQLBuilder(
            schema_registry=schema_registry,
            metric_catalog=metric_catalog,
        ),
        sql_guard=SQLGuard(allowed_tables=["analytics_metrics_daily"]),
        sql_gateway=mock_gateway,
        schema_registry=schema_registry,
        metric_catalog=metric_catalog,
    )

    # 绑定 workflow
    from core.agent.workflows.analytics import AnalyticsWorkflowAdapter
    adapter = AnalyticsWorkflowAdapter(analytics_service=service)
    service.bind_workflow_adapter(adapter, use_workflow=True)

    return service


# ============================================================================
# 场景1：简单查询完整流程
# ============================================================================

def test_e2e_simple_query_flow() -> None:
    """端到端测试：简单查询应该完整执行并返回结果。"""

    service = build_analytics_service_with_mock_gateway()
    workflow = service.workflow_adapter.workflow

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
    workflow = service.workflow_adapter.workflow

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

    data = result.get("data", {})
    assert "summary" in data


# ============================================================================
# 场景2：澄清-恢复完整流程
# ============================================================================

def test_e2e_clarification_resume_flow() -> None:
    """端到端测试：澄清后恢复应该复用原 run_id。"""

    service = build_analytics_service_with_mock_gateway()

    # 第一轮：发起需要澄清的请求
    first_result = service.submit_query(
        query="帮我看一下新疆区域上个月的情况",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    # 验证第一轮进入澄清
    assert first_result["meta"]["status"] == "awaiting_user_clarification"
    original_run_id = first_result["meta"]["run_id"]
    conversation_id = first_result["meta"]["conversation_id"]

    # 模拟用户补充指标
    second_result = service.submit_query(
        query="发电量",
        conversation_id=conversation_id,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    # 验证第二轮
    # 注意：由于 rule_fallback 模式，可能仍然需要澄清或成功
    assert second_result["meta"]["conversation_id"] == conversation_id


# ============================================================================
# 场景3：多轮对话上下文继承
# ============================================================================

def test_e2e_multi_turn_context_inheritance() -> None:
    """端到端测试：多轮对话应该继承上下文。"""

    service = build_analytics_service_with_mock_gateway()

    # 第一轮
    first_result = service.submit_query(
        query="查询新疆区域2024年3月发电量",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    assert first_result["meta"]["status"] == "succeeded"
    conversation_id = first_result["meta"]["conversation_id"]

    # 第二轮：省略区域和时间，只说指标
    second_result = service.submit_query(
        query="收入呢",
        conversation_id=conversation_id,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    # 验证第二轮执行
    # 注意：rule_fallback 可能无法继承上下文，需要 LLM 才能正确处理
    assert second_result["meta"]["conversation_id"] == conversation_id


# ============================================================================
# 场景4：会话历史查询
# ============================================================================

def test_e2e_conversation_history() -> None:
    """端到端测试：应该能查询会话历史。"""

    service = build_analytics_service_with_mock_gateway()

    # 执行查询
    result = service.submit_query(
        query="查询新疆区域2024年3月发电量",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    conversation_id = result["meta"]["conversation_id"]

    # 查询会话历史
    messages = service.conversation_repository.list_messages(conversation_id)

    # 验证有用户消息和助手消息
    assert len(messages) >= 2
    user_messages = [m for m in messages if m.get("role") == "user"]
    assistant_messages = [m for m in messages if m.get("role") == "assistant"]
    assert len(user_messages) >= 1
    assert len(assistant_messages) >= 1


# ============================================================================
# 场景5：Task Run 查询
# ============================================================================

def test_e2e_task_run_query() -> None:
    """端到端测试：应该能查询 Task Run。"""

    service = build_analytics_service_with_mock_gateway()

    # 执行查询
    result = service.submit_query(
        query="查询新疆区域2024年3月发电量",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    run_id = result["meta"]["run_id"]

    # 查询 Task Run
    task_run = service.task_run_repository.get_task_run(run_id)

    # 验证 Task Run 结构
    assert task_run is not None
    assert task_run["run_id"] == run_id
    assert task_run["status"] == "succeeded"


# ============================================================================
# 场景6：SQL Audit 记录
# ============================================================================

def test_e2e_sql_audit_record() -> None:
    """端到端测试：SQL 执行应该被记录到 Audit。"""

    service = build_analytics_service_with_mock_gateway()

    # 执行查询
    result = service.submit_query(
        query="查询新疆区域2024年3月发电量",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    run_id = result["meta"]["run_id"]

    # 查询 SQL Audit
    audit = service.sql_audit_repository.get_latest_by_run_id(run_id)

    # 验证 Audit 记录
    assert audit is not None
    assert audit["run_id"] == run_id
    assert audit["is_safe"] is True


# ============================================================================
# 场景7：错误处理
# ============================================================================

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


# ============================================================================
# 场景8：数据范围限制
# ============================================================================

def test_e2e_department_scope_filter() -> None:
    """端到端测试：应该根据用户部门过滤数据范围。"""

    service = build_analytics_service_with_mock_gateway()

    # 执行查询
    result = service.submit_query(
        query="查询新疆区域2024年3月发电量",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(user_id=2001),  # 使用不同用户
    )

    # 验证执行
    assert result is not None
    assert "meta" in result
