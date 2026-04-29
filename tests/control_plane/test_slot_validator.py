"""SlotValidator 测试。"""

from __future__ import annotations

from core.agent.control_plane.slot_validator import SlotValidator


def test_slot_validator_detects_missing_metric() -> None:
    """缺少 metric 时应返回 missing_slots。"""

    validator = SlotValidator()

    result = validator.validate(
        {
            "time_range": {"label": "上个月"},
        }
    )

    assert result.is_executable is False
    assert result.missing_slots == ["metric"]
    assert result.conflict_slots == []


def test_slot_validator_detects_missing_time_range() -> None:
    """缺少 time_range 时应返回 missing_slots。"""

    validator = SlotValidator()

    result = validator.validate(
        {
            "metric": "发电量",
        }
    )

    assert result.is_executable is False
    assert result.missing_slots == ["time_range"]


def test_slot_validator_detects_multi_metric_conflict() -> None:
    """多主指标表达时应触发冲突。"""

    validator = SlotValidator()

    result = validator.validate(
        {
            "time_range": {"label": "近一个月"},
            "metric_candidates": ["收入", "成本"],
        }
    )

    assert result.is_executable is False
    assert result.conflict_slots == ["metric"]
