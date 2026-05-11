"""合同审查 Agent 节点集合（重构版）。

基于 LangChain ReAct 模式的智能合同审查 Agent。
集成了新的 tools.py 和 reflection.py 模块。

核心设计：
1. 使用 LangChain @tool 装饰器定义工具
2. 使用 LLM 驱动的反思机制
3. 支持 Human Review 门控
4. 支持多轮对话

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from core.agent.workflows.contract.state import (
    AgentAction,
    AgentThought,
    ContractWorkflowState,
    ContractWorkflowStage,
    ContractWorkflowOutcome,
    ThoughtRecord,
)
from core.agent.workflows.contract.tools import (
    get_contract_tools,
    get_tool_by_name,
    parse_contract,
    search_laws,
    search_templates,
    search_history,
    extract_clauses,
    analyze_risk,
    generate_report,
    request_human_review,
)
from core.agent.workflows.contract.reflection import (
    ReflectionEngine,
    SimpleReflection,
    ReflectionResult,
)
from core.llm.gateway import LLMGateway, MockLLMGateway
from core.config.settings import get_settings

logger = logging.getLogger(__name__)


class ContractWorkflowNodes:
    """合同审查 Agent 工作流节点集合。

集成 LangChain Tools 和 LLM 驱动的反思机制。

