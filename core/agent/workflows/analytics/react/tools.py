"""Analytics ReAct Planning 允许工具。

这些工具只服务于 planning：
- 查指标目录；
- 查 schema registry；
- 查会话记忆；
- 做业务术语归一。

它们不能执行 SQL、不能绕过 SQL Guard、不能写 task_run、不能触发 export/review。
"""

from __future__ import annotations

from typing import Any

from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.common.exceptions import AppException


ALLOWED_REACT_TOOLS = {
    "metric_catalog_lookup",
    "schema_registry_lookup",
    "conversation_memory_lookup",
    "business_term_normalize",
}

FORBIDDEN_REACT_TOOLS = {
    "sql_execute",
    "sql_guard_bypass",
    "export",
    "review",
    "task_run_update",
}


class AnalyticsReactToolRegistry:
    """ReAct planning 工具白名单。"""

    def __init__(self, *, metric_catalog: MetricCatalog, schema_registry: SchemaRegistry) -> None:
        self.metric_catalog = metric_catalog
        self.schema_registry = schema_registry

    def run(self, *, tool_name: str, tool_input: dict[str, Any], conversation_memory: dict[str, Any]) -> dict[str, Any]:
        """执行允许的 planning 工具。

        如果模型请求了非白名单动作，这里明确拒绝。拒绝本身不会触发 SQL 或状态写入，
        只会让 ReAct planner 停止并回退到确定性 Planner。
        """

        clean_tool_name = str(tool_name or "").strip()
        clean_tool_input = self._clean_tool_input(tool_input)
        if clean_tool_name not in ALLOWED_REACT_TOOLS:
            return {"allowed": False, "reason": "tool_not_allowed", "tool_name": clean_tool_name}
        if clean_tool_name == "metric_catalog_lookup":
            return self._metric_catalog_lookup(clean_tool_input)
        if clean_tool_name == "schema_registry_lookup":
            return self._schema_registry_lookup(clean_tool_input)
        if clean_tool_name == "conversation_memory_lookup":
            return {"allowed": True, "memory": conversation_memory}
        if clean_tool_name == "business_term_normalize":
            return self._business_term_normalize(clean_tool_input)
        return {"allowed": False, "reason": "unknown_tool", "tool_name": clean_tool_name}

    def _metric_catalog_lookup(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        raw_text = str(tool_input.get("metric") or tool_input.get("query") or "")
        definition = self.metric_catalog.resolve_metric(raw_text) or self.metric_catalog.find_metric_in_query(raw_text)
        if definition is None:
            return {
                "allowed": True,
                "matched": False,
                "metric_names": self.metric_catalog.list_metric_names(),
            }
        return {
            "allowed": True,
            "matched": True,
            "metric": definition.name,
            "metric_code": definition.metric_code,
            "aliases": definition.aliases,
            "sensitivity_level": definition.sensitivity_level,
        }

    def _schema_registry_lookup(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        data_source = self._clean_text(tool_input.get("data_source"))
        if not data_source:
            # data_source 为空时使用默认数据源。
            # 这是 planning 只读查询，不会触发真实数据库访问，也不会绕过后续 SQL Guard。
            source_definition = self.schema_registry.get_default_data_source()
        else:
            try:
                source_definition = self.schema_registry.get_data_source(data_source)
            except (AppException, KeyError):
                return {
                    "allowed": True,
                    "matched": False,
                    "reason": "data_source_not_found",
                    "data_source": data_source,
                }
        table_definition = self.schema_registry.get_table_definition(
            table_name=source_definition.default_table,
            data_source=source_definition.key,
        )
        return {
            "allowed": True,
            "data_source": source_definition.key,
            "default_table": table_definition.name,
            "group_by_keys": list(table_definition.group_by_rules.keys()),
            "field_whitelist": table_definition.field_whitelist,
        }

    def _business_term_normalize(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        text = str(tool_input.get("text") or tool_input.get("query") or "")
        normalized: dict[str, Any] = {}
        if "同比" in text:
            normalized["compare_target"] = "yoy"
        if "环比" in text:
            normalized["compare_target"] = "mom"
        if any(keyword in text for keyword in ("排名", "前几", "最好", "最差", "top")):
            normalized["ranking_intent"] = True
        if any(keyword in text for keyword in ("按月", "趋势", "时间序列")):
            normalized["group_by"] = "month"
        return {"allowed": True, "normalized_terms": normalized}

    def _clean_tool_input(self, tool_input: dict[str, Any] | None) -> dict[str, Any]:
        """对模型传入的 tool_input 做最小清洗。

        ReAct 工具只允许 planning 只读能力。这里不会执行任何 SQL，
        也不会把模型传入的复杂对象原样转发到状态写入或外部系统。
        """

        if not isinstance(tool_input, dict):
            return {}
        clean: dict[str, Any] = {}
        for key, value in tool_input.items():
            clean_key = self._clean_text(key)
            if not clean_key:
                continue
            if isinstance(value, str):
                clean[clean_key] = value.strip()
            elif isinstance(value, (int, float, bool)) or value is None:
                clean[clean_key] = value
            elif isinstance(value, list):
                clean[clean_key] = [item for item in value if isinstance(item, (str, int, float, bool))]
            elif isinstance(value, dict):
                clean[clean_key] = {
                    str(child_key).strip(): child_value
                    for child_key, child_value in value.items()
                    if isinstance(child_value, (str, int, float, bool)) or child_value is None
                }
        return clean

    def _clean_text(self, value: Any) -> str | None:
        if value in (None, ""):
            return None
        return str(value).strip() or None
