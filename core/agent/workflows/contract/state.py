"""合同审查 Agent 工作流状态定义。

基于 ReAct (Reasoning + Acting) 模式的智能合同审查 Agent。

核心设计理念：
1. ReAct 模式：思考 → 规划 → 执行 → 观察 → 反思
2. Tool Use：Agent 可动态选择工具
3. RAG 增强：检索相关法规、标准模板、历史案例
4. 反思机制：对风险点进行二次校验
5. Human Review：支持高风险项人工复核
6. 多轮对话：支持追问和澄清

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict, Union

from pydantic import BaseModel, Field


# ==================== ReAct 模式枚举 ====================


class AgentThought(str, Enum):
    """Agent 思考状态。"""

    IDLE = "idle"  # 空闲
    THINKING = "thinking"  # 思考中
    PLANNING = "planning"  # 规划中
    ACTING = "acting"  # 执行中
    OBSERVING = "observing"  # 观察中
    REFLECTING = "reflecting"  # 反思中
    WAITING_REVIEW = "waiting_review"  # 等待人工复核
    WAITING_CLARIFICATION = "waiting_clarification"  # 等待澄清
    FINISHED = "finished"  # 完成


class AgentAction(str, Enum):
    """Agent 可执行的动作。"""

    # 文档处理
    PARSE_CONTRACT = "parse_contract"  # 解析合同
    EXTRACT_CLAUSES = "extract_clauses"  # 抽取条款

    # RAG 增强
    SEARCH_LAWS = "search_laws"  # 检索法规
    SEARCH_TEMPLATES = "search_templates"  # 检索标准模板
    SEARCH_HISTORY = "search_history"  # 检索历史案例

    # 分析
    ANALYZE_RISK = "analyze_risk"  # 分析风险
    COMPARE_TEMPLATE = "compare_template"  # 对比模板
    IDENTIFY_MISSING = "identify_missing"  # 识别缺失条款

    # 生成
    GENERATE_REPORT = "generate_report"  # 生成报告
    GENERATE_SUGGESTION = "generate_suggestion"  # 生成建议

    # 特殊动作
    ASK_CLARIFICATION = "ask_clarification"  # 请求澄清
    REQUEST_HUMAN_REVIEW = "request_human_review"  # 请求人工复核
    REACT_TO_FEEDBACK = "react_to_feedback"  # 对反馈做出反应


class ContractWorkflowStage(str, Enum):
    """合同审查 Agent 的执行阶段。"""

    # 入口阶段
    ENTRY = "entry"  # 入口验证

    # ReAct 循环阶段（重构后统一为一个循环节点）
    REACT_LOOP = "react_loop"  # ReAct 执行循环

    # 单独阶段（保留兼容性）
    THINK = "think"  # 思考（兼容旧版）
    PLAN = "plan"  # 规划（兼容旧版）
    ACT = "act"  # 执行（兼容旧版）
    OBSERVE = "observe"  # 观察（兼容旧版）
    REFLECT = "reflect"  # 反思

    # 特殊阶段
    CLARIFICATION = "clarification"  # 澄清
    HUMAN_REVIEW = "human_review"  # 人工复核
    GENERATE_REPORT = "generate_report"  # 生成报告

    # 结束阶段
    FINISH = "finish"  # 完成


class ContractWorkflowOutcome(str, Enum):
    """合同审查 Agent 的结果方向。"""

    CONTINUE = "continue"  # 继续执行
    CLARIFY = "clarify"  # 需要澄清
    REVIEW = "review"  # 需要人工审核
    FINISH = "finish"  # 完成
    FAIL = "fail"  # 失败


# ==================== Pydantic 数据模型 ====================


class ReviewContext(BaseModel):
    """审查上下文。

    用于在 ReAct 循环中传递审查上下文。
    """

    # 当前焦点
    current_focus: str = Field(description="当前审查焦点")

    # 已有发现
    findings: list[str] = Field(default_factory=list, description="已有发现")

    # 待验证假设
    hypotheses: list[str] = Field(default_factory=list, description="待验证假设")

    # 已检索的 RAG 上下文
    rag_contexts: dict[str, list[str]] = Field(
        default_factory=dict,
        description="RAG 上下文，key 为检索类型"
    )

    # 识别到的风险
    identified_risks: list[dict] = Field(default_factory=list, description="已识别风险")

    # 缺失条款
    missing_clauses: list[str] = Field(default_factory=list, description="缺失条款")


class ThoughtRecord(BaseModel):
    """思考记录。

    记录 Agent 的推理过程，用于可解释性和审计。
    """

    thought_id: str = Field(description="思考记录 ID")
    timestamp: datetime = Field(default_factory=datetime.now, description="思考时间")

    # 思考内容
    thinking: str = Field(description="当前思考内容")
    reasoning: str = Field(description="推理过程")

    # 决策
    action: str = Field(description="决定执行的动作")
    action_input: dict[str, Any] = Field(description="动作输入参数")
    reasoning_for_action: str = Field(description="选择该动作的原因")

    # 观察结果
    observation: str = Field(default="", description="动作执行后的观察结果")
    observation_summary: str = Field(default="", description="观察结果摘要")

    # 反思
    reflection: str = Field(default="", description="反思内容")
    is_correct: Optional[bool] = Field(default=None, description="判断是否正确")


class ContractWorkflowState(TypedDict, total=False):
    """合同审查 Agent 完整工作流状态。

    采用 ReAct 模式，支持多轮思考-执行-观察循环。
    """

    # ==================== 链路标识 ====================
    run_id: str
    trace_id: str
    conversation_id: Optional[str]
    user_id: str
    user_role: str

    # ==================== 输入参数 ====================
    contract_file_id: str
    storage_uri: Optional[str]  # MinIO 对象路径
    contract_name: str
    contract_type: Optional[str]
    business_domain: Optional[str]
    query: Optional[str]  # 用户原始问题

    # ==================== 文档解析结果 ====================
    parsed_content: str  # 解析后的合同文本
    document_blocks: List[dict]  # 文档块列表
    file_size: Optional[int]  # 文件大小

    # ==================== 条款分析结果 ====================
    extracted_clauses: List[dict]  # 抽取的条款
    parties: List[dict]  # 当事人信息
    metadata: dict  # 合同元数据

    # 新增：LLM 增强提取结果（用于 search_laws 多路检索）
    legal_search_topics: List[str]  # LLM 提取的法律检索主题
    contract_legal_issues: List[str]  # 合同涉及的法律问题

    # ==================== RAG 增强结果 ====================
    retrieved_laws: List[dict]  # 检索到的相关法规
    retrieved_templates: List[dict]  # 检索到的标准模板
    retrieved_history: List[dict]  # 检索到的历史案例

    # ==================== 风险分析结果 ====================
    identified_risks: List[dict]  # 识别的风险
    risk_summary: str  # 风险概要
    high_risk_count: int  # 高风险数量
    medium_risk_count: int  # 中风险数量
    low_risk_count: int  # 低风险数量

    # ==================== 报告结果 ====================
    review_report: Optional[dict]  # 审查报告
    conclusion: str  # 审查结论
    suggestions: List[str]  # 修改建议
    key_concerns: List[str]  # 重点关注项

    # ==================== ReAct 状态 ====================
    agent_status: str  # Agent 思考状态
    current_stage: str  # 当前工作流阶段
    outcome: str  # 工作流结果

    # ReAct 核心字段
    thoughts: List[dict]  # 思考记录列表
    current_plan: List[str]  # 当前执行计划
    pending_actions: List[str]  # 待执行动作队列
    completed_actions: List[str]  # 已完成动作列表
    review_context: dict  # 审查上下文

    # ReAct 新增字段
    completed_tools: List[str]  # 已完成的工具列表
    react_iterations: int  # ReAct 迭代次数
    reflection_result: Optional[dict]  # 反思结果
    overall_risk_level: Optional[str]  # 整体风险等级

    # ==================== Human Review 状态 ====================
    need_human_review: bool
    human_review_id: Optional[str]
    human_review_status: Optional[str]  # pending / completed / cancelled
    human_review_decision: Optional[str]  # approved / rejected / revised
    human_review_comments: Optional[str]  # 复核意见
    reviewer_id: Optional[str]  # 复核人ID
    reviewer_name: Optional[str]  # 复核人姓名
    pending_risks: List[dict]  # 待复核的风险项

    # ==================== Clarification 状态 ====================
    clarification_question: Optional[str]
    clarification_needed: bool

    # ==================== 元数据 ====================
    error: Optional[str]
    processing_time_ms: Optional[int]
    max_react_iterations: int  # 最大 ReAct 迭代次数


def create_initial_contract_state(
    run_id: str,
    contract_file_id: str,
    user_id: str,
    user_role: str = "user",
    contract_name: Optional[str] = None,
    contract_type: Optional[str] = None,
    business_domain: Optional[str] = None,
    query: Optional[str] = None,
    storage_uri: Optional[str] = None,
    trace_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> ContractWorkflowState:
    """创建初始合同审查工作流状态。

    Args:
        run_id: 唯一运行 ID
        contract_file_id: 合同文件 ID
        user_id: 用户 ID
        user_role: 用户角色
        contract_name: 合同名称
        contract_type: 合同类型
        business_domain: 业务域
        query: 用户原始问题
        storage_uri: MinIO 对象路径
        trace_id: 追踪 ID
        conversation_id: 会话 ID

    Returns:
        初始化的状态字典
    """

    return ContractWorkflowState(
        # 链路标识
        run_id=run_id,
        trace_id=trace_id or run_id,
        conversation_id=conversation_id,
        user_id=user_id,
        user_role=user_role,

        # 输入参数
        contract_file_id=contract_file_id,
        storage_uri=storage_uri,
        contract_name=contract_name or "未命名合同",
        contract_type=contract_type,
        business_domain=business_domain or "能源",
        query=query,

        # 文档解析结果
        parsed_content="",
        document_blocks=[],
        file_size=None,

        # 条款分析结果
        extracted_clauses=[],
        parties=[],
        metadata={},

        # 新增：LLM 增强提取结果
        legal_search_topics=[],  # LLM 提取的法律检索主题
        contract_legal_issues=[],  # 合同涉及的法律问题

        # RAG 增强结果
        retrieved_laws=[],
        retrieved_templates=[],
        retrieved_history=[],

        # 风险分析结果
        identified_risks=[],
        risk_summary="",
        high_risk_count=0,
        medium_risk_count=0,
        low_risk_count=0,

        # 报告结果
        review_report=None,
        conclusion="",
        suggestions=[],
        key_concerns=[],

        # ReAct 状态
        agent_status=AgentThought.IDLE.value,
        current_stage=ContractWorkflowStage.ENTRY.value,
        outcome=ContractWorkflowOutcome.CONTINUE.value,

        # ReAct 核心字段
        thoughts=[],
        current_plan=[],
        pending_actions=[],
        completed_actions=[],
        completed_tools=[],
        react_iterations=0,
        reflection_result=None,
        overall_risk_level=None,
        review_context=ReviewContext(
            current_focus="合同基本信息",
            findings=[],
            hypotheses=[],
            rag_contexts={},
            identified_risks=[],
            missing_clauses=[],
        ).model_dump(),

        # Human Review 状态
        need_human_review=False,
        human_review_id=None,
        human_review_status=None,
        pending_risks=[],

        # Clarification 状态
        clarification_question=None,
        clarification_needed=False,

        # 元数据
        error=None,
        processing_time_ms=None,
        max_react_iterations=10,
    )
