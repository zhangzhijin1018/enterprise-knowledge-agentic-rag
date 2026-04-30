"""Analytics ReAct Plan Validator。

LLM 输出即使经过 Prompt 约束，也必须在进入业务主链前做二次校验。

原因很简单：
1. Prompt 是软约束，模型仍可能输出 `sql / raw_sql / task_run_update` 等越界字段；
2. ReAct 子循环只允许产出 plan candidate，不能直接驱动 SQL 执行；
3. 经营分析后续会访问真实数据源，必须把“可控槽位”和“自由文本输出”隔离开。

本 Validator 的职责是把 LLM 候选 slots 清洗成安全、可解释、可交给
`AnalyticsPlanner.build_plan_from_slots()` 的 `safe_slots`。
"""

from __future__ import annotations

from typing import Any

from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry


class ReactPlanValidationError(ValueError):
    """ReAct plan candidate 校验失败。

    上层 `analytics_plan` 节点捕获该异常后，会回退到确定性 `AnalyticsPlanner`。
    这样即使 LLM 输出越界，也不会污染后续 SQL Builder / SQL Guard 主链。
    """


class ReactPlanValidator:
    """ReAct 输出二次校验器。"""

    # 只允许这些槽位进入 AnalyticsPlan。
    # 任何额外字段都必须被拒绝，不能让 LLM 自由扩展执行语义。
    ALLOWED_SLOT_KEYS = {
        "metric",
        "time_range",
        "org_scope",
        "group_by",
        "compare_target",
        "top_n",
        "sort_direction",
        "secondary_metrics",
        "metric_candidates",
    }

    # 这些字段代表执行、绕过治理或状态写入意图，一旦出现必须拒绝。
    FORBIDDEN_KEYS = {
        "sql",
        "raw_sql",
        "generated_sql",
        "checked_sql",
        "task_run_update",
        "export",
        "review",
        "permission_override",
        "sql_guard_bypass",
    }

    def __init__(self, *, metric_catalog: MetricCatalog, schema_registry: SchemaRegistry) -> None:
        self.metric_catalog = metric_catalog
        self.schema_registry = schema_registry

    def validate(self, candidate_slots: dict[str, Any]) -> dict[str, Any]:
        """校验并清洗 ReAct 输出 slots。

        返回值只包含白名单槽位。校验失败时抛出 `ReactPlanValidationError`，
        由上层触发 fallback，而不是继续使用不可信候选。
        """

        if not isinstance(candidate_slots, dict):
            raise ReactPlanValidationError("ReAct final_plan_candidate.slots 必须是 JSON object")
        self._reject_forbidden_keys(candidate_slots)

        unknown_keys = set(candidate_slots) - self.ALLOWED_SLOT_KEYS
        if unknown_keys:
            raise ReactPlanValidationError(f"ReAct slots 包含非白名单字段：{sorted(unknown_keys)}")

        safe_slots: dict[str, Any] = {}
        raw_metric = self._clean_text(candidate_slots.get("metric"))
        metric_candidates = self._clean_text_list(candidate_slots.get("metric_candidates"))
        if raw_metric:
            metric_definition = self.metric_catalog.resolve_metric(raw_metric)
            if metric_definition is not None:
                safe_slots["metric"] = metric_definition.name
            else:
                # 未识别指标不直接作为 metric 使用，只能降级进入 metric_candidates。
                # 后续 SlotValidator 会据此触发澄清，而不是盲目执行。
                metric_candidates = [raw_metric, *[item for item in metric_candidates if item != raw_metric]]
        if metric_candidates:
            safe_slots["metric_candidates"] = metric_candidates

        if "time_range" in candidate_slots and candidate_slots.get("time_range"):
            if not isinstance(candidate_slots["time_range"], dict):
                raise ReactPlanValidationError("time_range 必须是结构化对象")
            safe_slots["time_range"] = candidate_slots["time_range"]

        if "org_scope" in candidate_slots and candidate_slots.get("org_scope"):
            if not isinstance(candidate_slots["org_scope"], (dict, str)):
                raise ReactPlanValidationError("org_scope 必须是结构化对象或字符串")
            safe_slots["org_scope"] = candidate_slots["org_scope"]

        group_by = self._clean_text(candidate_slots.get("group_by"))
        if group_by:
            allowed_group_by = self._allowed_group_by_keys()
            if group_by not in allowed_group_by:
                raise ReactPlanValidationError(f"group_by 不受当前 schema 支持：{group_by}")
            safe_slots["group_by"] = group_by

        compare_target = self._clean_text(candidate_slots.get("compare_target"))
        if compare_target and compare_target != "none":
            if compare_target not in {"yoy", "mom"}:
                raise ReactPlanValidationError(f"compare_target 非法：{compare_target}")
            safe_slots["compare_target"] = compare_target

        if "top_n" in candidate_slots and candidate_slots.get("top_n") not in (None, ""):
            try:
                top_n = int(candidate_slots["top_n"])
            except (TypeError, ValueError) as exc:
                raise ReactPlanValidationError("top_n 必须是整数") from exc
            if top_n < 1 or top_n > 100:
                raise ReactPlanValidationError("top_n 必须在 1~100 范围内")
            safe_slots["top_n"] = top_n

        sort_direction = self._clean_text(candidate_slots.get("sort_direction"))
        if sort_direction:
            if sort_direction not in {"asc", "desc"}:
                raise ReactPlanValidationError(f"sort_direction 非法：{sort_direction}")
            safe_slots["sort_direction"] = sort_direction

        secondary_metrics = self._clean_text_list(candidate_slots.get("secondary_metrics"))
        if secondary_metrics:
            safe_slots["secondary_metrics"] = secondary_metrics

        return safe_slots

    def _allowed_group_by_keys(self) -> set[str]:
        """读取当前默认表支持的 group_by key。"""

        data_source = self.schema_registry.get_default_data_source()
        table_definition = self.schema_registry.get_table_definition(
            table_name=data_source.default_table,
            data_source=data_source.key,
        )
        return set(table_definition.group_by_rules.keys())

    def _reject_forbidden_keys(self, value: Any, *, path: str = "slots") -> None:
        """递归拒绝危险字段。

        不只检查顶层，是因为模型可能把 `generated_sql` 包进嵌套对象，
        如果不递归扫描，后续开发者误用时仍可能形成安全洞。
        """

        if isinstance(value, dict):
            for key, child in value.items():
                if key in self.FORBIDDEN_KEYS:
                    raise ReactPlanValidationError(f"ReAct 输出包含禁止字段：{path}.{key}")
                self._reject_forbidden_keys(child, path=f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self._reject_forbidden_keys(child, path=f"{path}[{index}]")

    def _clean_text(self, value: Any) -> str | None:
        if value in (None, ""):
            return None
        return str(value).strip() or None

    def _clean_text_list(self, value: Any) -> list[str]:
        if not value:
            return []
        if not isinstance(value, list):
            value = [value]
        cleaned: list[str] = []
        for item in value:
            text = self._clean_text(item)
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned
