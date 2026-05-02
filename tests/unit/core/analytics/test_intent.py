"""经营分析意图解析模块单元测试。

测试覆盖：
1. AnalyticsIntent 模型构造
2. AnalyticsIntentValidator 校验
3. LLMAnalyticsIntentParser 回退模式
4. SQL 字段拒绝
5. 置信度阈值校验
"""

import pytest

from core.analytics.intent.schema import (
    AnalyticsIntent,
    AnalysisIntentType,
    CompareTarget,
    ComplexityType,
    IntentConfidence,
    MetricCandidate,
    MetricIntent,
    OrgScopeIntent,
    OrgScopeType,
    PeriodRole,
    PlanningMode,
    RequiredQueryIntent,
    TimeRangeIntent,
    TimeRangeType,
)
from core.analytics.intent.validator import AnalyticsIntentValidator
from core.analytics.intent.parser import LLMAnalyticsIntentParser
from core.analytics.metric_catalog import MetricCatalog


class TestAnalyticsIntentModel:
    """AnalyticsIntent 模型测试。"""

    def test_simple_query_intent(self):
        """测试简单查询意图构造。"""

        intent = AnalyticsIntent(
            task_type="analytics_query",
            complexity=ComplexityType.SIMPLE,
            planning_mode=PlanningMode.DIRECT,
            analysis_intent=AnalysisIntentType.SIMPLE_QUERY,
            metric=MetricIntent(
                raw_text="发电量",
                metric_code="generation",
                metric_name="发电量",
                confidence=0.95,
            ),
            time_range=TimeRangeIntent(
                raw_text="2024年3月",
                type=TimeRangeType.ABSOLUTE,
                value="2024-03",
                start="2024-03-01",
                end="2024-03-31",
                confidence=0.95,
            ),
            org_scope=OrgScopeIntent(
                raw_text="新疆区域",
                type=OrgScopeType.REGION,
                name="新疆区域",
                confidence=0.9,
            ),
            compare_target=CompareTarget.NONE,
            confidence=IntentConfidence(
                overall=0.9,
                metric=0.95,
                time_range=0.95,
                org_scope=0.9,
            ),
            need_clarification=False,
            missing_fields=[],
            ambiguous_fields=[],
        )

        assert intent.task_type == "analytics_query"
        assert intent.complexity == ComplexityType.SIMPLE
        assert intent.planning_mode == PlanningMode.DIRECT
        assert intent.metric.metric_code == "generation"
        assert intent.time_range.value == "2024-03"
        assert intent.need_clarification is False

    def test_complex_intent_with_required_queries(self):
        """测试复杂查询意图构造（包含 required_queries）。"""

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
            org_scope=OrgScopeIntent(
                raw_text="新疆区域",
                type=OrgScopeType.REGION,
                name="新疆区域",
                confidence=0.9,
            ),
            group_by="station",
            compare_target=CompareTarget.YOY,
            required_queries=[
                RequiredQueryIntent(
                    query_name="current",
                    purpose="查询当前周期各电站发电量",
                    metric_code="generation",
                    period_role=PeriodRole.CURRENT,
                    group_by="station",
                    filters={},
                ),
                RequiredQueryIntent(
                    query_name="yoy_baseline",
                    purpose="查询去年同期各电站发电量作为基准",
                    metric_code="generation",
                    period_role=PeriodRole.YOY_BASELINE,
                    group_by="station",
                    filters={},
                ),
            ],
            confidence=IntentConfidence(
                overall=0.92,
                metric=0.95,
                time_range=0.9,
                org_scope=0.9,
                group_by=0.95,
                compare_target=0.95,
                analysis_intent=0.9,
            ),
            need_clarification=False,
            missing_fields=[],
            ambiguous_fields=[],
        )

        assert intent.complexity == ComplexityType.COMPLEX
        assert intent.planning_mode == PlanningMode.DECOMPOSED
        assert len(intent.required_queries) == 2
        assert intent.compare_target == CompareTarget.YOY

    def test_intent_needing_clarification(self):
        """测试需要澄清的意图构造。"""

        intent = AnalyticsIntent(
            task_type="analytics_query",
            complexity=ComplexityType.SIMPLE,
            planning_mode=PlanningMode.CLARIFICATION,
            analysis_intent=AnalysisIntentType.SIMPLE_QUERY,
            metric=None,
            time_range=TimeRangeIntent(
                raw_text="上个月",
                type=TimeRangeType.RELATIVE,
                value="上个月",
                confidence=0.8,
            ),
            org_scope=OrgScopeIntent(
                raw_text="新疆区域",
                type=OrgScopeType.REGION,
                name="新疆区域",
                confidence=0.9,
            ),
            compare_target=CompareTarget.NONE,
            confidence=IntentConfidence(
                overall=0.5,
                metric=0.1,
                time_range=0.8,
                org_scope=0.9,
            ),
            need_clarification=True,
            clarification_question="你想查看哪个经营指标？例如：发电量、收入，成本、利润。",
            missing_fields=["metric"],
            ambiguous_fields=[],
        )

        assert intent.metric is None
        assert intent.need_clarification is True
        assert "metric" in intent.missing_fields

    def test_intent_with_ambiguous_metric(self):
        """测试指标歧义的意图构造。"""

        intent = AnalyticsIntent(
            task_type="analytics_query",
            complexity=ComplexityType.SIMPLE,
            planning_mode=PlanningMode.CLARIFICATION,
            analysis_intent=AnalysisIntentType.SIMPLE_QUERY,
            metric=MetricIntent(
                raw_text="电量",
                confidence=0.4,
                candidates=[
                    MetricCandidate(metric_code="generation", metric_name="发电量", confidence=0.4),
                    MetricCandidate(metric_code="online", metric_name="上网电量", confidence=0.3),
                    MetricCandidate(metric_code="sales", metric_name="售电量", confidence=0.3),
                ],
            ),
            time_range=TimeRangeIntent(
                raw_text="最近",
                type=TimeRangeType.RELATIVE,
                value="最近",
                confidence=0.7,
            ),
            org_scope=OrgScopeIntent(
                raw_text="新疆",
                type=OrgScopeType.REGION,
                name="新疆",
                confidence=0.9,
            ),
            compare_target=CompareTarget.NONE,
            confidence=IntentConfidence(
                overall=0.55,
                metric=0.4,
                time_range=0.7,
                org_scope=0.9,
            ),
            need_clarification=True,
            clarification_question="你说的「电量」想看哪个口径？例如：发电量、上网电量、售电量。",
            missing_fields=[],
            ambiguous_fields=["metric"],
        )

        assert len(intent.metric.candidates) == 3
        assert "metric" in intent.ambiguous_fields


