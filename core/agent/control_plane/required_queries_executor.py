"""复杂分析 required_queries 执行器。

当 AnalyticsIntent 的 planning_mode 为 DECOMPOSED 时，
需要执行多个子查询（required_queries），并将结果组合。

执行流程：
1. 解析 required_queries，识别主查询和基准查询
2. 并发或顺序执行子查询
3. 组合结果，生成同比/环比分析
4. 返回组合后的结果集
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.analytics.intent.schema import AnalyticsIntent, RequiredQueryIntent, PeriodRole
from core.agent.control_plane.intent_sql_builder import AnalyticsIntentSQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
from core.tools.sql.sql_gateway import SQLGateway


@dataclass
class QueryExecutionResult:
    """单个查询执行结果。"""

    query_name: str
    period_role: str
    rows: list[dict]
    columns: list[str]
    row_count: int
    latency_ms: int
    success: bool = True
    error: str | None = None


@dataclass
class CombinedExecutionResult:
    """组合后的执行结果。"""

    # 主查询结果
    main_result: QueryExecutionResult | None = None
    # 基准查询结果（同比/环比）
    baseline_results: list[QueryExecutionResult] = field(default_factory=list)
    # 组合后的数据
    combined_rows: list[dict] = field(default_factory=list)
    # 执行摘要
    summary: dict = field(default_factory=dict)
    # 所有执行是否成功
    all_success: bool = True


class RequiredQueriesExecutor:
    """required_queries 执行器。

    负责执行 decomposed 模式下的多个子查询，
    并将结果组合成完整的分析结果。
    """

    def __init__(
        self,
        sql_builder: AnalyticsIntentSQLBuilder,
        sql_guard: SQLGuard,
        sql_gateway: SQLGateway,
    ) -> None:
        self.sql_builder = sql_builder
        self.sql_guard = sql_guard
        self.sql_gateway = sql_gateway

    def execute(
        self,
        intent: AnalyticsIntent,
        department_code: str | None = None,
    ) -> CombinedExecutionResult:
        """执行 required_queries 并组合结果。

        Args:
            intent: 经过校验的 AnalyticsIntent
            department_code: 部门代码

        Returns:
            组合后的执行结果
        """

        result = CombinedExecutionResult()

        # 构建复杂 SQL
        sql_bundle = self.sql_builder.build(intent, department_code=department_code)

        # 获取子查询列表
        sub_queries = sql_bundle.get("sub_queries", [])
        if not sub_queries:
            # 退化为简单查询
            return self._execute_simple(intent, sql_bundle, department_code)

        # 顺序执行每个子查询
        execution_results: list[QueryExecutionResult] = []
        for i, sub_query in enumerate(sub_queries):
            req_query = intent.required_queries[i] if i < len(intent.required_queries) else None
            query_name = req_query.query_name if req_query else f"query_{i}"
            period_role = (
                req_query.period_role.value
                if req_query and hasattr(req_query.period_role, "value")
                else str(req_query.period_role) if req_query else "unknown"
            )

            try:
                execution_result = self._execute_single_query(
                    sql=sub_query["generated_sql"],
                    query_name=query_name,
                    period_role=period_role,
                    department_code=department_code,
                )
            except Exception as exc:
                execution_result = QueryExecutionResult(
                    query_name=query_name,
                    period_role=period_role,
                    rows=[],
                    columns=[],
                    row_count=0,
                    latency_ms=0,
                    success=False,
                    error=str(exc),
                )

            execution_results.append(execution_result)
            if not execution_result.success:
                result.all_success = False

        # 分类结果
        for exec_res in execution_results:
            if exec_res.period_role in ("main", "current"):
                result.main_result = exec_res
            else:
                result.baseline_results.append(exec_res)

        # 组合结果
        if result.main_result and result.main_result.success:
            result.combined_rows = self._combine_results(
                main=result.main_result,
                baselines=result.baseline_results,
            )
            result.summary = self._build_summary(result)

        return result

    def _execute_simple(
        self,
        intent: AnalyticsIntent,
        sql_bundle: dict,
        department_code: str | None,
    ) -> CombinedExecutionResult:
        """退化为简单查询执行。"""

        result = CombinedExecutionResult()

        try:
            exec_result = self._execute_single_query(
                sql=sql_bundle["generated_sql"],
                query_name="main",
                period_role="current",
                department_code=department_code,
            )
            result.main_result = exec_result
            result.combined_rows = exec_result.rows
            result.all_success = exec_result.success
            result.summary = {
                "total_rows": exec_result.row_count,
                "execution_time_ms": exec_result.latency_ms,
            }
        except Exception as exc:
            result.all_success = False
            result.summary = {"error": str(exc)}

        return result

    def _execute_single_query(
        self,
        sql: str,
        query_name: str,
        period_role: str,
        department_code: str | None,
    ) -> QueryExecutionResult:
        """执行单个查询。"""

        import time

        # SQL 安全校验
        guard_result = self.sql_guard.validate(sql, risk_level="medium")
        if not guard_result.is_safe:
            raise PermissionError(f"SQL 未通过安全校验：{guard_result.blocked_reason}")

        # 记录开始时间
        start_time = time.time()

        # 执行查询
        execution_result = self.sql_gateway.execute_readonly_query(sql)

        # 计算延迟
        latency_ms = int((time.time() - start_time) * 1000)

        # 转换结果
        rows = []
        if hasattr(execution_result, "rows"):
            rows = list(execution_result.rows)
        elif isinstance(execution_result, dict):
            rows = execution_result.get("rows", [])
        elif isinstance(execution_result, list):
            rows = execution_result

        columns = []
        if hasattr(execution_result, "columns"):
            columns = list(execution_result.columns)
        elif rows and isinstance(rows[0], dict):
            columns = list(rows[0].keys())

        return QueryExecutionResult(
            query_name=query_name,
            period_role=period_role,
            rows=rows,
            columns=columns,
            row_count=len(rows),
            latency_ms=latency_ms,
            success=True,
        )

    def _combine_results(
        self,
        main: QueryExecutionResult,
        baselines: list[QueryExecutionResult],
    ) -> list[dict]:
        """组合主查询和基准查询结果。"""

        if not baselines:
            return main.rows

        combined_rows = []

        # 按维度键分组
        main_indexed: dict[str, dict] = {}
        for row in main.rows:
            key = self._extract_key(row, main.columns)
            main_indexed[key] = row

        # 遍历基准查询
        for baseline in baselines:
            baseline_indexed: dict[str, dict] = {}
            for row in baseline.rows:
                key = self._extract_key(row, baseline.columns)
                baseline_indexed[key] = row

            # 合并
            for key, main_row in main_indexed.items():
                combined_row = dict(main_row)
                baseline_row = baseline_indexed.get(key, {})

                # 计算同比/环比
                main_value = combined_row.get("total_value") or combined_row.get("value") or 0
                baseline_value = baseline_row.get("total_value") or baseline_row.get("value") or 0

                if baseline_value and baseline_value != 0:
                    combined_row["change_ratio"] = (main_value - baseline_value) / baseline_value
                else:
                    combined_row["change_ratio"] = None
                # change_value 始终计算（即使 baseline 为 0）
                combined_row["change_value"] = main_value - baseline_value

                combined_row["baseline_value"] = baseline_value
                combined_row["comparison_type"] = baseline.period_role

                combined_rows.append(combined_row)

        return combined_rows

    def _extract_key(self, row: dict, columns: list[str]) -> str:
        """提取分组键。"""

        # 优先使用 region/station/month 作为键
        for key in ["region", "station", "month", "dimension"]:
            if key in row and row[key] is not None:
                return str(row[key])

        # 否则使用所有维度字段组合
        parts = []
        for col in columns:
            if col not in ["total_value", "value", "count"]:
                parts.append(str(row.get(col, "")))
        return "|".join(parts)

    def _build_summary(self, result: CombinedExecutionResult) -> dict:
        """构建执行摘要。"""

        summary = {
            "total_queries": len(result.baseline_results) + (1 if result.main_result else 0),
            "successful_queries": sum(
                1 for r in result.baseline_results if r.success
            ) + (1 if result.main_result and result.main_result.success else 0),
            "main_query": {
                "rows": result.main_result.row_count if result.main_result else 0,
                "latency_ms": result.main_result.latency_ms if result.main_result else 0,
            },
        }

        if result.baseline_results:
            summary["baseline_queries"] = [
                {
                    "name": r.query_name,
                    "period_role": r.period_role,
                    "rows": r.row_count,
                    "latency_ms": r.latency_ms,
                }
                for r in result.baseline_results
            ]

        return summary
