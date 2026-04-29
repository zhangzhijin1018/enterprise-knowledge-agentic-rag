"""经营分析统一结果对象。

为什么需要统一结果对象：
1. 当前 analytics 执行后，结果散落在 execution_result.rows、masking_result.rows、
   tables.rows、export payload 等多处，存在大量重复拷贝；
2. 统一结果对象可以让 SQL 执行后的数据只保留一份，
   其他环节通过视图转换来消费，减少内存复制；
3. 同时为 output_snapshot 轻量化提供基础：
   轻快照只引用 run_id，重内容按需从结果仓储读取。

设计原则：
- 统一结果对象是"一次查询的完整结果"的唯一载体；
- 其他环节（masking、insight、chart、export）通过方法/视图消费，不重复拷贝；
- 支持 lite / standard / full 三种输出模式的视图转换。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AnalyticsResult:
    """经营分析统一查询结果对象。

    SQL 执行后的数据只保留一份，其他环节通过视图转换消费。
    """

    run_id: str
    trace_id: str
    summary: str
    sql_preview: str
    row_count: int
    latency_ms: int
    data_source: str
    metric_scope: str
    compare_target: str | None = None
    group_by: str | None = None
    slots: dict = field(default_factory=dict)
    planning_source: str | None = None

    columns: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)

    masked_columns: list[str] = field(default_factory=list)
    masked_rows: list[dict] = field(default_factory=list)
    visible_fields: list[str] = field(default_factory=list)
    sensitive_fields: list[str] = field(default_factory=list)
    masked_fields: list[str] = field(default_factory=list)
    hidden_fields: list[str] = field(default_factory=list)
    governance_decision: str = "no_masking_needed"

    chart_spec: dict | None = None
    insight_cards: list[dict] = field(default_factory=list)
    report_blocks: list[dict] = field(default_factory=list)

    safety_check_result: dict | None = None
    permission_check_result: dict | None = None
    data_scope_result: dict | None = None
    effective_filters: dict = field(default_factory=dict)
    audit_info: dict | None = None
    sql_explain: str | None = None

    timing_breakdown: dict = field(default_factory=dict)
    _tables_cache: list[dict] | None = field(default=None, init=False, repr=False)
    _governance_summary_cache: dict | None = field(default=None, init=False, repr=False)

    def to_lite_view(self) -> dict:
        """轻量视图：只包含核心摘要信息。

        适用于主查询接口默认返回，减少 payload 体积。
        """

        return {
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "summary": self.summary,
            "row_count": self.row_count,
            "latency_ms": self.latency_ms,
            "metric_scope": self.metric_scope,
            "data_source": self.data_source,
            "compare_target": self.compare_target,
            "group_by": self.group_by,
        }

    def to_standard_view(self) -> dict:
        """标准视图：在 lite 基础上增加 chart_spec 和 insight_cards。

        适用于前端需要图表和洞察卡片的场景。
        """

        view = self.to_lite_view()
        view.update({
            "sql_preview": self.sql_preview,
            "chart_spec": self.chart_spec,
            "insight_cards": self.insight_cards,
            "masked_fields": self.masked_fields,
            "effective_filters": self.effective_filters,
            "governance_decision": self._build_governance_summary(),
        })
        return view

    def to_full_view(self) -> dict:
        """完整视图：在 standard 基础上增加 tables、report_blocks、完整治理信息。

        适用于 run detail、export 等需要完整数据的场景。
        """

        view = self.to_standard_view()
        view.update({
            "tables": self._build_tables(),
            "report_blocks": self.report_blocks,
            "sql_explain": self.sql_explain,
            "safety_check_result": self.safety_check_result,
            "permission_check_result": self.permission_check_result,
            "data_scope_result": self.data_scope_result,
            "audit_info": self.audit_info,
            "slots": self.slots,
            "timing_breakdown": self.timing_breakdown,
        })
        return view

    def to_lightweight_snapshot(self) -> dict:
        """轻快照：写入 task_run.output_snapshot 的最小内容。

        为什么 output_snapshot 不能无限膨胀：
        1. output_snapshot 存储在 task_run 记录中，每次读取 task_run 都会加载整个 JSON；
        2. tables / report_blocks / insight_cards 等重内容体积大，
           导致 task_run 的读写压力显著增加；
        3. 大 JSON 写入和读取会拖慢数据库查询和 API 响应。

        为什么要拆轻快照与重结果：
        1. 轻快照保留核心摘要信息，满足"快速查看运行状态"的需求；
        2. 重内容按需从 analytics_result_repository 读取，
           不影响主查询链路的响应速度；
        3. 导出和详情页可以按需读取重内容，不影响轻查询场景。
        """

        return {
            "summary": self.summary,
            "slots": self.slots,
            "sql_preview": self.sql_preview,
            "row_count": self.row_count,
            "latency_ms": self.latency_ms,
            "compare_target": self.compare_target,
            "group_by": self.group_by,
            "metric_scope": self.metric_scope,
            "data_source": self.data_source,
            "governance_decision": self._build_governance_summary(),
            "timing_breakdown": self.timing_breakdown,
            "has_heavy_result": True,
        }

    def to_heavy_result(self) -> dict:
        """重内容：单独存储到 analytics_result_repository。

        包含 tables、insight_cards、report_blocks、chart_spec 等大体积内容。
        """

        return {
            "tables": self._build_tables(),
            "insight_cards": self.insight_cards,
            "report_blocks": self.report_blocks,
            "chart_spec": self.chart_spec,
            "sql_explain": self.sql_explain,
            "safety_check_result": self.safety_check_result,
            "permission_check_result": self.permission_check_result,
            "data_scope_result": self.data_scope_result,
            "audit_info": self.audit_info,
            "masked_fields": self.masked_fields,
            "effective_filters": self.effective_filters,
            "timing_breakdown": self.timing_breakdown,
        }

    def _build_tables(self) -> list[dict]:
        """构造结果表，使用脱敏后的行数据。"""

        if self._tables_cache is not None:
            return self._tables_cache

        rows_source = self.masked_rows if self.masked_rows else self.rows
        self._tables_cache = [
            {
                "name": "main_result",
                "columns": self.masked_columns if self.masked_columns else self.columns,
                "rows": [list(row.values()) for row in rows_source],
            }
        ]
        return self._tables_cache

    def _build_governance_summary(self) -> dict:
        """构造治理决策简版摘要。"""

        if self._governance_summary_cache is not None:
            return self._governance_summary_cache

        self._governance_summary_cache = {
            "action": self.governance_decision,
            "masked_fields": self.masked_fields,
            "effective_filters": self.effective_filters,
        }
        return self._governance_summary_cache