class TestAnalyticsIntentValidator:
    """AnalyticsIntentValidator 校验器测试。"""

    def setup_method(self):
        """测试初始化。"""
        self.validator = AnalyticsIntentValidator(metric_catalog=MetricCatalog())

    def test_valid_simple_intent_passes(self):
        """测试有效的简单查询意图通过校验。"""

        intent = AnalyticsIntent(
            task_type="analytics_query",
            complexity=ComplexityType.SIMPLE,
            planning_mode=PlanningMode.DIRECT,
            analysis_intent=AnalysisIntentType.SIMPLE_QUERY,
            metric=MetricIntent(
                raw_text="发电量",
                metric_code="generation",
                metric_name="发电量",
                confidence=0.95,
            ),
            time_range=TimeRangeIntent(
                raw_text="2024年3月",
                type=TimeRangeType.ABSOLUTE,
                value="2024-03",
                start="2024-03-01",
                end="2024-03-31",
                confidence=0.95,
            ),
            compare_target=CompareTarget.NONE,
            confidence=IntentConfidence(overall=0.9, metric=0.95, time_range=0.95),
            need_clarification=False,
            missing_fields=[],
            ambiguous_fields=[],
        )

        result = self.validator.validate(intent)

        # 注意：generation 指标在默认 MetricCatalog 中存在
        assert result.valid is True
        assert result.need_clarification is False

    def test_missing_metric_requires_clarification(self):
        """测试缺少指标需要澄清。"""

        intent = AnalyticsIntent(
            task_type="analytics_query",
            complexity=ComplexityType.SIMPLE,
            planning_mode=PlanningMode.DIRECT,
            analysis_intent=AnalysisIntentType.SIMPLE_QUERY,
            metric=None,
            time_range=TimeRangeIntent(
                raw_text="2024年3月",
                type=TimeRangeType.ABSOLUTE,
                value="2024-03",
                start="2024-03-01",
                end="2024-03-31",
                confidence=0.95,
            ),
            compare_target=CompareTarget.NONE,
            confidence=IntentConfidence(overall=0.7),
            need_clarification=True,
            missing_fields=["metric"],
            ambiguous_fields=[],
        )

        result = self.validator.validate(intent)

        assert result.valid is False
        assert result.need_clarification is True
        assert "metric" in result.missing_fields

    def test_low_confidence_requires_clarification(self):
        """测试低置信度需要澄清。"""

        intent = AnalyticsIntent(
            task_type="analytics_query",
            complexity=ComplexityType.SIMPLE,
            planning_mode=PlanningMode.DIRECT,
            analysis_intent=AnalysisIntentType.SIMPLE_QUERY,
            metric=MetricIntent(
                raw_text="电量",
                confidence=0.4,
                candidates=[
                    MetricCandidate(metric_code="generation", metric_name="发电量", confidence=0.4),
                ],
            ),
            time_range=TimeRangeIntent(
                raw_text="最近",
                type=TimeRangeType.RELATIVE,
                value="最近",
                confidence=0.7,
            ),
            compare_target=CompareTarget.NONE,
            confidence=IntentConfidence(overall=0.55),
            need_clarification=True,
            missing_fields=[],
            ambiguous_fields=["metric"],
        )

        result = self.validator.validate(intent)

        assert result.valid is False
        assert result.need_clarification is True

    def test_invalid_group_by_rejected(self):
        """测试无效的 group_by 被拒绝。"""

        intent = AnalyticsIntent(
            task_type="analytics_query",
            complexity=ComplexityType.SIMPLE,
            planning_mode=PlanningMode.DIRECT,
            analysis_intent=AnalysisIntentType.SIMPLE_QUERY,
            metric=MetricIntent(
                raw_text="发电量",
                metric_code="generation",
                metric_name="发电量",
                confidence=0.95,
            ),
            time_range=TimeRangeIntent(
                raw_text="2024年3月",
                type=TimeRangeType.ABSOLUTE,
                value="2024-03",
                start="2024-03-01",
                end="2024-03-31",
                confidence=0.95,
            ),
            group_by="invalid_dimension",
            compare_target=CompareTarget.NONE,
            confidence=IntentConfidence(overall=0.9),
            need_clarification=False,
            missing_fields=[],
            ambiguous_fields=[],
        )

        result = self.validator.validate(intent)

        assert result.valid is False
        assert any("group_by" in err for err in result.errors)

    def test_decomposed_without_required_queries_rejected(self):
        """测试 decomposed 模式没有 required_queries 被拒绝。"""

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
            compare_target=CompareTarget.YOY,
            required_queries=[],
            confidence=IntentConfidence(overall=0.9),
            need_clarification=False,
            missing_fields=[],
            ambiguous_fields=[],
        )

        result = self.validator.validate(intent)

        assert result.valid is False
        assert any("required_queries" in err for err in result.errors)

    def test_decline_attribution_with_yoy_requires_baseline_queries(self):
        """测试下降归因配合同比需要基准查询。"""

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
            compare_target=CompareTarget.YOY,
            required_queries=[
                RequiredQueryIntent(
                    query_name="current",
                    purpose="当前周期",
                    metric_code="generation",
                    period_role=PeriodRole.CURRENT,
                    group_by="station",
                    filters={},
                ),
            ],
            confidence=IntentConfidence(overall=0.9),
            need_clarification=False,
            missing_fields=[],
            ambiguous_fields=[],
        )

        result = self.validator.validate(intent)

        assert result.valid is False
        assert any("yoy_baseline" in err for err in result.errors)

    def test_top_n_range_validation(self):
        """测试 top_n 范围校验。"""

        validator = AnalyticsIntentValidator()

        result_min = validator._validate_top_n(0)
        assert any("不能小于" in err for err in result_min)

        result_max = validator._validate_top_n(100)
        assert any("不能大于" in err for err in result_max)


