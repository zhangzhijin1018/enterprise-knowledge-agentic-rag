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

    def validate(self, sql: str) -> SQLGuardResult:
        """校验 SQL 并补齐最小安全约束。"""

        normalized_sql = sql.strip()
        if not normalized_sql:
            return SQLGuardResult(
                is_safe=False,
                checked_sql=None,
                blocked_reason="SQL 不能为空",
            )

        upper_sql = normalized_sql.upper()
        if not upper_sql.startswith("SELECT "):
            return SQLGuardResult(
                is_safe=False,
                checked_sql=None,
                blocked_reason="当前阶段只允许执行 SELECT 只读查询",
            )

        if ";" in normalized_sql.rstrip(";"):
            return SQLGuardResult(
                is_safe=False,
                checked_sql=None,
                blocked_reason="禁止执行多语句 SQL",
            )

        if "--" in normalized_sql or "/*" in normalized_sql or "*/" in normalized_sql:
            return SQLGuardResult(
                is_safe=False,
                checked_sql=None,
                blocked_reason="禁止注释型 SQL 输入",
            )

        for keyword in self.DANGEROUS_KEYWORDS:
            if re.search(rf"\b{keyword}\b", upper_sql):
                return SQLGuardResult(
                    is_safe=False,
                    checked_sql=None,
                    blocked_reason=f"检测到危险关键字：{keyword}",
                )

        tables = self._extract_table_names(normalized_sql)
        if not tables:
            return SQLGuardResult(
                is_safe=False,
                checked_sql=None,
                blocked_reason="未识别到合法表名",
            )

        disallowed_tables = [table for table in tables if table not in self.allowed_tables]
        if disallowed_tables:
            return SQLGuardResult(
                is_safe=False,
                checked_sql=None,
                blocked_reason=f"存在未授权表：{', '.join(disallowed_tables)}",
            )

        checked_sql = normalized_sql
        if not re.search(r"\bLIMIT\s+\d+\b", upper_sql):
            checked_sql = f"{normalized_sql} LIMIT {self.default_limit}"

        return SQLGuardResult(
            is_safe=True,
            checked_sql=checked_sql,
            blocked_reason=None,
        )

    def _extract_table_names(self, sql: str) -> list[str]:
        """提取最小表名集合。

        当前阶段只处理最小模板式 SELECT，
        因此优先解析 `FROM xxx` 和 `JOIN xxx`。
        """

        from_tables = re.findall(r"\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, flags=re.IGNORECASE)
        join_tables = re.findall(r"\bJOIN\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, flags=re.IGNORECASE)
        return from_tables + join_tables
