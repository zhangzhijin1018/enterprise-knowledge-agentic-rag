"""经营分析规划器。

当前阶段这里不是最终版 NL2SQL Planner，
而是一个“规则优先、槽位优先、安全优先”的最小控制面模块。

为什么先做规则式 Planner：
1. 经营分析不是普通闲聊，直接自由生成 SQL 风险非常高；
2. 本轮目标是先把“意图识别 -> 槽位抽取 -> 澄清 -> SQL 模板”主链路做稳；
3. 后续如果引入 LLM 辅助 SQL 生成，也应该先经过这里形成结构化分析任务，
   而不是让 LLM 直接从原始自然语言跳到 SQL。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.analytics.metric_catalog import MetricCatalog


@dataclass(slots=True)
class AnalyticsPlan:
    """经营分析规划结果。

    这里统一把“意图识别、槽位提取、是否需要澄清”收口成一个结构，
    让 Service 层只关心编排，不再重复处理一堆散乱判断。
    """

    intent: str
    slots: dict
    required_slots: list[str]
    missing_slots: list[str]
    is_executable: bool
    clarification_question: str | None
    clarification_target_slots: list[str]
    data_source: str | None


class AnalyticsPlanner:
    """经营分析最小规划器。"""

    REQUIRED_SLOTS = ["metric", "time_range"]
    GROUP_BY_HINTS = {
        "按月": "month",
        "按月份": "month",
        "按月看": "month",
        "按月度": "month",
        "按区域": "region",
        "按区域看": "region",
        "按区域维度": "region",
        "按电站": "station",
        "按站点": "station",
        "按站点看": "station",
        "按电站维度": "station",
    }
    COMPARE_HINTS = {
        "同比": "yoy",
        "环比": "mom",
    }
    ORG_HINTS = {
        "新疆区域": {"type": "region", "value": "新疆区域"},
        "北疆区域": {"type": "region", "value": "北疆区域"},
        "南疆区域": {"type": "region", "value": "南疆区域"},
        "哈密电站": {"type": "station", "value": "哈密电站"},
        "吐鲁番电站": {"type": "station", "value": "吐鲁番电站"},
    }

    def __init__(self, metric_catalog: MetricCatalog | None = None) -> None:
        """初始化 Planner。

        这里显式依赖 `MetricCatalog`，意味着指标识别不再散落在规则代码里，
        而是统一从指标目录读取定义。
        """

        self.metric_catalog = metric_catalog or MetricCatalog()

    def plan(self, query: str, conversation_memory: dict | None = None) -> AnalyticsPlan:
        """把自然语言问题转换成结构化经营分析任务。

        业务设计说明：
        - 先抽取最小关键槽位，而不是急着生成 SQL；
        - 若 `metric + time_range` 不齐全，必须澄清，不能盲猜；
        - 会话记忆只用于“明确可继承”的信息补全，例如上一轮已经给过 time_range。
        """

        normalized_query = query.strip()
        memory = conversation_memory or {}

        short_term_memory = memory.get("short_term_memory") or {}

        metric_definition = self._extract_metric(normalized_query)
        inherited_metric = memory.get("last_metric")
        if metric_definition is None and inherited_metric:
            metric_definition = self.metric_catalog.resolve_metric(inherited_metric)
        inherited_org_scope = memory.get("last_org_scope") or None
        inherited_group_by = short_term_memory.get("last_group_by")
        inherited_compare_target = short_term_memory.get("last_compare_target")

        slots = {
            "metric": metric_definition.name if metric_definition is not None else inherited_metric,
            "time_range": self._extract_time_range(normalized_query) or memory.get("last_time_range") or None,
            "org_scope": self._extract_org_scope(normalized_query) or inherited_org_scope,
            "group_by": self._extract_group_by(normalized_query) or inherited_group_by,
            "compare_target": self._extract_compare_target(normalized_query) or inherited_compare_target,
        }

        # 清理空字典和空字符串，避免把“无意义占位值”当成已满足槽位。
        cleaned_slots = {
            key: value
            for key, value in slots.items()
            if value not in (None, "", {}, [])
        }

        missing_slots = [
            slot_name
            for slot_name in self.REQUIRED_SLOTS
            if slot_name not in cleaned_slots
        ]

        clarification_question = None
        clarification_target_slots: list[str] = []
        if missing_slots:
            clarification_question, clarification_target_slots = self._build_clarification(missing_slots)

        return AnalyticsPlan(
            intent="business_analysis",
            slots=cleaned_slots,
            required_slots=self.REQUIRED_SLOTS.copy(),
            missing_slots=missing_slots,
            is_executable=not missing_slots,
            clarification_question=clarification_question,
            clarification_target_slots=clarification_target_slots,
            data_source=metric_definition.data_source if metric_definition is not None else None,
        )

    def _extract_metric(self, query: str):
        """从问题中识别指标。

        当前阶段不再把指标词直接硬编码在 Planner 中，
        而是交给 `MetricCatalog` 统一解析别名与同义词。
        """

        return self.metric_catalog.find_metric_in_query(query)

    def _extract_time_range(self, query: str) -> dict | None:
        """解析最小时间范围。

        这里先只支持少量高频表达：
        - 上个月
        - 本月
        - `2024年3月` / `2024-03`
        - `3月` / `3月份`

        当前不是完整中文时间解析器，但已经能支撑最小经营分析闭环。
        """

        if "上个月" in query or "上月" in query:
            return {
                "type": "relative_month",
                "label": "上个月",
                "start_date": "2024-03-01",
                "end_date": "2024-03-31",
            }
        if "本月" in query or "这个月" in query:
            return {
                "type": "relative_month",
                "label": "本月",
                "start_date": "2024-04-01",
                "end_date": "2024-04-30",
            }

        explicit_month_match = re.search(r"(?:(\d{4})年)?(\d{1,2})月(?:份)?", query)
        if explicit_month_match:
            year = explicit_month_match.group(1) or "2024"
            month = int(explicit_month_match.group(2))
            last_day = 31 if month in {1, 3, 5, 7, 8, 10, 12} else 30
            if month == 2:
                last_day = 29
            return {
                "type": "explicit_month",
                "label": f"{year}年{month}月",
                "start_date": f"{year}-{month:02d}-01",
                "end_date": f"{year}-{month:02d}-{last_day:02d}",
            }

        explicit_dash_month_match = re.search(r"(\d{4})-(\d{2})", query)
        if explicit_dash_month_match:
            year = explicit_dash_month_match.group(1)
            month = int(explicit_dash_month_match.group(2))
            last_day = 31 if month in {1, 3, 5, 7, 8, 10, 12} else 30
            if month == 2:
                last_day = 29
            return {
                "type": "explicit_month",
                "label": f"{year}-{month:02d}",
                "start_date": f"{year}-{month:02d}-01",
                "end_date": f"{year}-{month:02d}-{last_day:02d}",
            }

        return None

    def _extract_org_scope(self, query: str) -> dict | None:
        """识别最小组织范围。

        当前阶段先做区域/电站两个最小层级，
        后续再扩展集团、分公司、业务板块和更细粒度组织树。
        """

        for keyword, payload in self.ORG_HINTS.items():
            if keyword in query:
                return payload
        return None

    def _extract_group_by(self, query: str) -> str | None:
        """识别 group by 维度。"""

        for keyword, value in self.GROUP_BY_HINTS.items():
            if keyword in query:
                return value
        return None

    def _extract_compare_target(self, query: str) -> str | None:
        """识别同比/环比占位。

        当前阶段先把 compare_target 解析出来，
        后续 SQL Builder 和结果解释层可以逐步增强。
        """

        for keyword, value in self.COMPARE_HINTS.items():
            if keyword in query:
                return value
        return None

    def _build_clarification(self, missing_slots: list[str]) -> tuple[str, list[str]]:
        """根据缺失槽位生成追问。

        原则：
        - 先问最关键槽位；
        - 问法尽量贴近业务语言；
        - 当前阶段一次最多追问 1~2 个关键槽位，避免问题过长。
        """

        if "metric" in missing_slots:
            return "你想看哪个指标？发电量、收入、成本、利润还是产量？", ["metric"]
        if "time_range" in missing_slots:
            return "你想看哪个时间范围？例如上个月、本月、2024年3月。", ["time_range"]
        return "当前分析条件还不完整，请补充关键分析条件。", missing_slots[:2]
