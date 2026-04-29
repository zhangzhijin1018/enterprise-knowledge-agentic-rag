"""经营分析语义补强器。

职责边界：
1. 负责口语化表达解析；
2. 负责继承多轮上下文中的可承接槽位；
3. 负责在低置信场景下调用 LLM planner gateway 做结构化补强；
4. 输出仍然必须是结构化 slots，绝不直接输出 SQL。

关键原则：
- 语义补强可以使用规则、memory、LLM fallback；
- 但“是否满足最小可执行条件”不在这里决定，而交给 SlotValidator；
- 这样可以保证 LLM 只能补槽位，不能越权跳过 clarification。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.analytics.metric_catalog import MetricCatalog
from core.agent.control_plane.llm_analytics_planner import (
    LLMAnalyticsPlannerGateway,
    LLMAnalyticsPlannerResult,
)


@dataclass(slots=True)
class SemanticResolutionResult:
    """语义补强结果。"""

    slots: dict
    planning_source: str
    confidence: float
    llm_result: LLMAnalyticsPlannerResult | None = None


class SemanticResolver:
    """经营分析语义补强器。"""

    GROUP_BY_HINTS = {
        "按月": "month",
        "按月份": "month",
        "按月看": "month",
        "按月度": "month",
        "按月展开": "month",
        "按时间展开": "month",
        "按时间序列": "month",
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
        "新疆这边": {"type": "region", "value": "新疆区域"},
        "新疆": {"type": "region", "value": "新疆区域"},
        "北疆区域": {"type": "region", "value": "北疆区域"},
        "北疆": {"type": "region", "value": "北疆区域"},
        "南疆区域": {"type": "region", "value": "南疆区域"},
        "南疆": {"type": "region", "value": "南疆区域"},
        "哈密电站": {"type": "station", "value": "哈密电站"},
        "吐鲁番电站": {"type": "station", "value": "吐鲁番电站"},
    }

    def __init__(
        self,
        *,
        metric_catalog: MetricCatalog,
        llm_planner_gateway: LLMAnalyticsPlannerGateway | None = None,
    ) -> None:
        self.metric_catalog = metric_catalog
        self.llm_planner_gateway = llm_planner_gateway

    def resolve(self, *, query: str, conversation_memory: dict | None = None) -> SemanticResolutionResult:
        """把自然语言问题补强为结构化槽位。"""

        normalized_query = query.strip()
        memory = conversation_memory or {}
        short_term_memory = memory.get("short_term_memory") or {}

        metric_definition = self._extract_metric(normalized_query)
        metric_candidates = self._extract_metric_candidates(normalized_query)
        inherited_metric = memory.get("last_metric")
        if metric_definition is None and inherited_metric:
            metric_definition = self.metric_catalog.resolve_metric(inherited_metric)

        inherited_org_scope = memory.get("last_org_scope") or None
        inherited_group_by = short_term_memory.get("last_group_by")
        inherited_compare_target = short_term_memory.get("last_compare_target")
        inherited_top_n = short_term_memory.get("last_top_n")
        inherited_sort_direction = short_term_memory.get("last_sort_direction")

        slots = {
            "metric": metric_definition.name if metric_definition is not None else inherited_metric,
            "time_range": self._extract_time_range(normalized_query) or memory.get("last_time_range") or None,
            "org_scope": self._extract_org_scope(normalized_query) or inherited_org_scope,
            "group_by": self._extract_group_by(normalized_query) or inherited_group_by,
            "compare_target": self._extract_compare_target(normalized_query) or inherited_compare_target,
            "top_n": self._extract_top_n(normalized_query) or inherited_top_n,
            "sort_direction": self._extract_sort_direction(normalized_query) or inherited_sort_direction,
            "secondary_metrics": [
                item
                for item in metric_candidates
                if item != (metric_definition.name if metric_definition else inherited_metric)
            ],
        }

        if slots["group_by"] is None:
            slots["group_by"] = self._infer_group_by_from_query(normalized_query) or inherited_group_by
        if slots["top_n"] and not slots["group_by"]:
            slots["group_by"] = "station"
        if self._is_trend_query(normalized_query) and not slots["group_by"]:
            slots["group_by"] = "month"

        if self._is_multi_metric_query(normalized_query, metric_candidates):
            slots["metric_candidates"] = metric_candidates
            slots["metric"] = None

        # “那收入呢”“新疆换成北疆”“只看哈密电站”这类表达都属于增量修改：
        # - 用户没有重复整句条件；
        # - 但明显是在上一轮分析上下文上替换一个槽位。
        # 因此这里优先承接 memory，再覆盖当前明确说出的新值。
        if self._should_merge_with_existing_metric(query=normalized_query, metric_candidates=metric_candidates, inherited_metric=inherited_metric):
            slots["metric_candidates"] = [inherited_metric, *[item for item in metric_candidates if item != inherited_metric]]
            slots["metric"] = None

        cleaned_slots = {
            key: value
            for key, value in slots.items()
            if value not in (None, "", {}, [])
        }

        planning_source = "rule"
        confidence = self._compute_local_confidence(query=normalized_query, slots=cleaned_slots)
        llm_result: LLMAnalyticsPlannerResult | None = None

        if self._should_try_llm_fallback(
            query=normalized_query,
            confidence=confidence,
            slots=cleaned_slots,
        ):
            llm_result = self.llm_planner_gateway.enhance_slots(
                query=normalized_query,
                current_slots=cleaned_slots,
                conversation_memory=memory,
            ) if self.llm_planner_gateway is not None else None

            if llm_result is not None and llm_result.should_use:
                planning_source = f"rule+{llm_result.source}"
                confidence = max(confidence, llm_result.confidence)
                cleaned_slots = self._merge_llm_slots(cleaned_slots, llm_result.slots)

        return SemanticResolutionResult(
            slots=cleaned_slots,
            planning_source=planning_source,
            confidence=confidence,
            llm_result=llm_result,
        )

    def _extract_metric(self, query: str):
        return self.metric_catalog.find_metric_in_query(query)

    def _extract_metric_candidates(self, query: str) -> list[str]:
        candidates: list[str] = []
        for metric_name in self.metric_catalog.list_metric_names():
            metric_definition = self.metric_catalog.resolve_metric(metric_name)
            if metric_definition is None:
                continue
            keywords = [metric_definition.name, *metric_definition.aliases]
            if any(keyword in query for keyword in keywords) and metric_definition.name not in candidates:
                candidates.append(metric_definition.name)
        return candidates

    def _extract_time_range(self, query: str) -> dict | None:
        if "上个月" in query or "上月" in query:
            return {
                "type": "relative_month",
                "label": "上个月",
                "start_date": "2024-03-01",
                "end_date": "2024-03-31",
            }
        if "最近这段时间" in query or "近一个月" in query or "最近" in query:
            return {
                "type": "relative_30_days",
                "label": "近一个月",
                "start_date": "2024-03-02",
                "end_date": "2024-04-01",
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
        matched_items: list[tuple[int, int, dict]] = []
        for keyword, payload in self.ORG_HINTS.items():
            position = query.rfind(keyword)
            if position >= 0:
                matched_items.append((position, len(keyword), payload))
        if not matched_items:
            return None
        matched_items.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return matched_items[0][2]

    def _extract_group_by(self, query: str) -> str | None:
        for keyword, value in self.GROUP_BY_HINTS.items():
            if keyword in query:
                return value
        return None

    def _infer_group_by_from_query(self, query: str) -> str | None:
        if any(keyword in query for keyword in ("哪些站点", "哪些电站", "按站点", "按电站", "站点排名", "电站排名")):
            return "station"
        if any(keyword in query for keyword in ("哪些区域", "按区域", "区域排名")):
            return "region"
        return None

    def _extract_compare_target(self, query: str) -> str | None:
        for keyword, value in self.COMPARE_HINTS.items():
            if keyword in query:
                return value
        return None

    def _extract_top_n(self, query: str) -> int | None:
        topn_match = re.search(r"top\s*(\d+)", query, flags=re.IGNORECASE)
        if topn_match:
            return int(topn_match.group(1))
        chinese_topn_match = re.search(r"前(\d+)", query)
        if chinese_topn_match:
            return int(chinese_topn_match.group(1))
        if "前几" in query or "最好" in query or "最差" in query:
            return 5
        return None

    def _extract_sort_direction(self, query: str) -> str | None:
        if "最差" in query or "最低" in query:
            return "asc"
        if "最好" in query or "最高" in query or "排名前" in query or "top" in query.lower():
            return "desc"
        return None

    def _is_trend_query(self, query: str) -> bool:
        return any(keyword in query for keyword in ("趋势", "走势", "按时间", "按月看", "按月展开"))

    def _is_multi_metric_query(self, query: str, metric_candidates: list[str]) -> bool:
        """判断当前问题是否属于多指标并列表达。

        设计原因：
        - 当前阶段的经营分析仍然坚持“单主指标执行”；
        - 如果用户一次同时提出“收入和成本一起看看”这类并列诉求，
          系统不能私自挑一个指标执行，也不能把多个指标静默压缩成一个指标；
        - 因此这里要先把它识别为冲突/歧义表达，后续由 clarification 明确主指标。

        注意：
        - 这里只负责识别“是否像多指标并列表达”；
        - 不负责决定是否可执行，真正的最小可执行条件仍由 SlotValidator 统一判断。
        """

        if len(metric_candidates) < 2:
            return False
        return any(keyword in query for keyword in ("一起", "同时", "和", "以及", "也加进来"))

    def _should_merge_with_existing_metric(
        self,
        *,
        query: str,
        metric_candidates: list[str],
        inherited_metric: str | None,
    ) -> bool:
        if inherited_metric is None or not metric_candidates:
            return False
        if len(metric_candidates) >= 2:
            return True
        return any(keyword in query for keyword in ("也加进来", "一起看看", "同时看", "再把"))

    def _is_analytics_like_query(self, query: str) -> bool:
        analytics_keywords = (
            "分析",
            "统计",
            "指标",
            "情况",
            "表现",
            "收入",
            "成本",
            "利润",
            "发电",
            "同比",
            "环比",
            "top",
            "排名",
            "最好",
            "最差",
            "展开",
            "换成",
            "改成",
        )
        return any(keyword in query for keyword in analytics_keywords)

    def _compute_local_confidence(self, *, query: str, slots: dict) -> float:
        confidence = 0.2
        if self._is_analytics_like_query(query):
            confidence += 0.2
        if "metric" in slots:
            confidence += 0.25
        if "time_range" in slots:
            confidence += 0.25
        if "group_by" in slots or "compare_target" in slots:
            confidence += 0.1
        if "org_scope" in slots:
            confidence += 0.05
        return min(confidence, 0.95)

    def _should_try_llm_fallback(self, *, query: str, confidence: float, slots: dict) -> bool:
        if not self._is_analytics_like_query(query):
            return False
        if self.llm_planner_gateway is None:
            return False
        return confidence < 0.75 or "metric" not in slots or "time_range" not in slots

    def _merge_llm_slots(self, current_slots: dict, llm_slots: dict) -> dict:
        merged_slots = dict(current_slots)
        for key, value in llm_slots.items():
            if value in (None, "", {}, []):
                continue
            if key == "time_range" and "time_range" in merged_slots:
                continue
            if key not in merged_slots:
                merged_slots[key] = value
        return merged_slots
