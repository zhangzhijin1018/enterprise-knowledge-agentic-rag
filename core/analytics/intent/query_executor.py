"""经营分析查询执行器（QueryExecutor）。

核心职责：
1. 根据 ExecutionPlan 执行子查询
2. 支持 SINGLE / PARALLEL / JOIN 三种执行策略
3. 所有阶段和查询都可以并行执行（不同数据源、不同连接池）
4. 返回结构化查询结果

执行策略：
- SINGLE：单个查询，直接执行
- PARALLEL：同一数据源 + 同表 + 不同时间 → 并行查询
- JOIN：同一数据源 + 多表 → SQL JOIN

注意：不同数据源的查询可以并行（跨连接池），最终应用层合并
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from core.analytics.intent.query_planner import ExecutionPlan, ExecutionPhase, ExecutionStrategy
from core.analytics.schema_registry import SchemaRegistry
from core.tools.sql.sql_gateway import SQLGateway


@dataclass
class QueryResult:
    """单个查询的执行结果。"""

    query_id: str
    success: bool
    sql: str | None = None
    data: list[dict] | None = None
    error: str | None = None
    row_count: int = 0
    execution_time_ms: float = 0.0


@dataclass
class ExecutionResult:
    """完整执行结果。"""

    plan: ExecutionPlan
    results: dict[str, QueryResult] = field(default_factory=dict)
    merged_data: list[dict] | None = None
    success: bool = True
    total_time_ms: float = 0.0
    errors: list[str] = field(default_factory=list)

    def get_result(self, query_id: str) -> QueryResult | None:
        """根据 query_id 获取查询结果。"""
        return self.results.get(query_id)

    def get_results_by_phase(self, phase_id: str) -> list[QueryResult]:
        """获取指定阶段的所有查询结果。"""
        phase = next((p for p in self.plan.phases if p.phase_id == phase_id), None)
        if phase is None:
            return []
        return [self.results[qid] for qid in phase.queries if qid in self.results]


class QueryExecutor:
    """查询执行器。

    根据 ExecutionPlan 执行 SQL 查询。

    执行策略：
    1. SINGLE：单个查询，直接执行
    2. PARALLEL：多个查询并行执行（asyncio.gather）
    3. JOIN：执行一条 JOIN SQL

    所有阶段都可以并行执行，因为：
    - 不同数据源使用不同的连接池
    - asyncio 可以处理阻塞 I/O
    - 并行执行显著提升性能

    使用示例：
        executor = QueryExecutor(sql_gateway, schema_registry)

        plan = ExecutionPlan(phases=[...])
        result = await executor.execute(plan)

        # 获取结果
        for query_id, query_result in result.results.items():
            print(f"{query_id}: {query_result.data}")
    """

    def __init__(
        self,
        sql_gateway: SQLGateway,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.sql_gateway = sql_gateway
        self.schema_registry = schema_registry or get_schema_registry()

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        """执行查询计划。

        执行策略：
        1. 收集所有阶段的查询任务
        2. 所有阶段并行执行（不同数据源、不同连接池）
        3. 阶段内根据策略执行（SINGLE/PARALLEL/JOIN）

        Args:
            plan: 执行计划

        Returns:
            ExecutionResult: 执行结果
        """

        import time

        t0 = time.monotonic()
        result = ExecutionResult(plan=plan)

        # 准备所有阶段的任务
        phase_tasks = []
        for phase in plan.phases:
            phase_tasks.append(self._execute_phase(phase))

        # 所有阶段并行执行！
        phase_results = await asyncio.gather(*phase_tasks, return_exceptions=True)

        # 收集结果
        for i, phase_result in enumerate(phase_results):
            phase = plan.phases[i]

            if isinstance(phase_result, Exception):
                # 阶段执行出错
                for query_id in phase.queries:
                    result.results[query_id] = QueryResult(
                        query_id=query_id,
                        success=False,
                        error=str(phase_result),
                    )
                result.errors.append(f"阶段 {phase.phase_id} 执行失败: {phase_result}")
            else:
                # 阶段执行成功
                result.results.update(phase_result)

        # 检查是否有严重错误
        failed_results = [r for r in result.results.values() if not r.success]
        if failed_results:
            result.errors.extend([f"{r.query_id}: {r.error}" for r in failed_results if r.error])
            # 如果所有查询都失败，标记为失败
            if len(failed_results) == plan.total_queries:
                result.success = False

        result.total_time_ms = round((time.monotonic() - t0) * 1000, 2)

        return result

    async def _execute_phase(self, phase: ExecutionPhase) -> dict[str, QueryResult]:
        """执行单个阶段。

        Args:
            phase: 执行阶段

        Returns:
            dict[query_id, QueryResult]
        """

        if phase.strategy == ExecutionStrategy.SINGLE:
            return await self._execute_single(phase)

        elif phase.strategy == ExecutionStrategy.PARALLEL:
            return await self._execute_parallel(phase)

        elif phase.strategy == ExecutionStrategy.JOIN:
            return await self._execute_join(phase)

        else:
            raise ValueError(f"未知的执行策略: {phase.strategy}")

    async def _execute_single(self, phase: ExecutionPhase) -> dict[str, QueryResult]:
        """执行单个查询。"""

        if not phase.queries:
            return {}

        query_id = phase.queries[0]
        result = await self._execute_single_query(query_id, phase.data_source_key)

        return {query_id: result}

    async def _execute_parallel(self, phase: ExecutionPhase) -> dict[str, QueryResult]:
        """并行执行多个查询。

        同一数据源的多个查询可以并行执行，因为：
        1. 使用 asyncio.gather 异步并发
        2. 底层连接池管理并发连接数
        3. 显著提升查询性能
        """

        if not phase.queries:
            return {}

        # 创建所有查询任务
        tasks = []
        for query_id in phase.queries:
            task = self._execute_single_query(query_id, phase.data_source_key)
            tasks.append(task)

        # 并行执行！
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理结果
        query_results = {}
        for query_id, res in zip(phase.queries, results):
            if isinstance(res, Exception):
                query_results[query_id] = QueryResult(
                    query_id=query_id,
                    success=False,
                    error=str(res),
                )
            else:
                query_results[query_id] = res

        return query_results

    async def _execute_join(self, phase: ExecutionPhase) -> dict[str, QueryResult]:
        """执行 JOIN 查询。

        当多个查询需要关联时（如多表 join），执行一条 JOIN SQL。
        """

        if not phase.queries:
            return {}

        # 执行 JOIN SQL
        if phase.join_sql:
            result = await self._execute_sql(phase.join_sql, phase.data_source_key)
            return {phase.queries[0]: result}
        else:
            return {phase.queries[0]: QueryResult(
                query_id=phase.queries[0],
                success=False,
                error="JOIN SQL 未指定",
            )}

    async def _execute_single_query(
        self,
        query_id: str,
        data_source_key: str,
    ) -> QueryResult:
        """执行单个查询。"""

        import time

        t0 = time.monotonic()

        try:
            # 构建 SQL（根据 query_id 查找对应的 SQL 构建参数）
            sql = self._build_sql_for_query(query_id, data_source_key)

            # 执行 SQL
            data = await self.sql_gateway.execute(sql)

            execution_time = round((time.monotonic() - t0) * 1000, 2)

            return QueryResult(
                query_id=query_id,
                success=True,
                sql=sql,
                data=data,
                row_count=len(data) if data else 0,
                execution_time_ms=execution_time,
            )

        except Exception as exc:
            execution_time = round((time.monotonic() - t0) * 1000, 2)
            return QueryResult(
                query_id=query_id,
                success=False,
                error=str(exc),
                execution_time_ms=execution_time,
            )

    async def _execute_sql(
        self,
        sql: str,
        data_source_key: str,
    ) -> QueryResult:
        """执行 SQL。"""

        import time

        t0 = time.monotonic()

        try:
            # 通过 SQL Gateway 执行
            data = await self.sql_gateway.execute(sql)

            execution_time = round((time.monotonic() - t0) * 1000, 2)

            return QueryResult(
                query_id="join_query",
                success=True,
                sql=sql,
                data=data,
                row_count=len(data) if data else 0,
                execution_time_ms=execution_time,
            )

        except Exception as exc:
            execution_time = round((time.monotonic() - t0) * 1000, 2)
            return QueryResult(
                query_id="join_query",
                success=False,
                error=str(exc),
                execution_time_ms=execution_time,
            )

    def _build_sql_for_query(
        self,
        query_id: str,
        data_source_key: str,
    ) -> str:
        """根据 query_id 构建 SQL。

        注意：这里需要根据 AnalyticsIntent 中携带的子查询信息构建 SQL。
        实际实现中，这部分逻辑应该由 SQL Builder 调用此执行器。

        当前实现为占位符。
        """

        # TODO: 实现真正的 SQL 构建逻辑
        return f"-- TODO: Build SQL for query {query_id} on {data_source_key}"

    def merge_results(
        self,
        results: dict[str, QueryResult],
        merge_strategy: str = "union",
    ) -> list[dict]:
        """合并多个查询结果。

        Args:
            results: 查询结果字典
            merge_strategy: 合并策略
                - "union": 结果合并
                - "join": 结果关联（需要共同字段）
                - "append": 结果追加

        Returns:
            合并后的结果
        """

        successful_results = [
            r for r in results.values() if r.success and r.data
        ]

        if not successful_results:
            return []

        if merge_strategy == "union":
            merged = []
            for res in successful_results:
                merged.extend(res.data or [])
            return merged

        elif merge_strategy == "append":
            merged = []
            for res in successful_results:
                if res.data:
                    merged.extend(res.data)
            return merged

        elif merge_strategy == "join":
            # 简化实现：取第一个结果
            return successful_results[0].data or []

        return []


# =============================================================================
# 便捷函数
# =============================================================================


async def execute_plan(
    plan: ExecutionPlan,
    sql_gateway: SQLGateway,
    schema_registry: SchemaRegistry | None = None,
) -> ExecutionResult:
    """便捷函数：执行查询计划。"""

    executor = QueryExecutor(sql_gateway, schema_registry)
    return await executor.execute(plan)
