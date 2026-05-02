"""基于 AnalyticsIntent 的 SQL 构造器。

本构造器直接接收经过 Validator 校验后的 AnalyticsIntent，
不依赖旧的 slots 格式，是新版经营分析链路的推荐 SQL Builder。

设计原则：
- 只接收 sanitized AnalyticsIntent
- 所有 SQL 字段、表、group_by 都必须来自 intent 和 schema registry
- 不允许自己猜 metric
- 支持 decomposed 模式的多个子查询

与旧版 SQLBuilder 的区别：
- 旧版 SQLBuilder 接收 dict 格式的 slots
- 新版 AnalyticsIntentSQLBuilder 接收 Pydantic 格式的 AnalyticsIntent
"""

from __future__ import annotations

import calendar
from datetime import datetime

from core.analytics.intent.schema import (
    AnalyticsIntent,
    CompareTarget,
    RequiredQueryIntent,
)
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry


class AnalyticsIntentSQLBuilder:
    """基于 AnalyticsIntent 的 Schema-aware SQL 构造器。

    直接接收经过 Validator 校验后的 AnalyticsIntent，生成结构化 SQL。

    特点：
    1. 输入是 Pydantic 模型，不是 dict
    2. 支持 simple 和 complex 两种模式
    3. simple 模式：生成单个 SQL
    4. complex 模式：生成多个子查询（required_queries）
    """

    def __init__(
        self,
        *,
        schema_registry: SchemaRegistry | None = None,
        metric_catalog: MetricCatalog | None = None,
    ) -> None:
        self.schema_registry = schema_registry or SchemaRegistry()
        self.metric_catalog = metric_catalog or MetricCatalog()

    def build(
        self,
        intent: AnalyticsIntent,
        *,
        department_code: str | None = None,
    ) -> dict:
        """根据 AnalyticsIntent 构造 SQL。

        Args:
            intent: 经过 Validator 校验后的 AnalyticsIntent
            department_code: 部门代码（用于数据范围过滤）

        Returns:
            包含 generated_sql 和元信息的 dict
        """

        from core.analytics.intent.schema import PlanningMode

        # 判断执行模式
        if intent.planning_mode == PlanningMode.DECOMPOSED:
            return self._build_complex_sql(intent, department_code=department_code)
        else:
            return self._build_simple_sql(intent, department_code=department_code)

    def _build_simple_sql(
        self,
        intent: AnalyticsIntent,
        *,
        department_code: str | None = None,
    ) -> dict:
        """构造简单查询 SQL（direct 模式）。"""

        # 解析指标定义
        metric_code = intent.metric.metric_code if intent.metric else None
        metric_name = intent.metric.metric_name if intent.metric else intent.metric.raw_text if intent.metric else None

        if not metric_code and not metric_name:
            raise ValueError("AnalyticsIntent 中缺少有效的 metric 信息")

        metric_definition = None

        # 优先通过 metric_name 查找
        if metric_name:
            metric_definition = self.metric_catalog.resolve_metric(metric_name)

        # 如果找不到，通过 metric_code 遍历查找
        if metric_definition is None and metric_code:
            for m in self.metric_catalog._metrics.values():
                if m.metric_code == metric_code:
                    metric_definition = m
                    break

        # 如果还是找不到，尝试用 metric_code 作为名称查找
        if metric_definition is None and metric_code:
            metric_definition = self.metric_catalog.resolve_metric(metric_code)

        if metric_definition is None:
            raise ValueError(f"无法解析指标：{metric_code} 或 {metric_name}")

        # 获取表定义
        data_source = metric_definition.data_source
        table_definition = self.schema_registry.get_table_definition(
            table_name=metric_definition.table_name,
            data_source=data_source,
        )

        # 解析时间范围
        time_range_dict = self._parse_time_range(intent)
        start_date = time_range_dict["start_date"]
        end_date = time_range_dict["end_date"]

        # 解析组织范围
        org_scope_dict = self._parse_org_scope(intent, table_definition)

        # 构建 WHERE 子句
        where_clauses = [
            f"{table_definition.metric_code_column} = '{metric_definition.metric_code}'",
        ]

        # 添加时间范围过滤
        where_clauses.extend([
            f"{table_definition.time_column} >= '{start_date}'",
            f"{table_definition.time_column} <= '{end_date}'",
        ])

        # 添加组织范围过滤
        if org_scope_dict:
            where_clauses.append(org_scope_dict["where_clause"])

        # 添加部门过滤
        if table_definition.department_filter_column:
            if not department_code:
                raise ValueError("当前表要求部门范围过滤，但未提供 department_code")
            where_clauses.append(
                f"{table_definition.department_filter_column} = '{department_code}'"
            )

        # 构建 SELECT 子句
        select_fields = [table_definition.metric_name_column]

        group_by_fields = []
        group_by_rule = None

        # 处理 group_by
        if intent.group_by:
            group_by_rule = self.schema_registry.get_group_by_rule(
                intent.group_by,
                table_name=table_definition.name,
                data_source=data_source,
            )
            if group_by_rule:
                select_fields.append(f"{group_by_rule.select_expression} AS {group_by_rule.alias}")
                group_by_fields.append(group_by_rule.group_expression)

        # 处理对比目标（yoy/mom）
        compare_target_str = (
            intent.compare_target.value
            if hasattr(intent.compare_target, "value")
            else intent.compare_target
        ) if intent.compare_target else CompareTarget.NONE.value

        if compare_target_str in {"yoy", "mom"}:
            compare_range = self._build_compare_range(start_date, end_date, compare_target_str)
            select_fields.extend([
                (
                    f"{metric_definition.aggregation}(CASE "
                    f"WHEN {table_definition.time_column} >= '{start_date}' "
                    f"AND {table_definition.time_column} <= '{end_date}' "
                    f"THEN {table_definition.metric_value_column} ELSE 0 END) AS current_value"
                ),
                (
                    f"{metric_definition.aggregation}(CASE "
                    f"WHEN {table_definition.time_column} >= '{compare_range['start_date']}' "
                    f"AND {table_definition.time_column} <= '{compare_range['end_date']}' "
                    f"THEN {table_definition.metric_value_column} ELSE 0 END) AS compare_value"
                ),
            ])
            where_clauses.extend([
                f"{table_definition.time_column} >= '{compare_range['start_date']}'",
                f"{table_definition.time_column} <= '{end_date}'",
            ])
        else:
            select_fields.append(
                f"{metric_definition.aggregation}({table_definition.metric_value_column}) AS total_value"
            )

        # 构建 ORDER BY
        order_by_clause = ""
        sort_direction = (
            intent.sort_direction.value
            if hasattr(intent.sort_direction, "value")
            else intent.sort_direction
        ) if intent.sort_direction else "desc"

        if intent.top_n:
            ranking_col = "current_value" if compare_target_str in {"yoy", "mom"} else "total_value"
            order_by_clause = f" ORDER BY {ranking_col} {sort_direction.upper()} LIMIT {intent.top_n}"
        elif compare_target_str in {"yoy", "mom"} and not intent.group_by:
            order_by_clause = " ORDER BY current_value DESC"
        elif group_by_rule:
            order_by_clause = f" ORDER BY {group_by_rule.order_by_expression}"

        # 组合 SQL
        sql = f"SELECT {', '.join(select_fields)} FROM {table_definition.name} WHERE {' AND '.join(where_clauses)}"

        if group_by_fields:
            sql += f" GROUP BY {', '.join(group_by_fields + [table_definition.metric_name_column])}"
        else:
            sql += f" GROUP BY {table_definition.metric_name_column}"

        sql += order_by_clause

        return {
            "generated_sql": sql,
            "metric_scope": metric_name,
            "data_source": data_source,
            "builder_metadata": {
                "planning_mode": "direct",
                "complexity": intent.complexity.value if hasattr(intent.complexity, "value") else intent.complexity,
                "group_by": intent.group_by,
                "compare_target": compare_target_str,
                "top_n": intent.top_n,
                "sort_direction": sort_direction,
                "time_range_label": intent.time_range.raw_text if intent.time_range else None,
                "org_scope": intent.org_scope.raw_text if intent.org_scope else None,
                "table_name": table_definition.name,
                "db_type": self.schema_registry.get_data_source(data_source).db_type,
                "metric_code": metric_definition.metric_code,
                "allowed_tables": self.schema_registry.get_allowed_tables(data_source=data_source),
                "field_whitelist_reserved": self.schema_registry.get_table_field_whitelist(
                    table_name=table_definition.name,
                    data_source=data_source,
                ),
                "effective_filters": {
                    "metric_code": metric_definition.metric_code,
                    "time_range": {
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                    "org_scope": intent.org_scope.raw_text if intent.org_scope else None,
                    "department_code": department_code if table_definition.department_filter_column else None,
                },
                "sql_template_version": "analytics_intent_v1",
            },
        }

    def _build_complex_sql(
        self,
        intent: AnalyticsIntent,
        *,
        department_code: str | None = None,
    ) -> dict:
        """构造复杂查询 SQL（decomposed 模式）。

        对于 complex 查询，需要根据 required_queries 生成多个子查询，
        然后组合成一个复合 SQL 或多个独立 SQL。
        """

        if not intent.required_queries:
            raise ValueError("complex 模式下 required_queries 不能为空")

        # 目前先支持单个主查询 + 基准查询的组合
        # 后续可扩展为完整的 CTAS/WITH 语句
        sub_queries = []

        for req_query in intent.required_queries:
            sub_sql = self._build_required_query_sql(
                req_query=req_query,
                intent=intent,
                department_code=department_code,
            )
            sub_queries.append(sub_sql)

        # 生成主 SQL（基于 current 角色）
        current_query = None
        baseline_query = None

        for i, req_query in enumerate(intent.required_queries):
            period_role = (
                req_query.period_role.value
                if hasattr(req_query.period_role, "value")
                else req_query.period_role
            )
            if period_role in ("main", "current"):
                current_query = sub_queries[i]
            elif period_role in ("yoy_baseline", "mom_baseline"):
                baseline_query = sub_queries[i]

        # 如果有基准查询，生成带对比的 SQL
        if current_query and baseline_query:
            # 简化版本：直接使用 current_query 的 SQL，基准数据在后续处理
            main_sql = current_query["generated_sql"]
            builder_metadata = current_query["builder_metadata"].copy()
            builder_metadata.update({
                "planning_mode": "decomposed",
                "has_baseline_query": True,
                "baseline_sql": baseline_query["generated_sql"],
                "required_queries": [
                    {
                        "query_name": rq.query_name,
                        "period_role": rq.period_role.value if hasattr(rq.period_role, "value") else rq.period_role,
                        "metric_code": rq.metric_code,
                    }
                    for rq in intent.required_queries
                ],
            })

            return {
                "generated_sql": main_sql,
                "metric_scope": current_query["metric_scope"],
                "data_source": current_query["data_source"],
                "sub_queries": sub_queries,
                "builder_metadata": builder_metadata,
            }

        # 没有基准查询，直接返回
        return current_query if current_query else sub_queries[0]

    def _build_required_query_sql(
        self,
        req_query: RequiredQueryIntent,
        intent: AnalyticsIntent,
        *,
        department_code: str | None = None,
    ) -> dict:
        """为单个 required_query 生成 SQL。"""

        # 优先使用 metric_name（resolve_metric 只支持名称查找）
        metric_code = req_query.metric_code or (intent.metric.metric_code if intent.metric else None)
        metric_name = req_query.metric_code  # 这里 req_query.metric_code 应该是 metric_code

        # 尝试通过 metric_name 查找（resolve_metric 只支持名称）
        metric_definition = None

        # 首先尝试用 intent.metric.metric_name 查找
        if intent.metric and intent.metric.metric_name:
            metric_definition = self.metric_catalog.resolve_metric(intent.metric.metric_name)

        # 如果找不到，尝试遍历 _metrics 通过 metric_code 查找
        if metric_definition is None and metric_code:
            for m in self.metric_catalog._metrics.values():
                if m.metric_code == metric_code:
                    metric_definition = m
                    break

        if metric_definition is None:
            raise ValueError(f"无法解析指标：{metric_code}")

        data_source = metric_definition.data_source
        table_definition = self.schema_registry.get_table_definition(
            table_name=metric_definition.table_name,
            data_source=data_source,
        )

        # 根据 period_role 计算时间范围
        period_role = (
            req_query.period_role.value
            if hasattr(req_query.period_role, "value")
            else req_query.period_role
        )

        time_range_dict = self._parse_time_range(intent)
        start_date = time_range_dict["start_date"]
        end_date = time_range_dict["end_date"]

        if period_role == "yoy_baseline":
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            start_date = start_dt.replace(year=start_dt.year - 1).strftime("%Y-%m-%d")
            end_date = end_dt.replace(year=end_dt.year - 1).strftime("%Y-%m-%d")
        elif period_role == "mom_baseline":
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            start_date = self._shift_month_str(start_date, -1)
            end_date = self._shift_month_str(end_date, -1)

        # 构建 WHERE
        where_clauses = [
            f"{table_definition.metric_code_column} = '{metric_definition.metric_code}'",
            f"{table_definition.time_column} >= '{start_date}'",
            f"{table_definition.time_column} <= '{end_date}'",
        ]

        # 添加部门过滤
        if table_definition.department_filter_column and department_code:
            where_clauses.append(
                f"{table_definition.department_filter_column} = '{department_code}'"
            )

        # SELECT
        select_fields = [table_definition.metric_name_column]

        group_by_rule = None
        if req_query.group_by:
            group_by_rule = self.schema_registry.get_group_by_rule(
                req_query.group_by,
                table_name=table_definition.name,
                data_source=data_source,
            )
            if group_by_rule:
                select_fields.append(f"{group_by_rule.select_expression} AS {group_by_rule.alias}")

        select_fields.append(
            f"{metric_definition.aggregation}({table_definition.metric_value_column}) AS total_value"
        )

        # GROUP BY
        group_by_fields = []
        if group_by_rule:
            group_by_fields.append(group_by_rule.group_expression)
            order_by = f" ORDER BY {group_by_rule.order_by_expression}"
        else:
            order_by = ""

        sql = f"SELECT {', '.join(select_fields)} FROM {table_definition.name} WHERE {' AND '.join(where_clauses)}"

        if group_by_fields:
            sql += f" GROUP BY {', '.join(group_by_fields + [table_definition.metric_name_column])}"
        else:
            sql += f" GROUP BY {table_definition.metric_name_column}"

        sql += order_by

        return {
            "generated_sql": sql,
            "metric_scope": metric_name,
            "data_source": data_source,
            "builder_metadata": {
                "query_name": req_query.query_name,
                "period_role": period_role,
                "group_by": req_query.group_by,
                "metric_code": metric_definition.metric_code,
                "time_range": {"start_date": start_date, "end_date": end_date},
            },
        }

    def _parse_time_range(self, intent: AnalyticsIntent) -> dict:
        """解析时间范围。"""

        if intent.time_range is None:
            raise ValueError("AnalyticsIntent 中缺少 time_range")

        # 如果已有 start_date 和 end_date，直接使用
        if intent.time_range.start and intent.time_range.end:
            return {
                "start_date": intent.time_range.start,
                "end_date": intent.time_range.end,
            }

        # 否则根据 type 推断
        time_type = (
            intent.time_range.type.value
            if hasattr(intent.time_range.type, "value")
            else intent.time_range.type
        )

        if time_type == "absolute" and intent.time_range.value:
            # 绝对时间，如 "2024-03"
            return {
                "start_date": f"{intent.time_range.value}-01",
                "end_date": f"{intent.time_range.value}-31",
            }

        # 相对时间，需要根据当前时间计算
        now = datetime.now()
        if "本月" in (intent.time_range.raw_text or ""):
            return {
                "start_date": f"{now.year}-{now.month:02d}-01",
                "end_date": f"{now.year}-{now.month:02d}-31",
            }
        elif "上个月" in (intent.time_range.raw_text or ""):
            prev_month = self._shift_month(now, -1)
            return {
                "start_date": f"{prev_month.year}-{prev_month.month:02d}-01",
                "end_date": f"{prev_month.year}-{prev_month.month:02d}-31",
            }
        elif "最近" in (intent.time_range.raw_text or "") and "月" in (intent.time_range.raw_text or ""):
            import re
            match = re.search(r"最近(\d+)个?月", intent.time_range.raw_text or "")
            if match:
                month_count = int(match.group(1))
                start_date = self._shift_month(now, -month_count + 1)
                return {
                    "start_date": f"{start_date.year}-{start_date.month:02d}-01",
                    "end_date": f"{now.year}-{now.month:02d}-31",
                }

        # 默认返回当前月
        return {
            "start_date": f"{now.year}-{now.month:02d}-01",
            "end_date": f"{now.year}-{now.month:02d}-31",
        }

    def _parse_org_scope(self, intent: AnalyticsIntent, table_definition) -> dict | None:
        """解析组织范围。"""

        if intent.org_scope is None:
            return None

        org_type = (
            intent.org_scope.type.value
            if hasattr(intent.org_scope.type, "value")
            else intent.org_scope.type
        ) if intent.org_scope.type else None

        org_name = intent.org_scope.name or intent.org_scope.raw_text

        if org_type == "region" and table_definition.dimension_columns.get("region"):
            return {
                "where_clause": f"{table_definition.dimension_columns['region']} = '{org_name}'",
                "type": org_type,
                "value": org_name,
            }
        elif org_type == "station" and table_definition.dimension_columns.get("station"):
            return {
                "where_clause": f"{table_definition.dimension_columns['station']} = '{org_name}'",
                "type": org_type,
                "value": org_name,
            }

        return None

    def _build_compare_range(self, start_date: str, end_date: str, compare_target: str) -> dict:
        """构造环比 / 同比比较时间范围。"""

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        if compare_target == "mom":
            compare_start = self._shift_month(start_dt, -1)
            compare_end = self._shift_month(end_dt, -1)
        else:  # yoy
            compare_start = start_dt.replace(year=start_dt.year - 1)
            compare_end = end_dt.replace(year=end_dt.year - 1)

        return {
            "start_date": compare_start.strftime("%Y-%m-%d"),
            "end_date": compare_end.strftime("%Y-%m-%d"),
        }

    def _shift_month(self, target_date: datetime, month_delta: int) -> datetime:
        """按月平移日期，并自动处理月底越界。"""

        total_month = (target_date.year * 12 + target_date.month - 1) + month_delta
        new_year = total_month // 12
        new_month = total_month % 12 + 1
        max_day = calendar.monthrange(new_year, new_month)[1]
        new_day = min(target_date.day, max_day)
        return target_date.replace(year=new_year, month=new_month, day=new_day)

    def _shift_month_str(self, date_str: str, month_delta: int) -> str:
        """按月平移日期字符串。"""

        dt = datetime.strptime(date_str, "%Y-%m-%d")
        shifted = self._shift_month(dt, month_delta)
        return shifted.strftime("%Y-%m-%d")
