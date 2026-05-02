"""经营分析子查询规划器（QueryPlanner）。

核心职责：
1. 接收 AnalyticsIntent（包含 required_queries）
2. 通过 MetricResolver 解析每个子查询的 data_source 和 table_name
3. 判断执行策略：SINGLE / PARALLEL / JOIN
4. 生成 ExecutionPlan

执行策略：
- SINGLE：单个查询，直接执行
- PARALLEL：同一数据源 + 同表 + 不同时间 → 并行查询 → 应用层合并
- JOIN：同一数据源 + 多表 → SQL JOIN

注意：不同数据源的查询也可以并行（跨连接池），最终应用层合并
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from core.analytics.intent.schema import (
    AnalyticsIntent,
    ComplexityType,
    ExecutionPhase,
    ExecutionPlan,
    ExecutionStrategy,
    PeriodRole,
    RequiredQuery,
)
from core.analytics.metric_resolver import MetricMetadata, MetricResolver


@dataclass
class PlanningContext:
    """规划上下文。

    包含规划所需的所有信息。
    """

    intent: AnalyticsIntent
    metric_resolver: MetricResolver
    max_parallel_queries: int = 5  # 同一数据源最大并行数


class QueryPlanner:
    """子查询规划器。

    将 AnalyticsIntent 中的 required_queries 转换为可执行的 ExecutionPlan。

    执行策略判断逻辑：
    1. 如果只有一个查询 → SINGLE
    2. 如果多个查询同数据源 + 同表：
       - 不同时间周期 → PARALLEL（并行查询）
       - 有关联需求 → JOIN（SQL JOIN）
    3. 如果多个查询不同数据源 → PARALLEL（并行查询）

    使用示例：
        planner = QueryPlanner(metric_resolver)

        # 复杂归因分析
        intent = AnalyticsIntent(
            complexity=ComplexityType.COMPLEX,
            required_queries=[
                RequiredQuery(query_id="q1", period_role=PeriodRole.CURRENT, ...),
                RequiredQuery(query_id="q2", period_role=PeriodRole.YOY_BASELINE, ...),
            ]
        )
        plan = planner.plan(intent)
        # plan.phases[0].strategy == ExecutionStrategy.PARALLEL
    """

    def __init__(self, metric_resolver: MetricResolver) -> None:
        self.metric_resolver = metric_resolver

    def plan(self, intent: AnalyticsIntent) -> ExecutionPlan:
        """根据意图生成执行计划。

        Args:
            intent: 解析后的意图对象

        Returns:
            ExecutionPlan: 执行计划
        """

        if intent.complexity == ComplexityType.SIMPLE:
            return self._plan_simple(intent)
        else:
            return self._plan_complex(intent)

    def _plan_simple(self, intent: AnalyticsIntent) -> ExecutionPlan:
        """为简单查询生成执行计划。"""

        if intent.metric is None or intent.metric.metric_code is None:
            return ExecutionPlan(phases=[], need_merge=False, total_queries=0)

        # 解析指标对应的数据源
        try:
            metadata = self.metric_resolver.resolve(intent.metric.metric_code)
        except ValueError:
            return ExecutionPlan(phases=[], need_merge=False, total_queries=0)

        # 简单查询只有一个子查询
        phase = ExecutionPhase(
            phase_id="phase_0",
            data_source_key=metadata.data_source_key,
            queries=["q_simple"],
            strategy=ExecutionStrategy.SINGLE,
            dependencies=[],
        )

        return ExecutionPlan(
            phases=[phase],
            need_merge=False,
            total_queries=1,
        )

    def _plan_complex(self, intent: AnalyticsIntent) -> ExecutionPlan:
        """为复杂查询生成执行计划。

        核心逻辑：
        1. 解析每个子查询的 data_source 和 table_name
        2. 按数据源分组
        3. 同数据源内判断：PARALLEL 还是 JOIN
        4. 不同数据源：PARALLEL（可跨数据源并行）
        """

        if not intent.required_queries:
            return ExecutionPlan(phases=[], need_merge=False, total_queries=0)

        # Step 1: 解析每个子查询的元数据
        query_metadata = self._resolve_query_metadata(intent.required_queries)

        # Step 2: 按数据源分组
        grouped = self._group_by_data_source(intent.required_queries, query_metadata)

        # Step 3: 为每个数据源生成执行阶段
        phases = []
        phase_index = 0

        for ds_key, queries in grouped.items():
            # 判断这个数据源内的执行策略
            strategy = self._determine_strategy(queries, query_metadata)

            if strategy == ExecutionStrategy.JOIN:
                # JOIN 策略：生成一条 JOIN SQL
                join_sql = self._build_join_sql(queries, query_metadata, ds_key)
                phase = ExecutionPhase(
                    phase_id=f"phase_{phase_index}",
                    data_source_key=ds_key,
                    queries=[q.query_id for q in queries],
                    strategy=strategy,
                    join_sql=join_sql,
                    dependencies=[],
                )
            else:
                # SINGLE 或 PARALLEL 策略
                phase = ExecutionPhase(
                    phase_id=f"phase_{phase_index}",
                    data_source_key=ds_key,
                    queries=[q.query_id for q in queries],
                    strategy=strategy,
                    dependencies=[],
                )

            phases.append(phase)
            phase_index += 1

        # Step 4: 确定是否需要合并
        need_merge = len(grouped) > 1

        # Step 5: 确定阶段间依赖（不同数据源可以并行）
        phases = self._resolve_dependencies(phases, query_metadata)

        return ExecutionPlan(
            phases=phases,
            need_merge=need_merge,
            total_queries=len(intent.required_queries),
        )

    def _resolve_query_metadata(
        self,
        queries: list[RequiredQuery],
    ) -> dict[str, dict]:
        """解析每个子查询的元数据。

        Returns:
            dict[query_id, {data_source_key, table_name, metric_code, ...}]
        """

        result = {}
        for query in queries:
            metadata = {
                "data_source_key": None,
                "table_name": None,
                "metric_code": query.metric_code,
                "period_role": query.period_role,
                "group_by": query.group_by,
            }

            if query.metric_code:
                try:
                    metric_meta = self.metric_resolver.resolve(query.metric_code)
                    metadata["data_source_key"] = metric_meta.data_source_key
                    metadata["table_name"] = metric_meta.table_name
                except ValueError:
                    pass

            result[query.query_id] = metadata

        return result

    def _group_by_data_source(
        self,
        queries: list[RequiredQuery],
        query_metadata: dict[str, dict],
    ) -> dict[str, list[RequiredQuery]]:
        """按数据源分组子查询。"""

        grouped: dict[str, list[RequiredQuery]] = {}

        for query in queries:
            meta = query_metadata.get(query.query_id, {})
            ds_key = meta.get("data_source_key") or "unknown"

            if ds_key not in grouped:
                grouped[ds_key] = []
            grouped[ds_key].append(query)

        return grouped

    def _determine_strategy(
        self,
        queries: list[RequiredQuery],
        query_metadata: dict[str, dict],
    ) -> ExecutionStrategy:
        """判断执行策略。

        判断逻辑：
        1. 单个查询 → SINGLE
        2. 多个查询：
           - 如果有关联需求（join_with）→ JOIN
           - 如果查询不同表 → JOIN
           - 如果查询同一表但不同时间 → PARALLEL
        """

        if len(queries) == 1:
            return ExecutionStrategy.SINGLE

        # 获取所有表名
        table_names = set()
        for query in queries:
            meta = query_metadata.get(query.query_id, {})
            table_name = meta.get("table_name")
            if table_name:
                table_names.add(table_name)

        # 如果查询多张表，使用 JOIN
        if len(table_names) > 1:
            return ExecutionStrategy.JOIN

        # 如果只有一个表，检查是否有 join_with 标记
        for query in queries:
            if query.join_with:
                return ExecutionStrategy.JOIN

        # 同一表 + 不同时间周期 → PARALLEL
        return ExecutionStrategy.PARALLEL

    def _build_join_sql(
        self,
        queries: list[RequiredQuery],
        query_metadata: dict[str, dict],
        data_source_key: str,
    ) -> str:
        """构建 JOIN SQL。

        简化版本：实际需要根据表结构和关联条件构建完整 SQL。
        这里只返回占位符。
        """

        # TODO: 根据实际表结构和关联条件构建 JOIN SQL
        # 需要考虑：
        # 1. 关联字段（如 biz_date, region_name）
        # 2. JOIN 类型（INNER/LEFT/RIGHT）
        # 3. SELECT 字段
        # 4. WHERE 条件

        return f"-- TODO: Build JOIN SQL for {len(queries)} queries on {data_source_key}"

    def _resolve_dependencies(
        self,
        phases: list[ExecutionPhase],
        query_metadata: dict[str, dict],
    ) -> list[ExecutionPhase]:
        """解析阶段间依赖关系。

        当前策略：不同数据源可以并行，无依赖
        未来可能需要：根据数据依赖添加依赖关系
        """

        # 当前：所有阶段无依赖，可以并行执行
        return phases

    def validate_plan(self, plan: ExecutionPlan) -> tuple[bool, str]:
        """验证执行计划的有效性。"""

        if not plan.phases:
            return True, ""

        # 检查查询 ID 是否唯一
        all_query_ids = set()
        for phase in plan.phases:
            for query_id in phase.queries:
                if query_id in all_query_ids:
                    return False, f"重复的查询 ID: {query_id}"
                all_query_ids.add(query_id)

        # 检查阶段依赖是否有效
        phase_ids = {p.phase_id for p in plan.phases}
        for phase in plan.phases:
            for dep_id in phase.dependencies:
                if dep_id not in phase_ids:
                    return False, f"无效的依赖阶段: {dep_id}"

        return True, ""

    def explain_plan(self, plan: ExecutionPlan) -> str:
        """生成执行计划的自然语言解释。"""

        if not plan.phases:
            return "无需执行查询"

        lines = [f"执行计划（共 {plan.total_queries} 个查询，分为 {len(plan.phases)} 个阶段）：\n"]

        for i, phase in enumerate(plan.phases):
            strategy_desc = {
                ExecutionStrategy.SINGLE: "单个查询",
                ExecutionStrategy.PARALLEL: "并行查询",
                ExecutionStrategy.JOIN: "SQL JOIN",
            }.get(phase.strategy, "未知")

            dep_str = f"，依赖阶段 {phase.dependencies}" if phase.dependencies else "（无依赖，可并行）"

            lines.append(f"阶段 {i + 1}：{phase.data_source_key} - {strategy_desc}{dep_str}")
            lines.append(f"  - 查询数：{len(phase.queries)}")

            if phase.strategy == ExecutionStrategy.JOIN:
                lines.append(f"  - JOIN SQL：{phase.join_sql}")

        if plan.need_merge:
            lines.append("\n注意：需要应用层合并不同数据源的结果")

        return "\n".join(lines)


# =============================================================================
# 便捷函数
# =============================================================================


def create_required_query(
    query_name: str,
    purpose: str,
    metric_code: str | None = None,
    metric_name: str | None = None,
    period_role: PeriodRole = PeriodRole.CURRENT,
    group_by: str | None = None,
    filters: dict | None = None,
    join_with: str | None = None,
    join_type: str | None = None,
) -> RequiredQuery:
    """创建子查询的便捷函数。"""

    return RequiredQuery(
        query_id=f"q_{uuid.uuid4().hex[:8]}",
        query_name=query_name,
        purpose=purpose,
        metric_code=metric_code,
        metric_name=metric_name,
        period_role=period_role,
        group_by=group_by,
        filters=filters or {},
        join_with=join_with,
        join_type=join_type,
    )
