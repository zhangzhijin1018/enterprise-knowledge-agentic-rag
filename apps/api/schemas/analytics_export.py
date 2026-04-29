"""经营分析导出接口 Schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyticsExportRequest(BaseModel):
    """经营分析导出请求。"""

    export_type: str = Field(description="导出类型，例如 json、markdown、docx、pdf")

    export_template: str | None = Field(default=None, description="导出模板类型，例如 weekly_report、monthly_report")


class AnalyticsExportData(BaseModel):
    """经营分析导出结果。

    V1 性能优化：导出已改为真正异步任务语义。
    POST export 只创建任务并返回 export_id，后台异步处理，
    前端通过 GET export detail 轮询读取状态。
    """

    export_id: str = Field(description="导出任务 ID")

    run_id: str = Field(description="经营分析运行 ID")

    export_type: str = Field(description="导出类型")

    export_template: str | None = Field(default=None, description="导出模板类型")

    status: str = Field(description="导出任务状态：pending / running / succeeded / failed / awaiting_human_review")

    review_required: bool = Field(default=False, description="是否需要人工审核")

    review_id: str | None = Field(default=None, description="审核任务 ID")

    review_status: str = Field(default="not_required", description="审核状态")

    review_level: str | None = Field(default=None, description="审核级别")

    review_reason: str | None = Field(default=None, description="审核原因")

    reviewer: str | None = Field(default=None, description="审核人显示名")

    filename: str | None = Field(default=None, description="导出文件名")

    content_preview: str | None = Field(default=None, description="导出内容预览")

    artifact_path: str | None = Field(default=None, description="本地产物路径")

    file_uri: str | None = Field(default=None, description="文件访问 URI")

    created_at: str = Field(description="导出任务创建时间")

    finished_at: str | None = Field(default=None, description="导出任务完成时间")

    reviewed_at: str | None = Field(default=None, description="审核完成时间")

    metadata: dict = Field(default_factory=dict, description="导出任务附加元数据")

    governance_decision: dict = Field(default_factory=dict, description="导出治理决策摘要")
