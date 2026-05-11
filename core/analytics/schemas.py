"""
经营分析内容生成器 - Schema 定义。

=================================================================
设计目的
=================================================================
本模块定义四个产物的 Pydantic Schema：
1. SummaryOutput - 摘要
2. InsightOutput - 洞察
3. ChartOutput - 图表
4. ReportOutput - 报告

=================================================================
设计原则
=================================================================
1. 所有字段都有中文描述，便于前端理解和调试
2. 字段命名统一，便于 TypeScript 类型生成
3. 支持 SSE Streaming 推送（小消息直接推送，大消息存库）
4. 支持报告导出（PDF/Word）
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# =============================================================================
# 枚举定义
# =============================================================================


class InsightType(str, Enum):
    """洞察类型枚举"""

    TREND = "trend"          # 趋势洞察
    RANKING = "ranking"      # 排名洞察
    COMPARISON = "comparison"  # 对比洞察
    ANOMALY = "anomaly"      # 异常提醒
    PATTERN = "pattern"      # 模式发现
    CAUSATION = "causation"  # 归因分析


class InsightImportance(str, Enum):
    """洞察重要性枚举"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ChartType(str, Enum):
    """图表类型枚举"""

    LINE = "line"                    # 折线图 - 时间趋势
    BAR = "bar"                      # 柱状图 - 维度对比
    GROUPED_BAR = "grouped_bar"     # 分组柱状图 - 多系列对比
    PIE = "pie"                      # 饼图 - 占比结构
    SCATTER = "scatter"              # 散点图 - 相关性
    RANKING_BAR = "ranking_bar"     # 排名条形图 - TOP N


class ReportBlockType(str, Enum):
    """报告块类型枚举"""

    OVERVIEW = "overview"          # 执行摘要
    FINDINGS = "findings"          # 关键发现
    TREND = "trend"                # 趋势分析
    RANKING = "ranking"            # 排名分析
    RECOMMENDATION = "recommendation"  # 后续建议


class HighlightIcon(str, Enum):
    """亮点图标类型"""

    UP = "up"       # 上升
    DOWN = "down"   # 下降
    INFO = "info"   # 信息


class HighlightColor(str, Enum):
    """亮点颜色类型"""

    GREEN = "green"   # 正向
    RED = "red"      # 负向
    BLUE = "blue"     # 中性


class ExportFormat(str, Enum):
    """导出格式枚举"""

    PDF = "pdf"
    WORD = "word"
    MARKDOWN = "markdown"
    HTML = "html"


# =============================================================================
# 摘要 Schema
# =============================================================================


class Highlight(BaseModel):
    """关键亮点"""

    text: str = Field(description="亮点文本内容")
    icon: HighlightIcon = Field(description="图标类型: up=上升, down=下降, info=信息")
    color: HighlightColor = Field(description="颜色: green=正向, red=负向, blue=中性")
    value: float | None = Field(default=None, description="关联数值（可选）")


class SummaryOutput(BaseModel):
    """摘要输出结构

    字段说明：
    - main_text：主要摘要文本，2-3句话，自然语言描述分析结果
    - key_highlights：关键亮点列表，最多5条，用于前端高亮展示
    - data_summary：数据层面的简要描述，包含具体数值
    - confidence：摘要置信度，0-1之间，越高表示LLM对摘要越有把握
    """

    main_text: str = Field(
        description="主要摘要文本，2-3句话，自然语言描述分析结果"
    )
    key_highlights: list[Highlight] = Field(
        default_factory=list,
        description="关键亮点列表，最多5条，按重要性排序"
    )
    data_summary: str = Field(
        description="数据层面的简要描述，包含具体数值和记录数"
    )
    confidence: float = Field(
        description="摘要置信度 0-1，越高表示LLM对摘要越有把握"
    )
    generated_at: str = Field(
        default_factory=lambda: "",
        description="生成时间 ISO 格式"
    )

    class Config:
        """Pydantic 配置"""

        json_schema_extra = {
            "example": {
                "main_text": "2024年3月，新疆区域发电量达到1.23亿千瓦时，同比增长12.2%，表现优于去年同期。",
                "key_highlights": [
                    {"text": "同比增长12.2%", "icon": "up", "color": "green", "value": 12.2},
                    {"text": "哈密站领先", "icon": "info", "color": "blue", "value": None},
                    {"text": "创历史新高", "icon": "up", "color": "green", "value": None},
                ],
                "data_summary": "共10行数据，关键值1.23亿千瓦时",
                "confidence": 0.95,
                "generated_at": "2024-03-15T10:30:00Z",
            }
        }


