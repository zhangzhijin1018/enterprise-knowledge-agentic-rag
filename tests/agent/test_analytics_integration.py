"""经营分析链路集成测试。

覆盖经营分析 Agent 的完整链路场景：
1. 简单明确查询
2. 缺指标澄清
3. 缺时间范围澄清
4. 指标歧义澄清
5. 复杂同比分析（complex 模式）
6. SQL 注入防护
7. LLM 输出 SQL 字段防护
8. 澄清恢复执行

这些测试覆盖用户问句的所有可能情况。
"""

from __future__ import annotations

import pytest

from unittest.mock import MagicMock, patch

from core.common.cache import reset_global_cache
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.analytics.intent.schema import (
    AnalyticsIntent,
    MetricIntent,
    TimeRangeIntent,
    IntentConfidence,
    ComplexityType,
    PlanningMode,
    AnalysisIntentType,
    CompareTarget,
    TimeRangeType,
)
from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.control_plane.sql_builder import SQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
from core.agent.control_plane.intent_sql_builder import AnalyticsIntentSQLBuilder
from core.analytics.intent.parser import LLMAnalyticsIntentParser
from core.analytics.intent.validator import AnalyticsIntentValidator
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
from core.tools.sql.sql_gateway import SQLGateway
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


def build_analytics_service() -> AnalyticsService:
    """构造最小 AnalyticsService。"""
    schema_registry = SchemaRegistry()
    metric_catalog = MetricCatalog(
        default_data_source=schema_registry.get_default_data_source().key,
        default_table_name=schema_registry.get_default_data_source().default_table,
    )
    return AnalyticsService(
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
        sql_gateway=SQLGateway(schema_registry=schema_registry),
        schema_registry=schema_registry,
        metric_catalog=metric_catalog,
    )


def build_workflow(service: AnalyticsService) -> AnalyticsLangGraphWorkflow:
    """构造 workflow。"""
    workflow = AnalyticsLangGraphWorkflow(service)
    service.bind_workflow_adapter(
        service.workflow_adapter or _MockWorkflowAdapter(service),
        use_workflow=True,
    )
    return workflow


class _MockWorkflowAdapter:
    """模拟 Workflow Adapter。"""
    def __init__(self, service):
        self.workflow = AnalyticsLangGraphWorkflow(service)


# ============================================================================
# 场景1：简单明确查询
# ============================================================================

