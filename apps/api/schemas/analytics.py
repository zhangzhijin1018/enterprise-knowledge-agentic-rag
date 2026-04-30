"""经营分析接口 Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AnalyticsQueryRequest(BaseModel):
    """经营分析提交请求。"""

    query: str = Field(description="经营分析自然语言问题")

    conversation_id: str | None = Field(default=None, description="会话 ID")

    output_mode: str = Field(default="lite", description="输出模式：lite / standard / full")

    need_sql_explain: bool = Field(default=False, description="是否返回 SQL 解释")


class AnalyticsClarificationReplyRequest(BaseModel):
    """经营分析澄清回复请求。"""

    reply: str = Field(description="用户针对经营分析澄清问题补充的内容")
    output_mode: str = Field(default="lite", description="恢复执行后希望返回的输出模式：lite / standard / full")
    need_sql_explain: bool = Field(default=False, description="恢复执行后是否返回 SQL 解释")


class AnalyticsResultTable(BaseModel):
    """经营分析结果表。"""

    name: str = Field(description="结果表名称")
    columns: list[str] = Field(default_factory=list, description="列名列表")
    rows: list[list] = Field(default_factory=list, description="行数据")


class AnalyticsClarificationData(BaseModel):
    """经营分析澄清响应。"""

    clarification_id: str = Field(description="澄清事件 ID")
    question: str = Field(description="澄清问题")
    target_slots: list[str] = Field(default_factory=list, description="目标槽位列表")
    clarification_type: str | None = Field(default=None, description="澄清类型，例如 missing_required_slot 或 slot_conflict")
    reason: str | None = Field(default=None, description="触发澄清的规则原因")
    suggested_options: list[str] = Field(default_factory=list, description="建议补充选项")


class AnalyticsClarificationDetailData(BaseModel):
    """经营分析澄清详情。"""

    clarification_id: str = Field(description="澄清事件 ID")
    run_id: str = Field(description="关联经营分析 run_id")
    conversation_id: str = Field(description="关联会话 ID")
    question: str = Field(description="系统发出的澄清问题")
    target_slots: list[str] = Field(default_factory=list, description="本轮需要补齐的目标槽位")
    user_reply: str | None = Field(default=None, description="用户已经提交的补充内容")
    resolved_slots: dict = Field(default_factory=dict, description="从用户回复中解析出的结构化槽位")
    status: str = Field(description="澄清事件状态，例如 pending / resolved")
    created_at: datetime | None = Field(default=None, description="澄清创建时间")
    resolved_at: datetime | None = Field(default=None, description="澄清解决时间")


class AnalyticsQueryResponseData(BaseModel):
    """经营分析提交响应。

    V1 性能优化：支持 output_mode 分级返回。
    - lite：summary、row_count、latency_ms、run_id、trace_id
    - standard：在 lite 基础上增加 chart_spec、insight_cards
    - full：在 standard 基础上增加 tables、report_blocks、完整治理信息
    """

    run_id: str | None = Field(default=None, description="任务运行 ID")
    trace_id: str | None = Field(default=None, description="Trace ID")
    summary: str | None = Field(default=None, description="结果摘要")
    row_count: int | None = Field(default=None, description="返回行数")
    latency_ms: int | None = Field(default=None, description="执行耗时")
    metric_scope: str | None = Field(default=None, description="指标范围说明")
    data_source: str | None = Field(default=None, description="执行数据源")
    compare_target: str | None = Field(default=None, description="对比目标")
    group_by: str | None = Field(default=None, description="分组维度")
    tables: list[AnalyticsResultTable] = Field(default_factory=list, description="结果表列表")
    sql_explain: str | None = Field(default=None, description="SQL 解释信息")
    sql_preview: str | None = Field(default=None, description="最终执行前 SQL 预览")
    safety_check_result: dict | None = Field(default=None, description="SQL 安全检查结果")
    chart_spec: dict | None = Field(default=None, description="前端可渲染的图表描述")
    insight_cards: list[dict] = Field(default_factory=list, description="最小洞察卡片")
    report_blocks: list[dict] = Field(default_factory=list, description="后续报告导出可复用的结构化块")
    audit_info: dict | None = Field(default=None, description="最小 SQL 审计摘要")
    permission_check_result: dict | None = Field(default=None, description="指标/数据源权限检查结果")
    data_scope_result: dict | None = Field(default=None, description="数据范围治理结果")
    masked_fields: list[str] = Field(default_factory=list, description="当前结果中被脱敏的字段")
    effective_filters: dict = Field(default_factory=dict, description="实际生效的数据过滤条件")
    governance_decision: dict | None = Field(default=None, description="治理决策摘要")
    timing_breakdown: dict = Field(default_factory=dict, description="关键阶段耗时分布")
    clarification: AnalyticsClarificationData | None = Field(default=None, description="澄清信息")


class AnalyticsRunDetailData(BaseModel):
    """经营分析运行详情。

    V1 性能优化：支持 output_mode 分级返回。
    """

    run_id: str = Field(description="任务运行 ID")
    conversation_id: str | None = Field(default=None, description="会话 ID")
    task_type: str = Field(description="任务类型")
    route: str | None = Field(default=None, description="路由结果")
    status: str = Field(description="主状态")
    sub_status: str | None = Field(default=None, description="子状态")
    trace_id: str = Field(description="Trace ID")
    summary: str | None = Field(default=None, description="结果摘要")
    row_count: int | None = Field(default=None, description="返回行数")
    latency_ms: int | None = Field(default=None, description="执行耗时")
    metric_scope: str | None = Field(default=None, description="指标范围说明")
    data_source: str | None = Field(default=None, description="执行数据源")
    compare_target: str | None = Field(default=None, description="对比目标")
    group_by: str | None = Field(default=None, description="分组维度")
    slots: dict = Field(default_factory=dict, description="槽位快照")
    latest_sql_audit: dict | None = Field(default=None, description="最新 SQL 审计信息")
    tables: list[AnalyticsResultTable] = Field(default_factory=list, description="结果表列表")
    sql_explain: str | None = Field(default=None, description="SQL 解释信息")
    sql_preview: str | None = Field(default=None, description="最终执行前 SQL 预览")
    safety_check_result: dict | None = Field(default=None, description="SQL 安全检查结果")
    chart_spec: dict | None = Field(default=None, description="前端可渲染的图表描述")
    insight_cards: list[dict] = Field(default_factory=list, description="最小洞察卡片")
    report_blocks: list[dict] = Field(default_factory=list, description="后续报告导出可复用的结构化块")
    audit_info: dict | None = Field(default=None, description="最小 SQL 审计摘要")
    permission_check_result: dict | None = Field(default=None, description="指标/数据源权限检查结果")
    data_scope_result: dict | None = Field(default=None, description="数据范围治理结果")
    masked_fields: list[str] = Field(default_factory=list, description="当前结果中被脱敏的字段")
    effective_filters: dict = Field(default_factory=dict, description="实际生效的数据过滤条件")
    governance_decision: dict | None = Field(default=None, description="治理决策摘要")
    output_snapshot: dict = Field(default_factory=dict, description="结果快照")
    timing_breakdown: dict = Field(default_factory=dict, description="关键阶段耗时分布")
