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
from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway


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
    planning_source: str
    confidence: float


class AnalyticsPlanner:
    """经营分析最小规划器。"""

    REQUIRED_SLOTS = ["metric", "time_range"]
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
        metric_catalog: MetricCatalog | None = None,
        llm_planner_gateway: LLMAnalyticsPlannerGateway | None = None,
    ) -> None:
        """初始化 Planner。

        这里显式依赖 `MetricCatalog`，意味着指标识别不再散落在规则代码里，
        而是统一从指标目录读取定义。
        """

        self.metric_catalog = metric_catalog or MetricCatalog()
        self.llm_planner_gateway = llm_planner_gateway

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
        metric_candidates = self._extract_metric_candidates(normalized_query)
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
            "top_n": self._extract_top_n(normalized_query),
            "sort_direction": self._extract_sort_direction(normalized_query),
            "secondary_metrics": [item for item in metric_candidates if item != (metric_definition.name if metric_definition else None)],
        }

        if slots["group_by"] is None:
            slots["group_by"] = self._infer_group_by_from_query(normalized_query) or inherited_group_by
        if slots["top_n"] and not slots["group_by"]:
            slots["group_by"] = "station"
        if self._is_trend_query(normalized_query) and not slots["group_by"]:
            slots["group_by"] = "month"
        if self._is_multi_metric_query(normalized_query, metric_candidates):
            # 当前 V5 仍然坚持“单次受控模板只围绕一个主指标执行”。
            # 当用户一次提出多个指标时，先把候选指标记下来并触发澄清，
            # 比静默忽略其中一个指标更安全，也更符合企业分析可解释性要求。
            slots["metric_candidates"] = metric_candidates
            slots["metric"] = None

        # 清理空字典和空字符串，避免把“无意义占位值”当成已满足槽位。
        cleaned_slots = {
            key: value
            for key, value in slots.items()
            if value not in (None, "", {}, [])
        }

        planning_source = "rule"
        confidence = self._compute_local_confidence(query=normalized_query, slots=cleaned_slots)

        # “规则优先 + LLM 补强”的关键边界：
        # 1. 先用本地确定性规则识别；
        # 2. 只有当规则置信度较低，或明显属于经营分析但关键槽位缺失时，才尝试 LLM 补强；
        # 3. 即使走了 LLM fallback，最终最小可执行条件判断仍然要回到本地确定性规则。
        if self._should_try_llm_fallback(
            query=normalized_query,
            confidence=confidence,
            slots=cleaned_slots,
        ):
            fallback_result = self.llm_planner_gateway.enhance_slots(
                query=normalized_query,
                current_slots=cleaned_slots,
                conversation_memory=memory,
            ) if self.llm_planner_gateway is not None else None

            if fallback_result is not None and fallback_result.should_use:
                planning_source = f"rule+{fallback_result.source}"
                confidence = max(confidence, fallback_result.confidence)
                cleaned_slots = self._merge_llm_slots(cleaned_slots, fallback_result.slots)

        missing_slots = [
            slot_name
            for slot_name in self.REQUIRED_SLOTS
            if slot_name not in cleaned_slots
        ]

        clarification_question = None
        clarification_target_slots: list[str] = []
        if missing_slots:
            clarification_question, clarification_target_slots = self._build_clarification(
                missing_slots=missing_slots,
                current_slots=cleaned_slots,
            )

        resolved_metric_definition = self.metric_catalog.resolve_metric(cleaned_slots.get("metric"))

        return AnalyticsPlan(
            intent="business_analysis",
            slots=cleaned_slots,
            required_slots=self.REQUIRED_SLOTS.copy(),
            missing_slots=missing_slots,
            is_executable=not missing_slots,
            clarification_question=clarification_question,
            clarification_target_slots=clarification_target_slots,
            data_source=resolved_metric_definition.data_source if resolved_metric_definition is not None else None,
            planning_source=planning_source,
            confidence=confidence,
        )

    def _extract_metric(self, query: str):
        """从问题中识别指标。

        当前阶段不再把指标词直接硬编码在 Planner 中，
        而是交给 `MetricCatalog` 统一解析别名与同义词。
        """

        return self.metric_catalog.find_metric_in_query(query)

    def _extract_metric_candidates(self, query: str) -> list[str]:
        """识别问题中出现的多个指标候选。

        典型场景：
        - “收入和成本一起看看”
        - “发电量和利润做个对比”

        当前阶段不会直接把多指标表达放开成自由 SQL，
        但会先把候选指标识别出来，后续可以：
        1. 引导用户选择当前最关心的主指标；
        2. 为未来多指标模板或报告型分析预留结构化入口。
        """

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

    def _infer_group_by_from_query(self, query: str) -> str | None:
        """从口语化表达中推断 group_by。

        例如：
        - 哪些站点最好 -> station
        - 哪些区域最差 -> region
        - 趋势 / 走势 -> month
        """

        if any(keyword in query for keyword in ("哪些站点", "哪些电站", "按站点", "按电站", "站点排名", "电站排名")):
            return "station"
        if any(keyword in query for keyword in ("哪些区域", "按区域", "区域排名")):
            return "region"
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

    def _extract_top_n(self, query: str) -> int | None:
        """识别 topN / 前 N。"""

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
        """识别排序方向。"""

        if "最差" in query or "最低" in query:
            return "asc"
        if "最好" in query or "最高" in query or "排名前" in query or "top" in query.lower():
            return "desc"
        return None

    def _is_trend_query(self, query: str) -> bool:
        """判断是否为趋势类分析。"""

        return any(keyword in query for keyword in ("趋势", "走势", "按时间", "按月看", "按月展开"))

    def _is_multi_metric_query(self, query: str, metric_candidates: list[str]) -> bool:
        """判断用户是否在一次问题中请求多个指标。"""

        if len(metric_candidates) < 2:
            return False
        return any(keyword in query for keyword in ("一起", "同时", "和", "以及"))

    def _is_analytics_like_query(self, query: str) -> bool:
        """判断是否明显属于经营分析语义。"""

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
        )
        return any(keyword in query for keyword in analytics_keywords)

    def _compute_local_confidence(self, *, query: str, slots: dict) -> float:
        """计算本地规则结果的粗粒度置信度。"""

        confidence = 0.2
        if self._is_analytics_like_query(query):
            confidence += 0.2
        if "metric" in slots:
            confidence += 0.25
        if "time_range" in slots:
            confidence += 0.25
        if "group_by" in slots or "compare_target" in slots:
            confidence += 0.1
        return min(confidence, 0.95)

    def _should_try_llm_fallback(self, *, query: str, confidence: float, slots: dict) -> bool:
        """判断是否应尝试 LLM fallback。"""

        if not self._is_analytics_like_query(query):
            return False
        if self.llm_planner_gateway is None:
            return False
        return confidence < 0.75 or "metric" not in slots or "time_range" not in slots

    def _merge_llm_slots(self, current_slots: dict, llm_slots: dict) -> dict:
        """合并 LLM 补强出的槽位。

        规则：
        - time_range 继续优先本地规则，除非当前完全没有；
        - 其他槽位允许 LLM 在当前缺失时补入；
        - 不允许 LLM 无脑覆盖本地高置信结果。
        """

        merged_slots = dict(current_slots)
        for key, value in llm_slots.items():
            if value in (None, "", {}, []):
                continue
            if key == "time_range" and "time_range" in merged_slots:
                continue
            if key not in merged_slots:
                merged_slots[key] = value
        return merged_slots

    def _build_clarification(
        self,
        *,
        missing_slots: list[str],
        current_slots: dict,
    ) -> tuple[str, list[str]]:
        """根据缺失槽位生成追问。

        原则：
        - 先问最关键槽位；
        - 问法尽量贴近业务语言；
        - 当前阶段一次最多追问 1~2 个关键槽位，避免问题过长。
        """

        if "metric" in missing_slots:
            if current_slots.get("metric_candidates"):
                metric_candidates = "、".join(current_slots["metric_candidates"])
                return (
                    f"你这次同时提到了多个指标：{metric_candidates}。当前最小版本建议先确定一个主指标，你想先看哪一个？",
                    ["metric"],
                )
            if current_slots.get("org_scope") or current_slots.get("time_range"):
                return "当前分析范围已经确定，但还缺少指标。你想看发电量、收入、成本、利润还是产量？", ["metric"]
            return "你想看哪个指标？发电量、收入、成本、利润还是产量？", ["metric"]
        if "time_range" in missing_slots:
            return "你想看哪个时间范围？例如上个月、本月、2024年3月。", ["time_range"]
        return "当前分析条件还不完整，请补充关键分析条件。", missing_slots[:2]