# =============================================================================
# 洞察 Schema
# =============================================================================


class EvidenceData(BaseModel):
    """洞察证据数据

    动态字段，根据洞察类型不同而不同：
    - comparison: current_value, compare_value, delta, change_pct
    - trend: data_points, start_value, end_value, trend_direction
    - ranking: dimension, value, row_count, top_value
    - anomaly: anomaly_count, anomaly_rows, anomaly_rate
    """

    current_value: float | None = Field(default=None, description="当前值")
    compare_value: float | None = Field(default=None, description="对比值")
    delta: float | None = Field(default=None, description="变化量")
    change_pct: float | None = Field(default=None, description="变化百分比")
    data_points: int | None = Field(default=None, description="数据点数量")
    start_value: float | None = Field(default=None, description="起始值")
    end_value: float | None = Field(default=None, description="结束值")
    trend_direction: str | None = Field(default=None, description="趋势方向: up/down/stable")
    dimension: str | None = Field(default=None, description="维度名称")
    row_count: int | None = Field(default=None, description="记录数")
    top_value: float | None = Field(default=None, description="最大值")
    anomaly_count: int | None = Field(default=None, description="异常数量")
    anomaly_rate: float | None = Field(default=None, description="异常比例")
    extra: dict[str, Any] = Field(default_factory=dict, description="额外证据数据")


class InsightCard(BaseModel):
    """洞察卡片结构

    每张卡片代表一个独立的洞察发现：
    - title：卡片标题，简短有力
    - type：洞察类型，用于前端图标和样式选择
    - summary：洞察摘要，自然语言描述
    - evidence：支撑洞察的证据数据
    - importance：重要性，用于排序和样式
    - action_suggestion：建议采取的行动
    """

    id: str = Field(description="唯一标识符，UUID格式")
    title: str = Field(description="洞察卡片标题，简短有力")
    type: InsightType = Field(description="洞察类型: trend/ranking/comparison/anomaly/pattern/causation")
    summary: str = Field(description="洞察摘要，自然语言描述业务意义")
    evidence: EvidenceData = Field(
        default_factory=EvidenceData,
        description="支撑洞察的证据数据"
    )
    importance: InsightImportance = Field(
        description="重要性: high/medium/low，用于排序和样式"
    )
    action_suggestion: str | None = Field(
        default=None,
        description="建议采取的行动或下一步"
    )
    icon: str = Field(
        default="📊",
        description="图标 emoji 或图标名称"
    )

    class Config:
        """Pydantic 配置"""

        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "title": "发电量同比增长",
                "type": "comparison",
                "summary": "当前值1.23亿千瓦时较去年同期1.10亿千瓦时增长12.2%，表现优异。",
                "evidence": {
                    "current_value": 123000000,
                    "compare_value": 110000000,
                    "delta": 13000000,
                    "change_pct": 12.2,
                },
                "importance": "high",
                "action_suggestion": "建议分析增长驱动因素，保持良好势头。",
                "icon": "📈",
            }
        }


class InsightOutput(BaseModel):
    """洞察输出结构

    包含多张洞察卡片和整体分析结论：
    - insights：洞察卡片列表，按重要性排序
    - overall_analysis：整体分析结论，一段综合性的分析文字
    - data_quality_note：数据质量说明（如有异常）
    """

    insights: list[InsightCard] = Field(
        default_factory=list,
        description="洞察卡片列表，按重要性排序"
    )
    overall_analysis: str = Field(
        description="整体分析结论，一段综合性的分析文字"
    )
    data_quality_note: str | None = Field(
        default=None,
        description="数据质量说明，如有异常数据或数据缺失"
    )
    generated_at: str = Field(
        default_factory=lambda: "",
        description="生成时间 ISO 格式"
    )

    class Config:
        """Pydantic 配置"""

        json_schema_extra = {
            "example": {
                "insights": [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "title": "发电量同比增长",
                        "type": "comparison",
                        "summary": "同比增长12.2%，表现优异。",
                        "evidence": {"current_value": 123, "change_pct": 12.2},
                        "importance": "high",
                        "action_suggestion": "建议分析增长驱动因素",
                        "icon": "📈",
                    }
                ],
                "overall_analysis": "整体表现良好，发电量稳步增长，建议持续关注增长态势。",
                "data_quality_note": None,
                "generated_at": "2024-03-15T10:30:00Z",
            }
        }


