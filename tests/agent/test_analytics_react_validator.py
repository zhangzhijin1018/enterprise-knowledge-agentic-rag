"""Analytics ReAct Plan Validator 测试。"""

from __future__ import annotations

import pytest

from core.agent.workflows.analytics.react.validator import ReactPlanValidationError, ReactPlanValidator
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.config.settings import Settings


def _validator() -> ReactPlanValidator:
    """构造测试用 validator。"""

    return ReactPlanValidator(
        metric_catalog=MetricCatalog(),
        schema_registry=SchemaRegistry(settings=Settings()),
    )


def test_react_plan_validator_cleans_valid_slots() -> None:
    """合法 slots 应被清洗成安全槽位。"""

    safe_slots = _validator().validate(
        {
            "metric": "收入",
            "time_range": {
                "type": "explicit_month",
                "label": "2024-03",
                "start_date": "2024-03-01",
                "end_date": "2024-03-31",
            },
            "group_by": "month",
            "compare_target": "yoy",
            "top_n": "5",
            "sort_direction": "desc",
        }
    )

    assert safe_slots["metric"] == "收入"
    assert safe_slots["top_n"] == 5
    assert safe_slots["compare_target"] == "yoy"


def test_react_plan_validator_rejects_sql_fields() -> None:
    """ReAct 输出不得包含 SQL 类字段。"""

    with pytest.raises(ReactPlanValidationError, match="禁止字段"):
        _validator().validate(
            {
                "metric": "收入",
                "time_range": {"label": "上个月"},
                "generated_sql": "select * from analytics_metrics_daily",
            }
        )


def test_react_plan_validator_rejects_nested_forbidden_fields() -> None:
    """嵌套危险字段也必须被拦截。"""

    with pytest.raises(ReactPlanValidationError, match="permission_override"):
        _validator().validate(
            {
                "metric": "收入",
                "org_scope": {"type": "region", "permission_override": True},
            }
        )


def test_react_plan_validator_rejects_invalid_group_by() -> None:
    """group_by 必须属于当前 schema 支持的 key。"""

    with pytest.raises(ReactPlanValidationError, match="group_by"):
        _validator().validate({"metric": "收入", "group_by": "free_dimension"})


def test_react_plan_validator_moves_unknown_metric_to_candidates() -> None:
    """未知 metric 不能直接作为可执行主指标，只能进入候选。"""

    safe_slots = _validator().validate(
        {
            "metric": "现金流",
            "time_range": {"label": "上个月"},
        }
    )

    assert "metric" not in safe_slots
    assert safe_slots["metric_candidates"] == ["现金流"]


def test_react_plan_validator_rejects_invalid_top_n_and_sort_direction() -> None:
    """top_n / sort_direction 必须在受控范围内。"""

    with pytest.raises(ReactPlanValidationError, match="top_n"):
        _validator().validate({"metric": "收入", "top_n": 101})

    with pytest.raises(ReactPlanValidationError, match="sort_direction"):
        _validator().validate({"metric": "收入", "sort_direction": "drop"})