节点职责：
1. entry: 入口验证
2. react_loop: ReAct 执行循环（解析→检索→抽取→分析）
3. reflect: 反思校验
4. human_review: 人工复核
5. generate_report: 生成报告
6. finish: 结束
"""

    def __init__(
        self,
        parser: Any = None,
        llm_gateway: Optional[LLMGateway] = None,
        use_reflection: bool = True,
    ) -> None:
        """初始化合同审查工作流节点。

        Args:
            parser: 文档解析器（可选，默认使用 LocalDocumentParser）
            llm_gateway: LLM 网关（可选，默认使用 Mock）
            use_reflection: 是否启用反思机制
        """
        # 初始化解析器
        if parser is None:
            from core.tools.local.parser import LocalDocumentParser
            self.parser = LocalDocumentParser()
        else:
            self.parser = parser

        # 初始化 LLM 网关
        self._llm_gateway = llm_gateway
        self._use_reflection = use_reflection

        # 初始化反思引擎（懒加载）
        self._reflection_engine: Optional[ReflectionEngine] = None

        # 获取工具列表
        self.tools = get_contract_tools()
        self.tool_map = {tool.name: tool for tool in self.tools}

        logger.info(
            f"ContractWorkflowNodes 初始化完成 | "
            f"tools={len(self.tools)} | use_reflection={use_reflection}"
        )

    @property
    def llm_gateway(self) -> LLMGateway:
        """获取 LLM 网关（懒加载）。"""
        if self._llm_gateway is None:
            settings = get_settings()
            if settings.llm_api_key and settings.llm_api_key != "your-api-key":
                from core.llm.gateway import OpenAICompatibleLLMGateway
                self._llm_gateway = OpenAICompatibleLLMGateway(settings=settings)
            else:
                self._llm_gateway = MockLLMGateway()
        return self._llm_gateway

    @property
    def reflection_engine(self) -> ReflectionEngine:
        """获取反思引擎（懒加载）。"""
        if self._reflection_engine is None and self._use_reflection:
            self._reflection_engine = ReflectionEngine(llm=self.llm_gateway)
        return self._reflection_engine

    # ==================== 节点定义 ====================

    async def entry(self, state: ContractWorkflowState) -> dict:
        """入口节点：验证输入参数。

        职责：
        - 验证必需参数
        - 初始化 ReAct 状态
        - 记录开始时间
        """
        run_id = state["run_id"]
        contract_file_id = state["contract_file_id"]

        logger.info(
            f"[{run_id}] 合同审查开始 | contract_file_id={contract_file_id}"
        )

        # 验证必需参数：缺参数时进入澄清机制，而非直接失败
        if not contract_file_id:
            logger.warning(f"[{run_id}] 缺少合同文件 ID，触发澄清机制")
            return {
                "current_stage": ContractWorkflowStage.CLARIFICATION.value,
                "outcome": ContractWorkflowOutcome.CLARIFY.value,
                "clarification_needed": True,
                "clarification_question": "请上传需要审查的合同文件。合同审查需要有效的合同文档才能进行分析。",
                "agent_status": AgentThought.WAITING_CLARIFICATION.value,
                "error": None,  # 清除之前的错误
            }

        # 初始化 ReAct 状态
        return {
            "current_stage": ContractWorkflowStage.REACT_LOOP.value,
            "agent_status": AgentThought.THINKING.value,
            "outcome": ContractWorkflowOutcome.CONTINUE.value,
            "completed_tools": [],
            "react_iterations": 0,
        }

    # ==================== ReAct 循环节点 ====================

    async def react_loop(self, state: ContractWorkflowState) -> dict:
        """ReAct 执行循环节点。

        核心职责：
        - 使用 LangChain Tools 执行合同审查
        - 追踪已完成步骤
        - 决定是否继续循环

        执行流程（基于状态决定下一步）：
        1. 如果还没解析合同 → parse_contract
        2. 如果还没检索法规 → search_laws
        3. 如果还没检索模板 → search_templates
        4. 如果还没抽取条款 → extract_clauses
        5. 如果还没分析风险 → analyze_risk
        6. 所有步骤完成 → 进入反思或报告
        """
        run_id = state["run_id"]
        completed_tools = state.get("completed_tools", [])
        react_iterations = state.get("react_iterations", 0)
        max_iterations = state.get("max_react_iterations", 10)

        logger.info(
            f"[{run_id}] ReAct 循环 | 迭代={react_iterations} | "
            f"已完成={completed_tools}"
        )

        # 检查迭代次数
        if react_iterations >= max_iterations:
            logger.warning(f"[{run_id}] 达到最大迭代次数 {max_iterations}，强制结束")
            return {
                "current_stage": ContractWorkflowStage.GENERATE_REPORT.value,
                "outcome": ContractWorkflowOutcome.CONTINUE.value,
            }

        # 确定下一步工具
        next_tool = self._decide_next_tool(completed_tools, state)

        if next_tool is None:
            # 所有工具都执行完成，进入反思
            logger.info(f"[{run_id}] ReAct 循环完成，进入反思")
            return {
                "current_stage": ContractWorkflowStage.REFLECT.value,
                "outcome": ContractWorkflowOutcome.CONTINUE.value,
            }

        # 执行工具
        tool = self.tool_map.get(next_tool)
        if tool is None:
            logger.error(f"[{run_id}] 工具不存在: {next_tool}")
            return {
                "current_stage": ContractWorkflowStage.REFLECT.value,
                "outcome": ContractWorkflowOutcome.CONTINUE.value,
            }

        # 准备工具输入
        tool_input = self._prepare_tool_input(next_tool, state)

        logger.info(f"[{run_id}] 执行工具: {next_tool}")

        try:
            # 执行工具
            result = await tool.ainvoke(tool_input)

            # 更新已完成工具列表
            new_completed = completed_tools + [next_tool]

            # 根据工具结果更新状态
            state_updates = self._update_state_from_result(next_tool, result, state)
            state_updates.update({
                "current_stage": ContractWorkflowStage.REACT_LOOP.value,
                "agent_status": AgentThought.THINKING.value,
                "completed_tools": new_completed,
                "react_iterations": react_iterations + 1,
            })

            logger.info(
                f"[{run_id}] 工具 {next_tool} 执行完成 | "
                f"结果状态: {result.get('status')}"
            )

            return state_updates

        except Exception as e:
            logger.error(f"[{run_id}] 工具执行失败: {next_tool} | 错误: {e}", exc_info=True)
            return {
                "current_stage": ContractWorkflowStage.REFLECT.value,
                "agent_status": AgentThought.FINISHED.value,
                "outcome": ContractWorkflowOutcome.CONTINUE.value,
                "error": f"工具执行失败: {str(e)}",
            }

    def _decide_next_tool(self, completed_tools: list[str], state: dict) -> Optional[str]:
        """决定下一步执行哪个工具。

        使用规则 + LLM 混合决策：
        1. 规则决定优先级
        2. LLM 可选介入做复杂决策

        工具执行顺序优化说明：
        - parse_contract 必须最先执行
        - extract_clauses 在 search_laws 之前执行（用户提出的优化）
          原因：extract_clauses 会调用 LLM 提取法律检索主题，
          这些主题可以传递给 search_laws 进行更精准的多路检索
        """
        # 工具执行顺序（基于依赖关系）
        # 优化：extract_clauses 在 search_laws 之前，因为 extract_clauses 会提取
        # legal_search_topics 供 search_laws 使用，实现更精准的法规检索
        tool_order = [
            "parse_contract",  # 必须最先执行
            "extract_clauses",  # LLM 抽取条款主题（在 search_laws 之前）
            "search_laws",  # 检索法规（可使用 extract_clauses 的结果）
            "search_templates",  # 检索模板
            "search_history",  # 检索历史案例（为风险分析提供参考）
            "analyze_risk",  # 分析风险（可参考历史案例的处理结果）
        ]

        # 找到第一个未完成的工具
        for tool in tool_order:
            if tool not in completed_tools:
                return tool

        return None  # 所有工具都已完成

    def _prepare_tool_input(self, tool_name: str, state: dict) -> dict:
        """准备工具输入参数。

        优化说明：
        - search_laws 现在可以接收 extracted_clauses 的结果（legal_search_topics）
        - search_laws 可以接收合同全文（parsed_content）
        - 这样可以实现基于合同内容的精准多路检索
        """
        if tool_name == "parse_contract":
            return {
                "contract_file_id": state.get("contract_file_id"),
                "storage_uri": state.get("storage_uri"),
            }

        elif tool_name == "search_laws":
            # 从 state 中获取 extract_clauses 的结果
            extracted_clauses = state.get("extracted_clauses", [])
            parsed_content = state.get("parsed_content", "")

            # 获取 LLM 提取的法律检索主题（由 extract_clauses 填充）
            legal_search_topics = state.get("legal_search_topics")

            return {
                "query": state.get("query", state.get("contract_name", "")),
                "contract_type": state.get("contract_type"),
                "business_domain": state.get("business_domain", "能源"),
                "top_k": 5,
                # 传递 extract_clauses 的结果
                "extracted_clauses": extracted_clauses if extracted_clauses else None,
                "contract_content": parsed_content if parsed_content else None,
                # 传递 LLM 提取的法律检索主题（用于多路检索）
                "legal_search_topics": legal_search_topics if legal_search_topics else None,
            }

        elif tool_name == "search_templates":
            return {
                "contract_type": state.get("contract_type"),
                "business_domain": state.get("business_domain", "能源"),
                "top_k": 3,
            }

        elif tool_name == "search_history":
            # 检索历史案例，为风险分析提供参考
            # 使用合同名称和类型作为检索 query
            query = state.get("contract_name", "") or state.get("query", "")
            return {
                "query": query,
                "contract_type": state.get("contract_type"),
                "risk_level": None,  # 不过滤风险等级，获取所有参考案例
                "top_k": 3,  # 最多返回3个历史案例
            }

        elif tool_name == "extract_clauses":
            return {
                "contract_text": state.get("parsed_content", ""),
                "contract_type": state.get("contract_type"),
            }

        elif tool_name == "analyze_risk":
            return {
                "clauses": state.get("extracted_clauses", []),
                "contract_type": state.get("contract_type"),
                "laws_context": state.get("retrieved_laws", []),
                "templates_context": state.get("retrieved_templates", []),
                "history_context": state.get("retrieved_history", []),  # 新增：历史案例上下文
            }

        return {}

    def _update_state_from_result(self, tool_name: str, result: dict, state: dict) -> dict:
        """根据工具执行结果更新状态。"""
        updates = {}

        if tool_name == "parse_contract":
            if result.get("status") == "success":
                updates["parsed_content"] = result.get("text", "")
                updates["document_blocks"] = result.get("blocks", [])
                updates["file_size"] = result.get("metadata", {}).get("text_length", 0)

        elif tool_name == "search_laws":
            if result.get("status") == "success":
                updates["retrieved_laws"] = result.get("laws", [])

        elif tool_name == "search_templates":
            if result.get("status") == "success":
                updates["retrieved_templates"] = result.get("templates", [])

        elif tool_name == "search_history":
            if result.get("status") == "success":
                updates["retrieved_history"] = result.get("history", [])

        elif tool_name == "extract_clauses":
            if result.get("status") == "success":
                updates["extracted_clauses"] = result.get("clauses", [])
                updates["parties"] = result.get("parties", [])
                updates["missing_clauses"] = result.get("missing_clauses", [])
                # 新增：保存 LLM 提取的法律检索主题，供 search_laws 使用
                updates["legal_search_topics"] = result.get("legal_search_topics", [])
                updates["contract_legal_issues"] = result.get("contract_legal_issues", [])

        elif tool_name == "analyze_risk":
            if result.get("status") == "success":
                updates["identified_risks"] = result.get("risks", [])
                updates["risk_summary"] = result.get("risk_summary", "")
                updates["overall_risk_level"] = result.get("overall_level", "unknown")
                updates["need_human_review"] = result.get("need_human_review", False)
                updates["high_risk_count"] = result.get("high_risk_count", 0)
                updates["medium_risk_count"] = result.get("medium_risk_count", 0)

        return updates

    # ==================== 反思节点 ====================

    async def reflect(self, state: ContractWorkflowState) -> dict:
        """反思节点：对审查结果进行二次校验。

        核心职责：
        - 使用 LLM 反思审查质量
        - 检查是否有遗漏
        - 决定是否需要 Human Review
        """
        run_id = state["run_id"]

        logger.info(f"[{run_id}] 执行反思校验...")

        # 获取审查结果
        contract_name = state.get("contract_name", "未知合同")
        contract_type = state.get("contract_type")
        business_domain = state.get("business_domain", "能源")
        clauses = state.get("extracted_clauses", [])
        risks = state.get("identified_risks", [])
        conclusion = state.get("risk_summary", "")

        # 检查是否需要反思
        if not self._use_reflection or self.reflection_engine is None:
            # 不使用反思，直接进入报告
            return self._decide_next_after_reflect(state, None)

        try:
            # 执行反思
            reflection = await self.reflection_engine.reflect(
                contract_name=contract_name,
                contract_type=contract_type,
                business_domain=business_domain,
                clauses=clauses,
                risks=risks,
                conclusion=conclusion,
                laws_context=state.get("retrieved_laws", []),
                templates_context=state.get("retrieved_templates", []),
            )

            logger.info(
                f"[{run_id}] 反思完成 | status={reflection.status} | "
                f"confidence={reflection.confidence} | "
                f"issues={len(reflection.issues)}"
            )

            # 根据反思结果决定下一步
            return self._decide_next_after_reflect(state, reflection)

        except Exception as e:
            logger.error(f"[{run_id}] 反思执行失败: {e}", exc_info=True)
            # 使用简化反思
            simple_reflection = SimpleReflection.reflect(
                clauses=clauses,
                risks=risks,
                conclusion=conclusion,
            )
            return self._decide_next_after_reflect(state, simple_reflection)

    def _decide_next_after_reflect(
        self,
        state: dict,
        reflection: Optional[ReflectionResult],
    ) -> dict:
        """根据反思结果决定下一步。"""
        # 检查是否需要人工复核
        if reflection and reflection.needs_human_review:
            logger.info("反思决定：需要人工复核")
            return {
                "current_stage": ContractWorkflowStage.HUMAN_REVIEW.value,
                "agent_status": AgentThought.WAITING_REVIEW.value,
                "outcome": ContractWorkflowOutcome.REVIEW.value,
                "reflection_result": reflection.to_dict() if reflection else None,
            }

        # 检查状态中的 need_human_review 标志
        if state.get("need_human_review"):
            return {
                "current_stage": ContractWorkflowStage.HUMAN_REVIEW.value,
                "agent_status": AgentThought.WAITING_REVIEW.value,
                "outcome": ContractWorkflowOutcome.REVIEW.value,
                "reflection_result": reflection.to_dict() if reflection else None,
            }

        # 直接生成报告
        return {
            "current_stage": ContractWorkflowStage.GENERATE_REPORT.value,
            "agent_status": AgentThought.FINISHED.value,
            "outcome": ContractWorkflowOutcome.CONTINUE.value,
            "reflection_result": reflection.to_dict() if reflection else None,
        }

    # ==================== Human Review 节点 ====================

    async def human_review(self, state: ContractWorkflowState) -> dict:
        """Human Review 节点：创建人工复核任务。

        职责：
        - 为高风险项创建人工复核任务
        - 保存 checkpoint 以便后续恢复
        - 设置等待状态，不阻塞线程

        注意：此节点执行后工作流暂停，等待用户点击"生成报告"按钮恢复
        """
        run_id = state["run_id"]
        identified_risks = state.get("identified_risks", [])
        high_risks = [r for r in identified_risks if r.get("risk_type") == "high"]

        logger.info(
            f"[{run_id}] Human Review | 高风险项: {len(high_risks)}"
        )

        try:
            # 调用 request_human_review 工具
            tool = self.tool_map.get("request_human_review")
            if tool:
                result = await tool.ainvoke({
                    "high_risk_items": high_risks,
                    "reason": f"发现 {len(high_risks)} 个高风险项，需要人工复核",
                })

                review_id = result.get("review_id")

                # 创建复核任务后的状态更新
                node_result = {
                    "current_stage": ContractWorkflowStage.HUMAN_REVIEW.value,
                    "agent_status": AgentThought.WAITING_REVIEW.value,
                    "need_human_review": True,
                    "human_review_id": review_id,
                    "human_review_status": "pending",
                    "pending_risks": high_risks,
                    "outcome": ContractWorkflowOutcome.REVIEW.value,
                }

                # 保存 checkpoint（用于后续恢复）
                self._save_review_checkpoint(state, node_result)

                return node_result

        except Exception as e:
            logger.error(f"[{run_id}] 创建复核任务失败: {e}", exc_info=True)

        # 备用方案
        node_result = {
            "current_stage": ContractWorkflowStage.HUMAN_REVIEW.value,
            "agent_status": AgentThought.WAITING_REVIEW.value,
            "need_human_review": True,
            "human_review_id": f"review_{run_id}",
            "human_review_status": "pending",
            "pending_risks": high_risks,
            "outcome": ContractWorkflowOutcome.REVIEW.value,
        }

        # 保存 checkpoint
        self._save_review_checkpoint(state, node_result)

        return node_result

    def _save_review_checkpoint(self, state: dict, node_result: dict) -> None:
        """保存 Human Review 节点的 checkpoint。

        在创建复核任务后，立即保存当前状态快照，以便后续恢复。

        Args:
            state: 当前状态
            node_result: 节点返回的状态更新
        """
        try:
            # 获取快照管理器
            from core.agent.workflows.contract.snapshot_manager import (
                get_snapshot_manager,
                SnapshotReason,
            )

            snapshot_manager = get_snapshot_manager()

            # 合并状态（保留原有状态 + 节点更新）
            merged_state = {**state, **node_result}

            # 创建快照，标记为复核前
            snapshot = snapshot_manager.create_snapshot(
                run_id=state["run_id"],
                trace_id=state.get("trace_id", state["run_id"]),
                state=merged_state,
                reason=SnapshotReason.BEFORE_REVIEW,
            )

            logger.info(
                f"[{state['run_id']}] 保存 Human Review checkpoint | "
                f"snapshot_id={snapshot.snapshot_id}"
            )

        except Exception as e:
            # checkpoint 保存失败不应该影响主流程
            logger.warning(
                f"[{state['run_id']}] 保存 checkpoint 失败: {e}",
                exc_info=True
            )

    # ==================== 报告生成节点 ====================

    async def generate_report(self, state: ContractWorkflowState) -> dict:
        """Generate Report 节点：生成审查报告。

        职责：
        - 汇总所有分析结果
        - 将复核结果写入报告
        - 生成结构化审查报告
        - 确定审查结论
        """
        run_id = state["run_id"]

        logger.info(f"[{run_id}] 生成审查报告...")

        try:
            contract_name = state.get("contract_name", "未知合同")
            contract_type = state.get("contract_type")
            clauses = state.get("extracted_clauses", [])
            parties = state.get("parties", [])
            risks = state.get("identified_risks", [])
            laws = state.get("retrieved_laws", [])
            templates = state.get("retrieved_templates", [])

            # 获取复核结果（如果有）
            human_review_status = state.get("human_review_status", "")
            human_review_decision = state.get("human_review_decision", "")
            human_review_comments = state.get("human_review_comments", "")
            reviewer_name = state.get("reviewer_name", "")

            # 判断是否经过复核
            is_reviewed = human_review_status == "completed"
            is_approved = human_review_decision == "approved"
            is_rejected = human_review_decision == "rejected"
            is_revised = human_review_decision == "revised"

            # 调用 generate_report 工具
            tool = self.tool_map.get("generate_report")
            if tool:
                result = await tool.ainvoke({
                    "contract_name": contract_name,
                    "contract_type": contract_type,
                    "clauses": clauses,
                    "parties": parties,
                    "risks": risks,
                    "laws_context": laws,
                    "templates_context": templates,
                })

                if result.get("status") == "success":
                    report = result.get("report", {})
                    conclusion = result.get("conclusion", "")

                    # 根据复核结果调整结论
                    if is_reviewed:
                        conclusion = self._adjust_conclusion_by_review(
                            conclusion=conclusion,
                            decision=human_review_decision,
                            comments=human_review_comments,
                            reviewer_name=reviewer_name,
                        )

                        # 将复核信息写入报告
                        report["human_review"] = {
                            "status": human_review_status,
                            "decision": human_review_decision,
                            "comments": human_review_comments,
                            "reviewer_name": reviewer_name,
                        }

                    # 统计风险
                    high_count = len([r for r in risks if r.get("risk_type") == "high"])
                    medium_count = len([r for r in risks if r.get("risk_type") == "medium"])
                    low_count = len([r for r in risks if r.get("risk_type") == "low"])

                    return {
                        "current_stage": ContractWorkflowStage.FINISH.value,
                        "agent_status": AgentThought.FINISHED.value,
                        "review_report": report,
                        "conclusion": conclusion,
                        "high_risk_count": high_count,
                        "medium_risk_count": medium_count,
                        "low_risk_count": low_count,
                        "suggestions": report.get("suggestions", []),
                        "key_concerns": report.get("key_concerns", []),
                        "outcome": ContractWorkflowOutcome.FINISH.value,
                    }

            # 工具执行失败，使用备用方案
            return self._generate_report_fallback(state)

        except Exception as e:
            logger.error(f"[{run_id}] 生成报告失败: {e}", exc_info=True)
            return self._generate_report_fallback(state)

    def _adjust_conclusion_by_review(
        self,
        conclusion: str,
        decision: str,
        comments: str,
        reviewer_name: str,
    ) -> str:
        """根据复核结果调整审查结论。

        Args:
            conclusion: 原始结论
            decision: 复核决定
            comments: 复核意见
            reviewer_name: 复核人姓名

        Returns:
            调整后的结论
        """
        reviewer_info = f"（复核人：{reviewer_name}）" if reviewer_name else ""

        if decision == "approved":
            return (
                f"【法务复核通过】{reviewer_info}\n"
                f"该合同经法务人员审核，同意签署。\n"
                f"复核意见：{comments}"
            )

        elif decision == "rejected":
            return (
                f"【法务审核拒绝】{reviewer_info}\n"
                f"该合同经法务人员审核，不同意签署。\n"
                f"拒绝原因：{comments}"
            )

        elif decision == "revised":
            return (
                f"【需修改后复核】{reviewer_info}\n"
                f"该合同需按照法务意见修改后再行提交审核。\n"
                f"修改要求：{comments}"
            )

        return conclusion

    def _generate_report_fallback(self, state: dict) -> dict:
        """生成报告的备用方案（当工具不可用时）。"""
        risks = state.get("identified_risks", [])
        high_count = len([r for r in risks if r.get("risk_type") == "high"])
        medium_count = len([r for r in risks if r.get("risk_type") == "medium"])

        if high_count > 0:
            conclusion = "该合同存在高风险条款，建议法务部门人工复核后再行签署"
        elif medium_count > 0:
            conclusion = "该合同存在中风险条款，建议与对方协商修改后再行签署"
        else:
            conclusion = "该合同基本符合标准，建议审核后签署"

        suggestions = []
        for risk in risks[:5]:
            clause = risk.get("related_clause", "")
            desc = risk.get("risk_description", "")
            suggestion = risk.get("suggestion", "")
            if suggestion:
                suggestions.append(f"{clause}: {desc}。{suggestion}")

        report = {
            "report_id": f"report_{state['run_id']}",
            "contract_name": state.get("contract_name", "未知"),
            "contract_type": state.get("contract_type", "未知"),
            "review_summary": {
                "total_clauses": len(state.get("extracted_clauses", [])),
                "high_risk_count": high_count,
                "medium_risk_count": medium_count,
            },
            "conclusion": conclusion,
            "suggestions": suggestions,
        }

        return {
            "current_stage": ContractWorkflowStage.FINISH.value,
            "agent_status": AgentThought.FINISHED.value,
            "review_report": report,
            "conclusion": conclusion,
            "high_risk_count": high_count,
            "medium_risk_count": medium_count,
            "low_risk_count": len([r for r in risks if r.get("risk_type") == "low"]),
            "suggestions": suggestions,
            "outcome": ContractWorkflowOutcome.FINISH.value,
        }

    # ==================== 澄清节点 ====================

    async def clarification(self, state: ContractWorkflowState) -> dict:
        """Clarification 澄清节点：等待用户补充信息。

        当工作流进入澄清状态时，此节点负责：
        - 记录需要澄清的问题
        - 设置 Agent 等待状态
        - 等待用户通过 API 补充信息后重新进入 entry

        用户补充信息后，应该：
        1. API 层更新 conversation/slot 数据
        2. 用户发起新请求时携带补充的信息
        3. 工作流从 entry 重新开始
        """
        run_id = state["run_id"]
        clarification_question = state.get("clarification_question", "请补充必要信息")

        logger.info(
            f"[{run_id}] 进入澄清阶段 | "
            f"问题: {clarification_question}"
        )

        return {
            "current_stage": ContractWorkflowStage.CLARIFICATION.value,
            "agent_status": AgentThought.WAITING_CLARIFICATION.value,
            "clarification_needed": True,
            # clarification_question 保持不变，让 API 层可以获取
        }

    # ==================== 结束节点 ====================

    async def finish(self, state: ContractWorkflowState) -> dict:
        """Finish 节点：结束工作流。

        职责：
        - 记录完成状态
        - 清理临时资源
        """
        run_id = state["run_id"]

        logger.info(
            f"[{run_id}] 合同审查完成 | "
            f"结论: {state.get('conclusion', 'N/A')[:50]}..."
        )

        return {
            "current_stage": ContractWorkflowStage.FINISH.value,
            "outcome": ContractWorkflowOutcome.FINISH.value,
        }
