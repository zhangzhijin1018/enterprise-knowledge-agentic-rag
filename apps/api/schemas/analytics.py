"""经营分析接口 Schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyticsQueryRequest(BaseModel):
    """经营分析提交请求。"""

    # 用户原始分析问题。
    query: str = Field(description="经营分析自然语言问题")

    # 可选会话 ID。多轮时用于继承上下文和承接澄清。
    conversation_id: str | None = Field(default=None, description="会话 ID")

    # 当前阶段先保留输出模式字段，为后续表格、摘要、报告多模式扩展预留。
    output_mode: str = Field(default="summary", description="输出模式")

    # 是否返回 SQL 解释信息。用于前端联调和后续审计透明化。
    need_sql_explain: bool = Field(default=False, description="是否返回 SQL 解释")


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


class AnalyticsQueryResponseData(BaseModel):
    """经营分析提交响应。"""

    summary: str | None = Field(default=None, description="结果摘要")
    tables: list[AnalyticsResultTable] = Field(default_factory=list, description="结果表列表")
    sql_explain: str | None = Field(default=None, description="SQL 解释信息")
    sql_preview: str | None = Field(default=None, description="最终执行前 SQL 预览")
    safety_check_result: dict | None = Field(default=None, description="SQL 安全检查结果")
    metric_scope: str | None = Field(default=None, description="指标范围说明")
    data_source: str | None = Field(default=None, description="执行数据源")
    row_count: int | None = Field(default=None, description="返回行数")
    latency_ms: int | None = Field(default=None, description="执行耗时")
    compare_target: str | None = Field(default=None, description="对比目标")
    group_by: str | None = Field(default=None, description="分组维度")
    chart_spec: dict | None = Field(default=None, description="前端可渲染的图表描述")
    insight_cards: list[dict] = Field(default_factory=list, description="最小洞察卡片")
    report_blocks: list[dict] = Field(default_factory=list, description="后续报告导出可复用的结构化块")
    audit_info: dict | None = Field(default=None, description="最小 SQL 审计摘要")
    clarification: AnalyticsClarificationData | None = Field(default=None, description="澄清信息")


class AnalyticsRunDetailData(BaseModel):
    """经营分析运行详情。"""

    run_id: str = Field(description="任务运行 ID")
    conversation_id: str | None = Field(default=None, description="会话 ID")
    task_type: str = Field(description="任务类型")
    route: str | None = Field(default=None, description="路由结果")
    status: str = Field(description="主状态")
    sub_status: str | None = Field(default=None, description="子状态")
    trace_id: str = Field(description="Trace ID")
    slots: dict = Field(default_factory=dict, description="槽位快照")
    latest_sql_audit: dict | None = Field(default=None, description="最新 SQL 审计信息")
    summary: str | None = Field(default=None, description="结果摘要")
    tables: list[AnalyticsResultTable] = Field(default_factory=list, description="结果表列表")
    sql_explain: str | None = Field(default=None, description="SQL 解释信息")
    sql_preview: str | None = Field(default=None, description="最终执行前 SQL 预览")
    safety_check_result: dict | None = Field(default=None, description="SQL 安全检查结果")
    metric_scope: str | None = Field(default=None, description="指标范围说明")
    data_source: str | None = Field(default=None, description="执行数据源")
    row_count: int | None = Field(default=None, description="返回行数")
    latency_ms: int | None = Field(default=None, description="执行耗时")
    compare_target: str | None = Field(default=None, description="对比目标")
    group_by: str | None = Field(default=None, description="分组维度")
    chart_spec: dict | None = Field(default=None, description="前端可渲染的图表描述")
    insight_cards: list[dict] = Field(default_factory=list, description="最小洞察卡片")
    report_blocks: list[dict] = Field(default_factory=list, description="后续报告导出可复用的结构化块")
    audit_info: dict | None = Field(default=None, description="最小 SQL 审计摘要")
    output_snapshot: dict = Field(default_factory=dict, description="结果快照")