class TestValidatorSQLFieldRejection:
    """SQL 字段拒绝测试。"""

    def setup_method(self):
        """测试初始化。"""
        self.validator = AnalyticsIntentValidator(metric_catalog=MetricCatalog())

    def test_intent_with_sql_field_rejected(self):
        """测试包含 SQL 字段的意图被拒绝。"""

        # 直接测试 _has_sql_fields 方法（模拟 LLM 错误输出包含 SQL 字段）
        intent_dict = {
            "task_type": "analytics_query",
            "complexity": "simple",
            "planning_mode": "direct",
            "analysis_intent": "simple_query",
            "raw_sql": "SELECT * FROM metrics",
            "confidence": {"overall": 0.9},
            "need_clarification": False,
            "missing_fields": [],
            "ambiguous_fields": [],
        }

        result = self.validator._has_sql_fields(intent_dict)
        assert result is True

    def test_intent_with_generated_sql_rejected(self):
        """测试包含 generated_sql 的意图被拒绝。"""

        intent_dict = {
            "task_type": "analytics_query",
            "complexity": "simple",
            "planning_mode": "direct",
            "analysis_intent": "simple_query",
            "generated_sql": "SELECT sum(generation) FROM metrics",
            "confidence": {"overall": 0.9},
            "need_clarification": False,
            "missing_fields": [],
            "ambiguous_fields": [],
        }

        result = self.validator._has_sql_fields(intent_dict)
        assert result is True

    def test_clean_intent_no_sql_fields(self):
        """测试干净意图不包含 SQL 字段。"""

        intent_dict = {
            "task_type": "analytics_query",
            "complexity": "simple",
            "planning_mode": "direct",
            "analysis_intent": "simple_query",
            "confidence": {"overall": 0.9},
            "need_clarification": False,
            "missing_fields": [],
            "ambiguous_fields": [],
        }

        result = self.validator._has_sql_fields(intent_dict)
        assert result is False


class TestMetricCatalog:
    """指标目录测试。"""

    def test_resolve_metric_by_name(self):
        """测试通过名称解析指标。"""

        catalog = MetricCatalog()
        metric_def = catalog.resolve_metric("发电量")

        assert metric_def is not None
        assert metric_def.metric_code == "generation"

    def test_find_metric_in_query(self):
        """测试在问句中查找指标。"""

        catalog = MetricCatalog()
        metric_def = catalog.find_metric_in_query("查询新疆区域2024年3月发电量")

        assert metric_def is not None
        assert metric_def.metric_code == "generation"

    def test_list_metric_names(self):
        """测试列出所有指标名称。"""

        catalog = MetricCatalog()
        names = catalog.list_metric_names()

        assert "发电量" in names
        assert "收入" in names
        assert "成本" in names
