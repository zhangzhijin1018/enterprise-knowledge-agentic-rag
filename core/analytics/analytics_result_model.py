"""经营分析结果模型。

这是经营分析工作流最终输出的结构化结果对象，
用于承载查询结果、摘要、图表、洞察、报告等完整输出。

设计原则：
- 作为 workflow 对外部 service/export/result_repository 提供的标准载体
- 轻部分会进入 task_run.output_snapshot
- 重部分会拆到 analytics_result_repository
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AnalyticsResult(BaseModel):
    """经营分析统一结果对象。

    用于承载查询结果、摘要、图表、洞察、报告等完整输出。

    字段说明：
    - run_id/trace_id：链路追踪
    - summary：文本摘要
    - sql_preview：SQL 预览（脱敏后）
    - chart_spec/insight_cards/report_blocks：按 output_mode 生成
    - governance_decision：数据治理决策
    - timing_breakdown：各阶段耗时
    """

    run_id: str = Field(description="运行 ID")
    trace_id: str = Field(description="追踪 ID")

    # 核心结果
    summary: str = Field(description="文本摘要")
    sql_preview: str = Field(description="SQL 预览（脱敏后）")
    row_count: int = Field(description="结果行数")
    latency_ms: int = Field(description="执行耗时（毫秒）")

    # 数据源信息
    data_source: str = Field(description="数据源标识")
    metric_scope: str = Field(description="指标范围")

    # 分析维度
    compare_target: str | None = Field(default=None, description="对比目标")
    group_by: str | None = Field(default=None, description="分组维度")

    # 槽位信息
    slots: dict = Field(description="原始槽位")

    # 规划信息
    planning_source: str = Field(description="规划来源")

    # 查询结果
    columns: list[str] = Field(default_factory=list, description="列名")
    rows: list[dict] = Field(default_factory=list, description="原始行数据")

    # 脱敏结果
    masked_columns: list[str] = Field(default_factory=list, description="脱敏后列名")
    masked_rows: list[dict] = Field(default_factory=list, description="脱敏后行数据")

    # 字段权限
    visible_fields: list[str] = Field(default_factory=list, description="可见字段")
    sensitive_fields: list[str] = Field(default_factory=list, description="敏感字段")
    masked_fields: list[str] = Field(default_factory=list, description="已脱敏字段")
    hidden_fields: list[str] = Field(default_factory=list, description="已隐藏字段")

    # 治理决策
    governance_decision: dict = Field(default_factory=dict, description="数据治理决策")

    # 图表和洞察
    chart_spec: dict | None = Field(default=None, description="图表规格（standard/full 模式）")
    insight_cards: list[dict] = Field(default_factory=list, description="洞察卡片（standard/full 模式）")
    report_blocks: list[dict] = Field(default_factory=list, description="报告块（full 模式）")

    # 安全检查
    safety_check_result: dict = Field(default_factory=dict, description="安全检查结果")

    # 权限检查
    permission_check_result: dict = Field(default_factory=dict, description="权限检查结果")
    data_scope_result: dict = Field(default_factory=dict, description="数据范围结果")

    # 有效过滤
    effective_filters: dict = Field(default_factory=dict, description="有效过滤条件")

    # 审计信息
    audit_info: dict = Field(default_factory=dict, description="审计信息")

    # SQL 说明
    sql_explain: str | None = Field(default=None, description="SQL 说明")

    # 性能信息
    timing_breakdown: dict[str, float] = Field(default_factory=dict, description="各阶段耗时")

    # 降级信息
    degraded: bool = Field(default=False, description="是否发生降级")
    degraded_features: list[str] = Field(default_factory=list, description="降级特性列表")

    # 重试信息
    retry_summary: dict = Field(default_factory=dict, description="重试摘要")

    class Config:
        """Pydantic 配置。"""

        extra = "allow"

    def to_lite_view(self) -> dict:
        """转换为 lite 视图。

        lite 模式只返回摘要和基本信息，不包含图表、洞察、报告。
        """

        return {
            "summary": self.summary,
            "sql_preview": self.sql_preview,
            "row_count": self.row_count,
            "latency_ms": self.latency_ms,
            "trace_id": self.trace_id,
        }

    def to_standard_view(self) -> dict:
        """转换为 standard 视图。

        standard 模式返回摘要、图表、洞察，不包含报告。
        """

        return {
            "summary": self.summary,
            "sql_preview": self.sql_preview,
            "row_count": self.row_count,
            "latency_ms": self.latency_ms,
            "data_source": self.data_source,
            "metric_scope": self.metric_scope,
            "compare_target": self.compare_target,
            "group_by": self.group_by,
            "columns": self.masked_columns,
            "rows": self.masked_rows,
            "chart_spec": self.chart_spec,
            "insight_cards": self.insight_cards,
            "governance_decision": self.governance_decision,
            "safety_check_result": self.safety_check_result,
            "trace_id": self.trace_id,
        }

    def to_full_view(self) -> dict:
        """转换为 full 视图。

        full 模式返回完整信息，包括报告。
        """

        result = self.to_standard_view()
        result["report_blocks"] = self.report_blocks
        result["audit_info"] = self.audit_info
        result["timing_breakdown"] = self.timing_breakdown
        result["degraded"] = self.degraded
        result["degraded_features"] = self.degraded_features
        return result

    def to_heavy_result(self) -> dict:
        """转换为重结果（用于持久化到 analytics_result_repository）。

        重结果包含完整行数据和图表规格。
        """

        return {
            "tables": [
                {
                    "name": "main_result",
                    "columns": self.columns,
                    "rows": self.rows,
                }
            ],
            "chart_spec": self.chart_spec,
            "insight_cards": self.insight_cards,
            "report_blocks": self.report_blocks,
            "governance_decision": self.governance_decision,
            "audit_info": self.audit_info,
        }

    def to_lightweight_snapshot(self) -> dict:
        """转换为轻量快照（用于 task_run.output_snapshot）。

        轻量快照只包含摘要信息，不包含大数据字段。
        这是为了避免 task_run.output_snapshot 膨胀。
        """

        return {
            "summary": self.summary,
            "sql_preview": self.sql_preview,
            "row_count": self.row_count,
            "latency_ms": self.latency_ms,
            "data_source": self.data_source,
            "metric_scope": self.metric_scope,
            "compare_target": self.compare_target,
            "group_by": self.group_by,
            "planning_source": self.planning_source,
            "chart_spec": self.chart_spec,
            "insight_cards": self.insight_cards,
            "governance_decision": {
                "masked_fields": self.masked_fields,
                "visible_fields": self.visible_fields,
                "sensitive_fields": self.sensitive_fields,
            },
            "safety_check_result": {
                "is_safe": self.safety_check_result.get("is_safe") if isinstance(self.safety_check_result, dict) else True,
            },
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "degraded": self.degraded,
            "degraded_features": self.degraded_features,
        }