# =============================================================================
# 图表 Schema
# =============================================================================


class AxisConfig(BaseModel):
    """坐标轴配置"""

    label: str = Field(description="轴标签名称")
    data: list[str] = Field(default_factory=list, description="轴数据列表")
    type: str = Field(default="category", description="轴类型: category/value")


class SeriesConfig(BaseModel):
    """系列配置"""

    name: str = Field(description="系列名称")
    color: str | None = Field(default=None, description="系列颜色")
    line_style: str | None = Field(default=None, description="线条样式")


class ChartDataPoint(BaseModel):
    """图表数据点"""

    x: str | float = Field(description="X轴值")
    y: float = Field(description="Y轴值")
    series: str | None = Field(default=None, description="系列名称（分组柱状图用）")
    label: str | None = Field(default=None, description="数据点标签")


class ChartOutput(BaseModel):
    """图表输出结构

    包含图表元数据和渲染数据：
    - chart_type：推荐的图表类型
    - title：图表标题
    - description：图表描述，解释图表含义
    - x_axis/y_axis：坐标轴配置
    - series：系列配置（多系列用）
    - data：图表数据点列表
    - key_insight：从图表中发现的关键洞察
    """

    chart_type: ChartType = Field(
        description="推荐图表类型: line/bar/grouped_bar/pie/scatter/ranking_bar"
    )
    title: str = Field(description="图表标题")
    description: str = Field(description="图表描述，自然语言解释图表含义")
    x_axis: AxisConfig = Field(
        default_factory=AxisConfig,
        description="X轴配置"
    )
    y_axis: AxisConfig = Field(
        default_factory=AxisConfig,
        description="Y轴配置"
    )
    series: list[SeriesConfig] = Field(
        default_factory=list,
        description="系列配置列表（多系列时使用）"
    )
    data: list[ChartDataPoint] = Field(
        default_factory=list,
        description="图表数据点列表"
    )
    key_insight: str | None = Field(
        default=None,
        description="从图表中发现的关键洞察"
    )
    generated_at: str = Field(
        default_factory=lambda: "",
        description="生成时间 ISO 格式"
    )

    class Config:
        """Pydantic 配置"""

        json_schema_extra = {
            "example": {
                "chart_type": "line",
                "title": "新疆区域发电量月度趋势",
                "description": "折线图展示发电量在各月份的连续变化趋势，便于观察周期性规律和长期走势。",
                "x_axis": {
                    "label": "月份",
                    "data": ["1月", "2月", "3月", "4月", "5月", "6月"],
                    "type": "category",
                },
                "y_axis": {
                    "label": "发电量（亿千瓦时）",
                    "data": [],
                    "type": "value",
                },
                "series": [{"name": "2024年", "color": "#1890ff"}],
                "data": [
                    {"x": "1月", "y": 0.85, "series": "2024年"},
                    {"x": "2月", "y": 0.92, "series": "2024年"},
                    {"x": "3月", "y": 1.23, "series": "2024年"},
                ],
                "key_insight": "3月发电量达峰值，6个月累计增长15%",
                "generated_at": "2024-03-15T10:30:00Z",
            }
        }


# =============================================================================
# 报告 Schema
# =============================================================================


class ReportBlock(BaseModel):
    """报告块结构

    报告由多个块组成，每个块包含：
    - block_type：块类型
    - title：块标题
    - content：块内容，Markdown 格式
    - importance：重要性
    """

    id: str = Field(description="唯一标识符，UUID格式")
    block_type: ReportBlockType = Field(description="块类型: overview/findings/trend/ranking/recommendation")
    title: str = Field(description="块标题")
    content: str = Field(description="块内容，Markdown 格式")
    importance: InsightImportance = Field(
        default=InsightImportance.MEDIUM,
        description="重要性"
    )
    collapsed: bool = Field(
        default=False,
        description="是否默认折叠（长内容块可默认折叠）"
    )
    order: int = Field(
        default=0,
        description="排序顺序，数字越小越靠前"
    )


