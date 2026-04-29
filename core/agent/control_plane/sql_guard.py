"""经营分析 SQL 安全检查器。

为什么必须先有 SQL Guard：
1. 经营分析最终会落到真实业务数据库，不能让自由 SQL 直接执行；
2. 即使当前阶段还是规则模板，也要把“生成 SQL”和“检查 SQL”显式拆开；
3. 后续一旦引入 LLM 辅助 SQL 生成，SQL Guard 会成为最后一道硬安全边界。

当前阶段提供的能力：
- 只允许只读查询；
- 禁止 DDL / DML；
- 禁止多语句；
- 表白名单；
- 自动补 LIMIT；
- 字段白名单预留。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class SQLGuardResult:
    """SQL 安全检查结果。"""

    is_safe: bool
    checked_sql: str | None
    blocked_reason: str | None
    governance_detail: dict | None = None


class SQLGuard:
    """最小 SQL Guard。"""

    DANGEROUS_KEYWORDS = (
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "TRUNCATE",
        "CREATE",
        "GRANT",
        "REVOKE",
        "MERGE",
        "ATTACH",
        "DETACH",
        "PRAGMA",
    )

    def __init__(
        self,
        *,
        allowed_tables: list[str] | None = None,
        allowed_fields: list[str] | None = None,
        default_limit: int = 500,
    ) -> None:
        """初始化最小 SQL Guard。"""

        self.allowed_tables = set(allowed_tables or ["analytics_metrics_daily"])
        self.allowed_fields = set(allowed_fields or [])
        self.default_limit = default_limit

    def validate(
        self,
        sql: str,
        *,
        allowed_tables: list[str] | None = None,
        allowed_fields: list[str] | None = None,
        required_filter_column: str | None = None,
        required_filter_value: str | None = None,
    ) -> SQLGuardResult:
        """校验 SQL 并补齐最小安全约束。

        这里既保留全局默认白名单，也允许调用方按 data_source / table 动态覆盖：
        - `allowed_tables` 用于真正的表级治理；
        - `allowed_fields` 先做最小字段级白名单预留；
        - 这样 AnalyticsService 可以根据 Schema Registry 把治理规则显式传进来。
        """

        normalized_sql = sql.strip()
        if not normalized_sql:
            return SQLGuardResult(
                is_safe=False,
                checked_sql=None,
                blocked_reason="SQL 不能为空",
                governance_detail={"stage": "normalize"},
            )

        upper_sql = normalized_sql.upper()
        if not upper_sql.startswith("SELECT "):
            return SQLGuardResult(
                is_safe=False,
                checked_sql=None,
                blocked_reason="当前阶段只允许执行 SELECT 只读查询",
                governance_detail={"stage": "read_only_check"},
            )

        if ";" in normalized_sql.rstrip(";"):
            return SQLGuardResult(
                is_safe=False,
                checked_sql=None,
                blocked_reason="禁止执行多语句 SQL",
                governance_detail={"stage": "multi_statement_check"},
            )

        if "--" in normalized_sql or "/*" in normalized_sql or "*/" in normalized_sql:
            return SQLGuardResult(
                is_safe=False,
                checked_sql=None,
                blocked_reason="禁止注释型 SQL 输入",
                governance_detail={"stage": "comment_check"},
            )

        for keyword in self.DANGEROUS_KEYWORDS:
            if re.search(rf"\b{keyword}\b", upper_sql):
                return SQLGuardResult(
                    is_safe=False,
                    checked_sql=None,
                    blocked_reason=f"检测到危险关键字：{keyword}",
                    governance_detail={"stage": "dangerous_keyword_check", "keyword": keyword},
                )

        tables = self._extract_table_names(normalized_sql)
        if not tables:
            return SQLGuardResult(
                is_safe=False,
                checked_sql=None,
                blocked_reason="未识别到合法表名",
                governance_detail={"stage": "table_extract_check"},
            )

        effective_allowed_tables = set(allowed_tables or self.allowed_tables)
        disallowed_tables = [table for table in tables if table not in effective_allowed_tables]
        if disallowed_tables:
            return SQLGuardResult(
                is_safe=False,
                checked_sql=None,
                blocked_reason=f"存在未授权表：{', '.join(disallowed_tables)}",
                governance_detail={
                    "stage": "table_whitelist_check",
                    "disallowed_tables": disallowed_tables,
                },
            )

        effective_allowed_fields = set(allowed_fields or self.allowed_fields)
        if effective_allowed_fields:
            projected_fields = self._extract_selected_fields(normalized_sql)
            disallowed_fields = [
                field_name
                for field_name in projected_fields
                if field_name not in effective_allowed_fields and field_name != "*"
            ]
            if disallowed_fields:
                return SQLGuardResult(
                    is_safe=False,
                    checked_sql=None,
                    blocked_reason=f"存在未授权字段：{', '.join(disallowed_fields)}",
                    governance_detail={
                        "stage": "field_whitelist_check",
                        "disallowed_fields": disallowed_fields,
                    },
                )

        if required_filter_column and required_filter_value:
            expected_pattern = re.compile(
                rf"\b{re.escape(required_filter_column)}\b\s*=\s*'{re.escape(required_filter_value)}'",
                flags=re.IGNORECASE,
            )
            if not expected_pattern.search(normalized_sql):
                return SQLGuardResult(
                    is_safe=False,
                    checked_sql=None,
                    blocked_reason=f"缺少必需的数据范围过滤：{required_filter_column}",
                    governance_detail={
                        "stage": "data_scope_check",
                        "required_filter_column": required_filter_column,
                        "required_filter_value": required_filter_value,
                    },
                )

        checked_sql = normalized_sql
        if not re.search(r"\bLIMIT\s+\d+\b", upper_sql):
            checked_sql = f"{normalized_sql} LIMIT {self.default_limit}"

        return SQLGuardResult(
            is_safe=True,
            checked_sql=checked_sql,
            blocked_reason=None,
            governance_detail={
                "stage": "passed",
                "required_filter_column": required_filter_column,
                "required_filter_value": required_filter_value,
            },
        )

    def _extract_table_names(self, sql: str) -> list[str]:
        """提取最小表名集合。

        当前阶段只处理最小模板式 SELECT，
        因此优先解析 `FROM xxx` 和 `JOIN xxx`。
        """

        from_tables = re.findall(r"\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, flags=re.IGNORECASE)
        join_tables = re.findall(r"\bJOIN\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, flags=re.IGNORECASE)
        return from_tables + join_tables

    def _extract_selected_fields(self, sql: str) -> list[str]:
        """提取 SELECT 投影字段。

        当前阶段这里只做最小模板场景下的字段解析，
        目的不是覆盖所有复杂 SQL 语法，而是为“字段级白名单预留”提供一个稳定入口。
        当后续 SQL 模板变复杂时，可以把这里升级成 AST 解析器。
        """

        match = re.search(r"\bSELECT\s+(.*?)\s+\bFROM\b", sql, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return []

        raw_projection = match.group(1)
        projection_items = [item.strip() for item in raw_projection.split(",") if item.strip()]
        extracted_fields: list[str] = []
        for item in projection_items:
            alias_match = re.search(r"\bAS\s+([a-zA-Z_][a-zA-Z0-9_]*)$", item, flags=re.IGNORECASE)
            if alias_match:
                extracted_fields.append(alias_match.group(1))
                continue

            function_match = re.search(r"\(([^()]+)\)", item)
            if function_match:
                extracted_fields.append(function_match.group(1).split(".")[-1].strip())
                continue

            normalized_item = item.split(".")[-1].strip()
            extracted_fields.append(normalized_item)
        return extracted_fields
