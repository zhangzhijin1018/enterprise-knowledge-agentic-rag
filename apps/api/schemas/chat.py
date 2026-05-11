"""智能问答接口 Schema。"""

from pydantic import BaseModel, Field


class HistoryMessageInput(BaseModel):
    """历史消息输入模型。

    当前阶段允许前端传最近几轮历史消息，
    但真正的会话可信来源仍应是服务端持久化记录。
    该字段主要用于：
    - 前端首版联调；
    - 后续对比“前端携带历史”和“服务端会话回放”的差异；
    - 预留跨端恢复会话的输入契约。
    """

    # 消息角色，例如 user 或 assistant。
    role: str = Field(description="消息角色")

    # 消息原文内容。
    content: str = Field(description="消息内容")


class ChatRequest(BaseModel):
    """提交问答请求的最小输入模型。"""

    # 用户问题原文。
    query: str = Field(description="用户问题")

    # 多轮对话时传已有会话 ID；首轮会话可为空，由服务端自动创建。
    conversation_id: str | None = Field(default=None, description="会话 ID")

    # 前端可选传最近历史消息，服务端仍以持久化会话为准。
    history_messages: list[HistoryMessageInput] = Field(
        default_factory=list,
        description="最近历史消息",
    )

    # 业务提示，例如 policy、safety、analytics。
    business_hint: str | None = Field(default=None, description="业务提示")

    # 限制候选知识库范围。当前最小骨架仅保留字段，不实际参与检索。
    knowledge_base_ids: list[str] = Field(default_factory=list, description="候选知识库 ID 列表")

    # 是否流式返回。当前最小骨架统一按非流式处理。
    stream: bool = Field(default=False, description="是否流式返回")

    # =========================================================================
    # 合同审查相关参数
    # =========================================================================

    # 合同文件 ID（用于合同审查场景）
    # 如果提供此参数，系统将执行合同审查流程
    contract_file_id: str | None = Field(
        default=None,
        description="合同文件 ID，从 /api/v1/contracts/upload 获取"
    )

    # 合同名称（可选，如果 contract_file_id 存在则可省略）
    contract_name: str | None = Field(
        default=None,
        description="合同名称"
    )

    # 合同类型（可选）
    contract_type: str | None = Field(
        default=None,
        description="合同类型（采购合同/销售合同/劳动合同等）"
    )


class CitationItem(BaseModel):
    """引用信息模型。

    当前阶段返回 mock citation，
    主要是为了从第一天起就把“答案必须可溯源”的接口格式定下来。
    """

    # 文档 ID。
    document_id: str = Field(description="文档 ID")

    # 文档标题。
    document_title: str = Field(description="文档标题")

    # 切片 ID。
    chunk_id: str = Field(description="切片 ID")

    # 页码。
    page_no: int = Field(description="页码")

    # 摘录片段。
    snippet: str = Field(description="引用片段")


# =============================================================================
# 统一结果格式（用于 SSE complete 事件）
# =============================================================================

class ResultMetadata(BaseModel):
    """结果元数据。"""
    # 引用列表
    citations: list[CitationItem] = Field(default_factory=list, description="引用列表")


class AnalyticsResult(BaseModel):
    """经营分析结果。"""
    summary: str = Field(description="分析摘要")
    insight_cards: list[dict] = Field(default_factory=list, description="洞察卡片")
    chart_spec: dict | None = Field(default=None, description="图表配置")
    tables: list[dict] = Field(default_factory=list, description="数据表格")
    sql_preview: str | None = Field(default=None, description="SQL 预览")
    row_count: int | None = Field(default=None, description="返回行数")


class ContractRiskItem(BaseModel):
    """合同风险项。"""
    clause: str = Field(description="相关条款")
    risk_type: str = Field(description="风险类型")
    risk_level: str = Field(description="风险等级（low/medium/high/critical）")
    description: str = Field(description="风险描述")
    suggestion: str = Field(description="修改建议")


class ContractParty(BaseModel):
    """合同当事人。"""
    name: str = Field(description="当事人名称")
    role: str = Field(description="角色（甲方/乙方）")


class ContractResult(BaseModel):
    """合同审查结果。"""
    contract_name: str = Field(description="合同名称")
    contract_type: str = Field(description="合同类型")
    overall_risk_level: str = Field(description="整体风险等级")
    risk_summary: str = Field(description="风险摘要")
    risk_items: list[ContractRiskItem] = Field(default_factory=list, description="风险列表")
    parties: list[ContractParty] = Field(default_factory=list, description="合同当事人")
    need_human_review: bool = Field(description="是否需要人工审核")


class ClarificationData(BaseModel):
    """澄清数据。"""
    question: str = Field(description="澄清问题")
    slots: dict = Field(default_factory=dict, description="缺失的槽位")


class UnifiedResult(BaseModel):
    """统一的结果格式。

    用于 SSE complete 事件和 HTTP 响应。

    设计说明：
    - result_type 标识结果类型，前端据此渲染不同组件
    - 各类型结果使用独立字段，未使用的为 null
    - 保持向前兼容，新增结果类型只需添加新字段
    """

    # 结果类型
    result_type: str = Field(
        description="结果类型（rag/analytics/contract/clarification）",
    )

    # 通用状态
    status: str = Field(description="状态（succeeded/failed/clarification）")

    # RAG 结果
    answer: str | None = Field(default=None, description="RAG 回答")
    citations: list[CitationItem] = Field(default_factory=list, description="引用列表")

    # 经营分析结果
    analytics: AnalyticsResult | None = Field(default=None, description="经营分析结果")

    # 合同审查结果
    contract: ContractResult | None = Field(default=None, description="合同审查结果")

    # 澄清数据
    clarification: ClarificationData | None = Field(default=None, description="澄清数据")

    @classmethod
    def from_rag(cls, answer: str, citations: list[CitationItem] | None = None) -> "UnifiedResult":
        """从 RAG 结果创建统一格式。"""
        return cls(
            result_type="rag",
            status="succeeded",
            answer=answer,
            citations=citations or [],
        )

    @classmethod
    def from_analytics(cls, analytics_result: AnalyticsResult) -> "UnifiedResult":
        """从经营分析结果创建统一格式。"""
        return cls(
            result_type="analytics",
            status="succeeded",
            analytics=analytics_result,
        )

    @classmethod
    def from_contract(cls, contract_result: ContractResult) -> "UnifiedResult":
        """从合同审查结果创建统一格式。"""
        return cls(
            result_type="contract",
            status="succeeded",
            contract=contract_result,
        )

    @classmethod
    def from_clarification(cls, clarification: ClarificationData) -> "UnifiedResult":
        """从澄清数据创建统一格式。"""
        return cls(
            result_type="clarification",
            status="clarification",
            clarification=clarification,
        )
