"""
经营分析 SQL 安全检查器（最后一道硬安全边界）。

=================================================================
为什么必须先有 SQL Guard
=================================================================
1. 经营分析最终会落到真实业务数据库，不能让自由 SQL 直接执行；
2. 即使当前阶段还是规则模板，也要把"生成 SQL"和"检查 SQL"显式拆开；
3. 后续一旦引入 LLM 辅助 SQL 生成，SQL Guard 会成为最后一道硬安全边界：
   LLM 可能产生幻觉、可能被 prompt injection 诱导，但 SQL Guard 是确定性规则，
   不受 LLM 影响。

=================================================================
当前阶段提供的能力（9 层校验，按执行顺序排列）
=================================================================
1. 空 SQL 检查           → SQL 不能为空字符串
2. 只读检查              → SQL 必须以 SELECT 开头，拒绝 DDL/DML
3. 多语句检查            → 禁止分号分隔的多条 SQL（防止 SQL 注入中的堆叠查询攻击）
4. 注释检查              → 禁止 -- 行注释和 /* */ 块注释（防止注释注入绕过后续检查）
5. 危险关键字检查         → 禁止 INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/CREATE/GRANT/REVOKE/MERGE 等
6. 表名提取与白名单检查   → 只允许操作白名单中的表（默认 analytics_metrics_daily）
7. 字段白名单检查（预留） → 当 allowed_fields 非空时，限制 SELECT 投影字段
8. 数据范围过滤检查        → 如果表要求部门过滤，必须包含 department_code = 'xxx' 条件
9. 自动补 LIMIT           → 没有 LIMIT 时自动追加 LIMIT 500，防止全表扫

=================================================================
重试策略（重要）
=================================================================
- SQL Guard blocked → 不可重试（治理规则层面的硬拒绝，重试不会改变结果）
- SQL Gateway timeout → 可重试一次（网络/负载的临时故障，重试可能成功）
- 权限校验失败 → 不可重试（权限不足不是临时问题）

=================================================================
安全模型说明
=================================================================
SQL Guard 不依赖 AST 解析（避免复杂度和解析器漏洞），而是采用正则匹配 + 关键字黑名单。
这是一种"宁可误杀，不可漏放"的防御性策略：
- 优点：简单、可审计、规则明确、不受 LLM 影响
- 缺点：可能对复杂但安全的 SQL 误判（当前阶段可接受，因为 SQL 是模板生成的）
- 后续：当 SQL 模板变复杂时，可引入 SQL AST 解析器（如 sqlparse）增强精度
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class SQLGuardResult:
    """
    SQL 安全检查结果（不可变数据类）。

    字段说明：
    - is_safe：SQL 是否通过全部安全检查（为 True 时 checked_sql 才有有效值）
    - checked_sql：经过安全检查并补全 LIMIT 后的可执行 SQL（is_safe=False 时为 None）
    - blocked_reason：被阻断的具体原因（is_safe=True 时为 None），用于前端展示和审计
    - governance_detail：治理详情，包含校验失败的阶段（stage）和相关上下文信息

    使用 slots=True 减少内存占用（本类在每次 SQL 校验时都创建实例）。
    """

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
                    governance_detail={
                        "stage": "dangerous_keyword_check",
                        "keyword": keyword,
                    },
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
        disallowed_tables = [
            table for table in tables if table not in effective_allowed_tables
        ]
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

        from_tables = re.findall(
            r"\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, flags=re.IGNORECASE
        )
        join_tables = re.findall(
            r"\bJOIN\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, flags=re.IGNORECASE
        )
        return from_tables + join_tables

    def _extract_selected_fields(self, sql: str) -> list[str]:
        """提取 SELECT 投影字段。

        当前阶段这里只做最小模板场景下的字段解析，
        目的不是覆盖所有复杂 SQL 语法，而是为“字段级白名单预留”提供一个稳定入口。
        当后续 SQL 模板变复杂时，可以把这里升级成 AST 解析器。
        """

        match = re.search(
            r"\bSELECT\s+(.*?)\s+\bFROM\b", sql, flags=re.IGNORECASE | re.DOTALL
        )
        if not match:
            return []

        raw_projection = match.group(1)
        projection_items = [
            item.strip() for item in raw_projection.split(",") if item.strip()
        ]
        extracted_fields: list[str] = []
        for item in projection_items:
            alias_match = re.search(
                r"\bAS\s+([a-zA-Z_][a-zA-Z0-9_]*)$", item, flags=re.IGNORECASE
            )
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
