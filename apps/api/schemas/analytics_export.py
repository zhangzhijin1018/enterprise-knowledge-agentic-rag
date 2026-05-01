"""经营分析导出接口 Schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyticsExportRequest(BaseModel):
    """经营分析导出请求。"""

    # 导出类型。
    # 当前阶段支持：
    # - json：完整结构化结果；
    # - markdown：可直接阅读的文本报告；
    # - docx/pdf：先走占位导出链路，为后续复杂排版预留边界。
    export_type: str = Field(description="导出类型，例如 json、markdown、docx、pdf")

    # 导出模板类型。当前阶段支持 weekly_report、monthly_report；
    # 不传时表示继续使用通用导出结构。
    export_template: str | None = Field(default=None, description="导出模板类型，例如 weekly_report、monthly_report")


class AnalyticsExportData(BaseModel):
    """经营分析导出结果。"""

    # 导出任务唯一 ID，用于后续轮询导出状态和读取导出结果。
    export_id: str = Field(description="导出任务 ID")

    # 关联的经营分析运行 ID。导出任务必须依赖已完成的分析结果。
    run_id: str = Field(description="经营分析运行 ID")

    # 当前导出类型，例如 json、markdown、docx、pdf。
    export_type: str = Field(description="导出类型")

    # 当前导出模板类型。为空时表示使用通用导出结构。
    export_template: str | None = Field(default=None, description="导出模板类型")

    # 当前导出任务状态。虽然本轮用同步实现，但仍保留异步任务状态语义。
    status: str = Field(description="导出任务状态")

    # 是否需要人工审核。
    review_required: bool = Field(default=False, description="是否需要人工审核")

    # 关联审核任务 ID。
    review_id: str | None = Field(default=None, description="审核任务 ID")

    # 当前审核状态。
    review_status: str = Field(default="not_required", description="审核状态")

    # 当前审核级别。
    review_level: str | None = Field(default=None, description="审核级别")

    # 当前审核原因。
    review_reason: str | None = Field(default=None, description="审核原因")

    # 审核人显示名。
    reviewer: str | None = Field(default=None, description="审核人显示名")

    # 生成后的文件名。
    filename: str | None = Field(default=None, description="导出文件名")

    # 内容预览。当前主要给 json/markdown 使用，便于前端快速预览。
    content_preview: str | None = Field(default=None, description="导出内容预览")

    # 本地产物路径。当前阶段落到 storage/exports/，后续可替换对象存储 URI。
    artifact_path: str | None = Field(default=None, description="本地产物路径")

    # 文件访问 URI。当前阶段与 artifact_path 一致，后续可替换成对象存储地址。
    file_uri: str | None = Field(default=None, description="文件访问 URI")

    # 创建时间。用于前端展示导出任务时间线。
    created_at: str = Field(description="导出任务创建时间")

    # 完成时间。导出失败或未完成时允许为空。
    finished_at: str | None = Field(default=None, description="导出任务完成时间")

    # 审核完成时间。
    reviewed_at: str | None = Field(default=None, description="审核完成时间")

    # 导出附加元数据，用于记录 server_mode、placeholder_mode 等运行信息。
    metadata: dict = Field(default_factory=dict, description="导出任务附加元数据")

    # 当前导出关联的治理决策摘要。
    governance_decision: dict = Field(default_factory=dict, description="导出治理决策摘要")
