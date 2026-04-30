"""Analytics ReAct Planning 触发策略。"""

from __future__ import annotations

from core.config.settings import Settings, get_settings


class AnalyticsReactPlanningPolicy:
    """判断是否需要进入局部 ReAct Planning。

    设计原则：
    - 简单问题继续走确定性 Planner，成本低、延迟低、可解释；
    - 只有复杂经营分析问题才让 LLM 做局部拆解；
    - 这个策略只决定是否尝试 ReAct，不决定是否可执行，更不能绕过 SlotValidator。
    """

    COMPLEX_HINTS = (
        "原因分析",
        "下降原因",
        "对比",
        "同比",
        "环比",
        "排名",
        "拖累",
        "贡献",
        "多指标",
        "多时间段",
        "多区域",
        "一起看看",
        "同时看",
        "哪些站点",
        "哪些区域",
        "最好",
        "最差",
    )

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def should_use_react(self, *, query: str, conversation_memory: dict | None = None) -> bool:
        """判断当前问题是否进入 ReAct planning。"""

        if not self.settings.analytics_react_planner_enabled:
            return False
        normalized_query = (query or "").strip()
        if not normalized_query:
            return False
        metric_like_count = sum(1 for keyword in ("收入", "成本", "利润", "发电", "产量") if keyword in normalized_query)
        return any(keyword in normalized_query for keyword in self.COMPLEX_HINTS) or metric_like_count >= 2
