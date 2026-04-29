"""ClarificationGenerator 测试。"""

from __future__ import annotations

from core.agent.control_plane.clarification_generator import ClarificationGenerator


def test_clarification_generator_builds_missing_metric_response() -> None:
    """缺少 metric 时应生成结构化 clarification。"""

    generator = ClarificationGenerator()

    result = generator.generate(
        missing_slots=["metric"],
        conflict_slots=[],
        current_slots={"time_range": {"label": "上个月"}},
        validation_reason="缺少关键槽位：metric",
    )

    assert result.clarification_type == "missing_required_slot"
    assert result.target_slots == ["metric"]
    assert "发电量" in result.question
    assert result.suggested_options


def test_clarification_generator_builds_conflict_response() -> None:
    """多指标冲突时应生成 slot_conflict。"""

    generator = ClarificationGenerator()

    result = generator.generate(
        missing_slots=[],
        conflict_slots=["metric"],
        current_slots={"metric_candidates": ["收入", "成本"]},
        validation_reason="存在冲突槽位：metric",
    )

    assert result.clarification_type == "slot_conflict"
    assert result.target_slots == ["metric"]
    assert result.suggested_options == ["收入", "成本"]