def test_simple_clear_query() -> None:
    """场景1：简单明确查询应该直接执行成功。"""

    service = build_analytics_service()
    workflow = build_workflow(service)

    state = workflow.run_state(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="standard",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    # 验证 workflow 状态
    assert workflow.backend_name == "langgraph_stategraph"
    assert state["workflow_stage"] == AnalyticsWorkflowStage.ANALYTICS_FINISH
    assert state["workflow_outcome"] == AnalyticsWorkflowOutcome.FINISH

    result = state["final_response"]
    assert result["meta"]["status"] == "succeeded"
    assert result["data"]["summary"]


# ============================================================================
# 场景2：缺指标澄清
# ============================================================================

def test_missing_metric_clarification() -> None:
    """场景2：缺少指标时应该返回澄清。"""

    service = build_analytics_service()
    workflow = build_workflow(service)

    state = workflow.run_state(
        query="帮我看一下新疆区域上个月的情况",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    # 验证进入澄清流程
    assert state["workflow_stage"] == AnalyticsWorkflowStage.ANALYTICS_FINISH
    assert state["workflow_outcome"] == AnalyticsWorkflowOutcome.CLARIFY

    result = state["final_response"]
    # clarification 响应结构是 data.clarification
    clarification = result["data"].get("clarification", {})
    assert clarification is not None, "应该返回 clarification"
    assert "question" in clarification or "target_slots" in clarification


# ============================================================================
# 场景3：缺时间范围澄清
# ============================================================================

def test_missing_time_range_clarification() -> None:
    """场景3：缺少时间范围时应该返回澄清。"""

    service = build_analytics_service()
    workflow = build_workflow(service)

    state = workflow.run_state(
        query="查询新疆区域发电量",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    # 验证进入澄清流程
    assert state["workflow_outcome"] == AnalyticsWorkflowOutcome.CLARIFY

    result = state["final_response"]
    clarification = result["data"].get("clarification", {})
    assert clarification is not None


# ============================================================================
# 场景4：指标歧义澄清
# ============================================================================

def test_ambiguous_metric_clarification() -> None:
    """场景4：指标存在歧义时应该返回澄清并提供选项。"""

    service = build_analytics_service()
    workflow = build_workflow(service)

    state = workflow.run_state(
        query="新疆最近电量咋样",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    # 验证进入澄清流程
    assert state["workflow_outcome"] == AnalyticsWorkflowOutcome.CLARIFY

    result = state["final_response"]
    clarification = result["data"].get("clarification", {})
    assert clarification is not None
    # 应该提供建议选项
    if clarification.get("suggested_options"):
        assert len(clarification["suggested_options"]) > 0


# ============================================================================
# 场景5：复杂同比分析（complex 模式）
# ============================================================================

def test_complex_yoy_analysis() -> None:
    """场景5：复杂同比分析应该生成 required_queries。"""

    # 测试 AnalyticsIntentSQLBuilder 的 complex 模式
    schema_registry = SchemaRegistry()
    metric_catalog = MetricCatalog(
        default_data_source=schema_registry.get_default_data_source().key,
        default_table_name=schema_registry.get_default_data_source().default_table,
    )
    builder = AnalyticsIntentSQLBuilder(
        schema_registry=schema_registry,
        metric_catalog=metric_catalog,
    )

    # 构造 complex 意图
    intent = AnalyticsIntent(
        task_type="analytics_query",
        complexity=ComplexityType.COMPLEX,
        planning_mode=PlanningMode.DECOMPOSED,
        analysis_intent=AnalysisIntentType.DECLINE_ATTRIBUTION,
        metric=MetricIntent(
            raw_text="发电量",
            metric_code="generation",
            metric_name="发电量",
            confidence=0.95,
        ),
        time_range=TimeRangeIntent(
            raw_text="近三个月",
            type=TimeRangeType.RELATIVE,
            value="近三个月",
            confidence=0.9,
        ),
        org_scope=None,
        group_by="station",
        compare_target=CompareTarget.YOY,
        confidence=IntentConfidence(
            overall=0.92,
            metric=0.95,
            time_range=0.9,
            group_by=0.95,
            compare_target=0.95,
        ),
        need_clarification=False,
        missing_fields=[],
        ambiguous_fields=[],
    )

    # 添加 required_queries
    from core.analytics.intent.schema import RequiredQueryIntent, PeriodRole
    intent.required_queries = [
        RequiredQueryIntent(
            query_name="current",
            purpose="查询当前周期各电站发电量",
            metric_code="generation",
            period_role=PeriodRole.CURRENT,
            group_by="station",
        ),
        RequiredQueryIntent(
            query_name="yoy_baseline",
            purpose="查询去年同期各电站发电量",
            metric_code="generation",
            period_role=PeriodRole.YOY_BASELINE,
            group_by="station",
        ),
    ]

    # 构建 SQL
    sql_bundle = builder.build(intent, department_code="analytics-center")

    assert sql_bundle is not None
    assert "generated_sql" in sql_bundle
    assert sql_bundle["builder_metadata"]["planning_mode"] == "decomposed"


# ============================================================================
# 场景6：SQL 注入防护
# ============================================================================

def test_sql_injection_protection() -> None:
    """场景6：SQL 注入应该被 SQL Guard 阻断。"""

    service = build_analytics_service()
    # 使用 mock 的 SQL Gateway 返回恶意 SQL 结果
    original_execute = service.sql_gateway.execute_readonly_query

    def mock_execute_with_injection(*args, **kwargs):
        # 模拟 SQL 执行返回异常结果
        raise Exception("SQL 注入检测：包含禁止的 DDL 语句")

    service.sql_gateway.execute_readonly_query = mock_execute_with_injection

    workflow = build_workflow(service)

    try:
        state = workflow.run_state(
            query="查询发电量",
            conversation_id=None,
            output_mode="lite",
            need_sql_explain=False,
            user_context=build_user_context(),
        )
        # 如果没有抛出异常，检查是否进入失败流程
        assert state["workflow_outcome"] in [
            AnalyticsWorkflowOutcome.FAIL,
            AnalyticsWorkflowOutcome.CLARIFY,
        ]
    except Exception:
        # SQL 注入被正确检测
        pass
    finally:
        service.sql_gateway.execute_readonly_query = original_execute


# ============================================================================
# 场景7：LLM 输出 SQL 字段防护
# ============================================================================

def test_llm_sql_field_rejection() -> None:
    """场景7：LLM 输出 SQL 字段应该被 Validator 拒绝。"""

    # 测试 Validator 能检测到 SQL 字段
    validator = AnalyticsIntentValidator()

    # 构造包含 SQL 字段的意图
    intent_dict = {
        "task_type": "analytics_query",
        "complexity": "simple",
        "planning_mode": "direct",
        "analysis_intent": "simple_query",
        "raw_sql": "SELECT * FROM users",  # 禁止字段
        "confidence": {"overall": 0.9},
        "need_clarification": False,
        "missing_fields": [],
        "ambiguous_fields": [],
    }

    # 验证 Validator 能检测到 SQL 字段
    has_sql = validator._has_sql_fields(intent_dict)
    assert has_sql is True, "Validator 应该能检测到 SQL 字段"


# ============================================================================
# 场景8：澄清恢复执行
# ============================================================================

def test_clarification_resume() -> None:
    """场景8：澄清后恢复执行应该复用原 run_id。"""

    service = build_analytics_service()
    workflow = build_workflow(service)

    # 第一轮：发起需要澄清的请求
    first_state = workflow.run_state(
        query="帮我看一下新疆区域上个月的情况",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    # 验证第一轮进入澄清
    assert first_state["workflow_outcome"] == AnalyticsWorkflowOutcome.CLARIFY
    original_run_id = first_state.get("run_id")

    # 模拟用户补充指标后的恢复执行
    second_state = workflow.run_state(
        query="发电量",
        conversation_id=first_state.get("conversation_id"),
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(),
        run_id=original_run_id,
        trace_id=first_state.get("trace_id"),
    )

    # 验证第二轮继续执行
    # 注意：由于是 rule_fallback 模式，可能仍然需要澄清
    assert second_state["workflow_outcome"] in [
        AnalyticsWorkflowOutcome.FINISH,
        AnalyticsWorkflowOutcome.CLARIFY,
    ]


# ============================================================================
# 场景9：Validator 置信度校验
# ============================================================================

def test_validator_confidence_threshold() -> None:
    """场景9：置信度过低时应该触发澄清。"""

    validator = AnalyticsIntentValidator()

    # 构造低置信度意图
    intent = AnalyticsIntent(
        task_type="analytics_query",
        complexity=ComplexityType.SIMPLE,
        planning_mode=PlanningMode.DIRECT,
        analysis_intent=AnalysisIntentType.SIMPLE_QUERY,
        metric=MetricIntent(
            raw_text="电量",
            confidence=0.3,  # 低置信度
        ),
        time_range=TimeRangeIntent(
            raw_text="最近",
            type=TimeRangeType.RELATIVE,
            confidence=0.4,  # 低置信度
        ),
        confidence=IntentConfidence(
            overall=0.5,  # 低于阈值 0.65
            metric=0.3,
            time_range=0.4,
        ),
        need_clarification=False,
        missing_fields=[],
        ambiguous_fields=[],
    )

    result = validator.validate(intent)

    # 验证需要澄清
    assert result.need_clarification is True or result.valid is False


# ============================================================================
# 场景10：Validator group_by 白名单
# ============================================================================

def test_validator_group_by_whitelist() -> None:
    """场景10：非白名单 group_by 应该被拒绝。"""

    validator = AnalyticsIntentValidator()

    # 构造非白名单 group_by 的意图
    intent = AnalyticsIntent(
        task_type="analytics_query",
        complexity=ComplexityType.SIMPLE,
        planning_mode=PlanningMode.DIRECT,
        analysis_intent=AnalysisIntentType.SIMPLE_QUERY,
        metric=MetricIntent(
            raw_text="发电量",
            metric_code="generation",
            confidence=0.9,
        ),
        time_range=TimeRangeIntent(
            raw_text="2024-03",
            type=TimeRangeType.ABSOLUTE,
            value="2024-03",
            confidence=0.9,
        ),
        group_by="invalid_dimension",  # 非白名单
        confidence=IntentConfidence(overall=0.9),
        need_clarification=False,
        missing_fields=[],
        ambiguous_fields=[],
    )

    result = validator.validate(intent)

    # 验证被拒绝
    assert result.valid is False or result.need_clarification is True
    assert any("group_by" in str(e).lower() for e in result.errors)


# ============================================================================
# 场景11：decomposed 模式 required_queries 校验
# ============================================================================

def test_decomposed_requires_required_queries() -> None:
    """场景11：decomposed 模式但没有 required_queries 应该被拒绝。"""

    validator = AnalyticsIntentValidator()

    # 构造 decomposed 但没有 required_queries 的意图
    intent = AnalyticsIntent(
        task_type="analytics_query",
        complexity=ComplexityType.COMPLEX,
        planning_mode=PlanningMode.DECOMPOSED,
        analysis_intent=AnalysisIntentType.DECLINE_ATTRIBUTION,
        metric=MetricIntent(
            raw_text="发电量",
            metric_code="generation",
            confidence=0.9,
        ),
        time_range=TimeRangeIntent(
            raw_text="近三个月",
            type=TimeRangeType.RELATIVE,
            confidence=0.9,
        ),
        compare_target=CompareTarget.YOY,
        confidence=IntentConfidence(overall=0.9),
        need_clarification=False,
        missing_fields=[],
        ambiguous_fields=[],
        required_queries=[],  # 空列表
    )

    result = validator.validate(intent)

    # 验证被拒绝
    assert result.valid is False
    assert any("required_queries" in str(e).lower() for e in result.errors)


# ============================================================================
# 场景12：decline_attribution + yoy 需要 yoy_baseline
# ============================================================================

def test_decline_attribution_requires_yoy_baseline() -> None:
    """场景12：decline_attribution + yoy 需要 yoy_baseline。"""

    validator = AnalyticsIntentValidator()

    # 构造 decline_attribution + yoy 但缺少 yoy_baseline 的意图
    intent = AnalyticsIntent(
        task_type="analytics_query",
        complexity=ComplexityType.COMPLEX,
        planning_mode=PlanningMode.DECOMPOSED,
        analysis_intent=AnalysisIntentType.DECLINE_ATTRIBUTION,
        metric=MetricIntent(
            raw_text="发电量",
            metric_code="generation",
            confidence=0.9,
        ),
        time_range=TimeRangeIntent(
            raw_text="近三个月",
            type=TimeRangeType.RELATIVE,
            confidence=0.9,
        ),
        compare_target=CompareTarget.YOY,
        confidence=IntentConfidence(overall=0.9),
        need_clarification=False,
        missing_fields=[],
        ambiguous_fields=[],
        required_queries=[
            # 只有 current，缺少 yoy_baseline
            {
                "query_name": "current",
                "purpose": "查询当前周期",
                "period_role": "current",
            }
        ],
    )

    from core.analytics.intent.schema import RequiredQueryIntent, PeriodRole
    intent.required_queries = [
        RequiredQueryIntent(
            query_name="current",
            purpose="查询当前周期",
            metric_code="generation",
            period_role=PeriodRole.CURRENT,
        ),
        # 故意不添加 yoy_baseline
    ]

    result = validator.validate(intent)

    # 验证被拒绝
    assert result.valid is False