class ReportOutput(BaseModel):
    """完整报告输出结构

    包含报告的所有块和元数据：
    - blocks：报告块列表
    - executive_summary：执行摘要，一句话核心结论
    - next_steps：后续步骤建议
    - metadata：报告元数据
    """

    blocks: list[ReportBlock] = Field(
        default_factory=list,
        description="报告块列表"
    )
    executive_summary: str = Field(
        description="执行摘要，一句话核心结论"
    )
    next_steps: list[str] = Field(
        default_factory=list,
        description="后续步骤建议列表"
    )
    metadata: ReportMetadata = Field(
        default_factory=ReportMetadata,
        description="报告元数据"
    )

    class Config:
        """Pydantic 配置"""

        json_schema_extra = {
            "example": {
                "blocks": [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440001",
                        "block_type": "overview",
                        "title": "分析概览",
                        "content": "2024年3月，新疆区域发电量达到1.23亿千瓦时，同比增长12.2%，表现优于去年同期。",
                        "importance": "high",
                        "collapsed": False,
                        "order": 1,
                    },
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440002",
                        "block_type": "findings",
                        "title": "关键发现",
                        "content": "1. **同比增长12.2%**：表现优于去年同期\n2. **哈密站领先**：发电量占全区域32%\n3. **异常提醒**：2条零值记录需核查",
                        "importance": "high",
                        "collapsed": False,
                        "order": 2,
                    },
                ],
                "executive_summary": "发电量同比增长12.2%，整体表现良好，建议持续关注增长态势。",
                "next_steps": [
                    "可进一步下钻到区域/电站维度进行深入分析",
                    "建议关注异常值背后的业务原因",
                    "可对比不同指标间的相关性",
                ],
                "metadata": {
                    "generated_at": "2024-03-15T10:30:00Z",
                    "query": "新疆区域2024年3月发电量",
                    "data_points": 10,
                },
            }
        }


# =============================================================================
# 报告元数据和存储
# =============================================================================


class ReportMetadata(BaseModel):
    """报告元数据"""

    generated_at: str = Field(description="生成时间 ISO 格式")
    query: str = Field(description="用户查询原始文本")
    data_points: int = Field(description="数据点数量")
    total_rows: int = Field(default=0, description="总记录数")
    duration_ms: int | None = Field(default=None, description="生成耗时毫秒")
    model: str | None = Field(default=None, description="使用的模型名称")
    model_version: str | None = Field(default=None, description="模型版本")


class ReportStorage(BaseModel):
    """报告存储结构

    用于存储到数据库的报告完整结构：
    - id：报告唯一标识
    - content：报告内容（JSON 序列化）
    - export_files：导出文件路径列表
    - status：报告状态
    """

    id: str = Field(description="报告唯一标识，UUID格式")
    run_id: str = Field(description="关联的运行ID")
    user_id: str | None = Field(default=None, description="用户ID")
    content: ReportOutput = Field(description="报告内容")
    export_status: str = Field(default="pending", description="导出状态: pending/processing/completed/failed")
    export_files: dict[ExportFormat, str] = Field(
        default_factory=dict,
        description="导出文件路径，格式 -> 路径"
    )
    file_size: dict[ExportFormat, int] = Field(
        default_factory=dict,
        description="导出文件大小，格式 -> 字节数"
    )
    created_at: str = Field(description="创建时间 ISO 格式")
    expires_at: str | None = Field(default=None, description="过期时间（用于清理）")


# =============================================================================
# SSE 事件结构
# =============================================================================


class SSEEventType(str, Enum):
    """SSE 事件类型"""

    SUMMARY = "summary"
    INSIGHTS = "insights"
    CHART = "chart"
    REPORT = "report"
    REPORT_READY = "report_ready"
    REPORT_DOWNLOAD = "report_download"
    ERROR = "error"
    COMPLETE = "complete"
    PROGRESS = "progress"


class SSEEvent(BaseModel):
    """SSE 事件结构"""

    event: SSEEventType = Field(description="事件类型")
    data: dict[str, Any] = Field(description="事件数据")
    run_id: str = Field(description="运行ID")
    timestamp: str = Field(
        default_factory=lambda: "",
        description="事件时间 ISO 格式"
    )

    def to_sse_format(self) -> str:
        """转换为 SSE 格式字符串"""
        import json

        return f"event: {self.event.value}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"


class ProgressEvent(BaseModel):
    """进度事件"""

    stage: str = Field(description="当前阶段")
    progress: float = Field(description="进度 0-100")
    message: str = Field(description="进度消息")
    detail: str | None = Field(default=None, description="详细信息")


# =============================================================================
# 便捷类型别名
# =============================================================================


# 四个产物的统一输出类型
ContentGenerationResult = dict[str, SummaryOutput | InsightOutput | ChartOutput | ReportOutput]

# SSE 推送事件列表
SSEEventList = list[SSEEvent]

# 导出请求
ExportRequest = dict[ExportFormat, bool]

# 导出响应
ExportResponse = dict[ExportFormat, str | None]
