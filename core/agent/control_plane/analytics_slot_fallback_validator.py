"""经营分析 LLM 槽位补强结果 Validator。

Prompt 是“软约束”：它告诉模型应该怎么输出，但不能保证模型永远遵守。
Validator 是“硬边界”：它决定哪些 LLM 输出字段可以进入业务 Planner。

本模块的核心安全原则：
- LLM fallback 只能补强槽位；
- 不能生成 SQL；
- 不能绕过 SQL Guard / 权限 / Review；
- 不能更新 task_run 等权威状态；
- 未识别指标不能直接当作 metric 执行，只能进入候选指标并触发澄清。
"""

from __future__ import annotations

from typing import Any

from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry


class AnalyticsSlotFallbackValidationError(ValueError):
    """LLM 槽位补强结果校验失败。

    上层 gateway 捕获该异常后，应回退到本地规则 Planner，
    而不是继续使用不可信的 LLM 输出。
    """


class AnalyticsSlotFallbackValidator:
    """经营分析 LLM fallback 输出二次校验器。"""

    # 允许 LLM fallback 补强的槽位白名单。
    # 这些字段仍然只代表“计划候选”，后续还要经过 SlotValidator 判断是否可执行。
    ALLOWED_SLOT_KEYS = {
        "metric",
        "time_range",
        "org_scope",
        "group_by",
        "compare_target",
        "top_n",
        "sort_direction",
        "metric_candidates",
    }

    # 一旦出现这些字段，说明模型试图越过 planning 边界进入执行/治理/状态写入层。
    # 必须直接拒绝，不能静默忽略，否则后续开发者误用时容易形成安全洞。
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

    def validate(self, slots: dict[str, Any]) -> dict[str, Any]:
        """校验并清洗 LLM fallback slots。

        返回值只包含允许进入 `AnalyticsPlanner.build_plan_from_slots()` 的安全槽位。
        这里不会判断“是否满足最小可执行条件”，因为那是 SlotValidator 的职责。
        """

        if not isinstance(slots, dict):
            raise AnalyticsSlotFallbackValidationError("LLM fallback slots 必须是 JSON object")
        self._reject_forbidden_keys(slots)

        unknown_keys = set(slots) - self.ALLOWED_SLOT_KEYS
        if unknown_keys:
            raise AnalyticsSlotFallbackValidationError(f"LLM fallback slots 包含非白名单字段：{sorted(unknown_keys)}")

        safe_slots: dict[str, Any] = {}
        metric_candidates = self._clean_text_list(slots.get("metric_candidates"))

        raw_metric = self._clean_text(slots.get("metric"))
        if raw_metric:
            metric_definition = self.metric_catalog.resolve_metric(raw_metric)
            if metric_definition is not None:
                safe_slots["metric"] = metric_definition.name
            else:
                # 未识别指标不能直接作为 metric 执行。
                # 这里只把它放入候选，后续由 clarification 让用户确认，避免盲猜指标口径。
                metric_candidates = [raw_metric, *[item for item in metric_candidates if item != raw_metric]]

        if metric_candidates:
            safe_slots["metric_candidates"] = metric_candidates

        if slots.get("time_range"):
            if not isinstance(slots["time_range"], dict):
                raise AnalyticsSlotFallbackValidationError("time_range 必须是结构化对象")
            safe_slots["time_range"] = slots["time_range"]

        if slots.get("org_scope"):
            if not isinstance(slots["org_scope"], (dict, str)):
                raise AnalyticsSlotFallbackValidationError("org_scope 必须是结构化对象或字符串")
            safe_slots["org_scope"] = slots["org_scope"]

        group_by = self._clean_text(slots.get("group_by"))
        if group_by:
            allowed_group_by = self._allowed_group_by_keys()
            if group_by not in allowed_group_by:
                raise AnalyticsSlotFallbackValidationError(f"group_by 不受当前 schema 支持：{group_by}")
            safe_slots["group_by"] = group_by

        compare_target = self._clean_text(slots.get("compare_target"))
        if compare_target and compare_target != "none":
            if compare_target not in {"yoy", "mom"}:
                raise AnalyticsSlotFallbackValidationError(f"compare_target 非法：{compare_target}")
            safe_slots["compare_target"] = compare_target

        if slots.get("top_n") not in (None, ""):
            try:
                top_n = int(slots["top_n"])
            except (TypeError, ValueError) as exc:
                raise AnalyticsSlotFallbackValidationError("top_n 必须是整数") from exc
            if top_n < 1 or top_n > 100:
                raise AnalyticsSlotFallbackValidationError("top_n 必须在 1~100 范围内")
            safe_slots["top_n"] = top_n

        sort_direction = self._clean_text(slots.get("sort_direction"))
        if sort_direction:
            if sort_direction not in {"asc", "desc"}:
                raise AnalyticsSlotFallbackValidationError(f"sort_direction 非法：{sort_direction}")
            safe_slots["sort_direction"] = sort_direction

        return safe_slots

    def _allowed_group_by_keys(self) -> set[str]:
        """从 SchemaRegistry 读取当前默认表支持的 group_by key。"""

        data_source = self.schema_registry.get_default_data_source()
        table_definition = self.schema_registry.get_table_definition(
            table_name=data_source.default_table,
            data_source=data_source.key,
        )
        return set(table_definition.group_by_rules.keys())

    def _reject_forbidden_keys(self, value: Any, *, path: str = "slots") -> None:
        """递归拒绝危险字段。

        递归扫描是必要的，因为模型可能把 `raw_sql` 等字段藏在嵌套结构里。
        如果只检查顶层，后续某个调用方误用嵌套对象时仍可能绕过边界。
        """

        if isinstance(value, dict):
            for key, child in value.items():
                if key in self.FORBIDDEN_KEYS:
                    raise AnalyticsSlotFallbackValidationError(f"LLM fallback 输出包含禁止字段：{path}.{key}")
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
