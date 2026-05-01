"""经营分析 LLM 槽位补强 Validator 测试。"""

from __future__ import annotations

import pytest

from core.agent.control_plane.analytics_slot_fallback_validator import (
    AnalyticsSlotFallbackValidationError,
    AnalyticsSlotFallbackValidator,
)
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.config.settings import Settings


def _validator() -> AnalyticsSlotFallbackValidator:
    """构造测试用 Validator。"""

    return AnalyticsSlotFallbackValidator(
        metric_catalog=MetricCatalog(),
        schema_registry=SchemaRegistry(settings=Settings()),
    )


def test_slot_fallback_validator_cleans_valid_slots() -> None:
    """合法槽位应被清洗为安全 slots。"""

    safe_slots = _validator().validate(
        {
            "metric": "营收",
            "group_by": "month",
            "compare_target": "yoy",
            "top_n": "5",
            "sort_direction": "desc",
        }
    )

    assert safe_slots["metric"] == "收入"
    assert safe_slots["group_by"] == "month"
    assert safe_slots["top_n"] == 5


def test_slot_fallback_validator_rejects_forbidden_keys() -> None:
    """LLM fallback 不能携带 SQL 或绕过治理字段。"""

    for forbidden_key in (
        "sql",
        "raw_sql",
        "generated_sql",
        "checked_sql",
        "task_run_update",
        "export",
        "review",
        "sql_guard_bypass",
    ):
        with pytest.raises(AnalyticsSlotFallbackValidationError, match="禁止字段"):
            _validator().validate({"metric": "收入", forbidden_key: "bad"})


def test_slot_fallback_validator_moves_unknown_metric_to_candidates() -> None:
    """未识别指标不能直接作为 metric，应进入候选指标。"""

    safe_slots = _validator().validate({"metric": "未知经营指标"})

    assert "metric" not in safe_slots
    assert safe_slots["metric_candidates"] == ["未知经营指标"]


def test_slot_fallback_validator_rejects_invalid_group_by() -> None:
    """group_by 必须属于 SchemaRegistry 支持的 key。"""

    with pytest.raises(AnalyticsSlotFallbackValidationError, match="group_by"):
        _validator().validate({"metric": "收入", "group_by": "free_dimension"})
