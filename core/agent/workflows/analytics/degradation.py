"""经营分析 Workflow 最小降级策略。

降级的核心原则不是“静默吞错”，而是：

1. 对可选增强能力做温和降级；
2. 对核心真实性能力绝不伪造结果。

因此当前允许降级的只有：
- `chart_spec`
- `insight_cards`
- `report_blocks`

而不允许降级伪造成功的环节包括：
- SQL 执行失败
- SQL Guard 拦截
- 权限 / 数据范围治理失败
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class DegradationRecord:
    """单次降级记录。"""

    feature: str
    reason: str


class AnalyticsWorkflowDegradationController:
    """经营分析 workflow 轻量降级控制器。"""

    def mark_degraded(
        self,
        *,
        state: dict[str, Any],
        feature: str,
        reason: str,
    ) -> None:
        """在 workflow state 中记录降级结果。"""

        state["degraded"] = True
        state.setdefault("degraded_features", [])
        if feature not in state["degraded_features"]:
            state["degraded_features"].append(feature)
        state.setdefault("degradation_history", [])
        record = DegradationRecord(feature=feature, reason=reason)
        state["degradation_history"].append(
            {
                "feature": record.feature,
                "reason": record.reason,
            }
        )
