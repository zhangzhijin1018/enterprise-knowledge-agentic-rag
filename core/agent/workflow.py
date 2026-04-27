"""Agent 工作流门面。

当前阶段还不接真实 LangGraph，
但先把“Chat 请求如何进入受控工作流”这件事收口到独立门面里。

这样做的工程收益是：
1. router 和 service 不直接承载具体分支判断；
2. 当前 mock 规则、状态流转、澄清分支都有统一入口；
3. 后续接真实 LangGraph 时，优先替换这里的执行实现，而不是改外围接口层。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apps.api.schemas.chat import ChatRequest
from core.agent.control_plane import ClarificationManager, TaskRouter, WorkflowStateManager
from core.agent.state import AgentState
from core.common.response import build_response_meta
from core.repositories.conversation_repository import ConversationRepository
from core.repositories.task_run_repository import TaskRunRepository
from core.security.auth import UserContext

logger = logging.getLogger("core.agent.workflow")


class ChatWorkflowFacade:
    """最小 Chat 工作流门面。

    当前职责：
    - 构造最小 AgentState；
    - 按工作流顺序推进状态；
    - 决定进入 mock answer 还是 clarification；
    - 持久化会话消息、任务状态和恢复所需运行态对象。

    当前不做的事：
    - 不接真实 LLM；
    - 不接真实 RAG；
    - 不接真实 LangGraph；
    - 不接真实 Human Review。
    """

    def __init__(
        self,
        conversation_repository: ConversationRepository,
        task_run_repository: TaskRunRepository,
    ) -> None:
        """注入工作流执行依赖。

        第三轮开始，workflow 内部做了轻拆分：
        - `TaskRouter` 负责路由判断；
        - `WorkflowStateManager` 负责运行态持久化；
        - `ClarificationManager` 负责澄清分支细节。

        这样不会改变外部 API 契约，但能让主流程编排更清晰。
        """

        self.conversation_repository = conversation_repository
        self.task_run_repository = task_run_repository
        self.task_router = TaskRouter()
        self.state_manager = WorkflowStateManager(task_run_repository=task_run_repository)
        self.clarification_manager = ClarificationManager(
            conversation_repository=conversation_repository,
            state_manager=self.state_manager,
        )

    def execute_chat(self, payload: ChatRequest, user_context: UserContext) -> dict:
        """执行最小 chat 工作流。

        工作流顺序：
        1. 获取或创建会话；
        2. 创建 task run；
        3. 写入用户消息；
        4. 构造结构化 AgentState；
        5. 依次经过 context / authorize / risk / route / execute 节点；
        6. 返回统一 data / meta 响应。

        第二轮数据库完善后，这条工作流不需要知道底层到底是：
        - PostgreSQL + SQLAlchemy Session；
        - 还是本地内存回退模式。

        这正是当前分层设计的价值：
        工作流只依赖 Repository 抽象，不直接依赖数据库细节。
        """

        conversation = self._get_or_create_conversation(
            conversation_id=payload.conversation_id,
            user_id=user_context.user_id,
            query=payload.query,
        )
        task_run = self.state_manager.create_task_run(
            conversation_id=conversation["conversation_id"],
            user_id=user_context.user_id,
            payload=payload,
        )

        self.conversation_repository.add_message(
            conversation_id=conversation["conversation_id"],
            role="user",
            message_type="text",
            content=payload.query,
            related_run_id=task_run["run_id"],
        )
        self.conversation_repository.update_conversation(
            conversation["conversation_id"],
            current_route="chat",
            current_status="active",
            last_run_id=task_run["run_id"],
        )

        state = self._build_initial_state(
            conversation=conversation,
            task_run=task_run,
            payload=payload,
            user_context=user_context,
        )
        state = self._context_build_node(state)
        state = self._authorize_node(state)
        state = self._risk_check_node(state)
        state = self._route_node(state)
        result = self._execute_node(state)

        logger.info(
            "chat_workflow_finished run_id=%s conversation_id=%s route=%s status=%s sub_status=%s user_id=%s",
            state["run_id"],
            state["conversation_id"],
            state["route"],
            result["meta"].get("status"),
            result["meta"].get("sub_status"),
            state["user_id"],
        )
        return result

    def _build_initial_state(
        self,
        conversation: dict,
        task_run: dict,
        payload: ChatRequest,
        user_context: UserContext,
    ) -> AgentState:
        """构造最小 AgentState。

        为什么要尽早结构化：
        - 当前虽然只是 mock 工作流，但状态结构一旦稳定，
          后续改成真实工作流时，节点之间就不需要靠零散 dict 传值；
        - 这也是工作流可恢复、可审计、可评估的基础。
        """

        return AgentState(
            run_id=task_run["run_id"],
            conversation_id=conversation["conversation_id"],
            trace_id=task_run["trace_id"],
            user_id=user_context.user_id,
            user_role=user_context.roles[0] if user_context.roles else "employee",
            query=payload.query,
            business_hint=payload.business_hint or "",
            route="chat",
            business_domain="general",
            task_type="chat",
            knowledge_base_ids=payload.knowledge_base_ids,
            history_messages=[item.model_dump() for item in payload.history_messages],
            retrieved_chunks=[],
            tool_calls=[],
            risk_level="low",
            need_human_review=False,
            review_status="not_required",
            final_answer="",
            selected_agent="",
            selected_capability="",
            citations=[],
            clarification_id="",
            clarification_question="",
            clarification_slots=[],
            status="created",
            sub_status="request_received",
        )

    def _context_build_node(self, state: AgentState) -> AgentState:
        """上下文构建节点。

        当前阶段不做真正上下文压缩或历史回放拼接，
        但先在任务状态里标记“上下文已就绪”，为后续接 LangGraph 节点顺序预留位置。
        """

        self._update_task_run_stage(
            state,
            status="context_built",
            sub_status="building_context",
            context_snapshot={
                "history_message_count": len(state["history_messages"]),
                "knowledge_base_ids": state["knowledge_base_ids"],
                "business_hint": state["business_hint"],
            },
        )
        state["status"] = "context_built"
        state["sub_status"] = "building_context"
        return state

    def _authorize_node(self, state: AgentState) -> AgentState:
        """权限前置节点。

        当前阶段还没有真正的 RBAC / ABAC 规则引擎，
        但要先把“授权是一个独立工作流节点”这件事固定下来。
        """

        self._update_task_run_stage(
            state,
            status="authorized",
            sub_status="permission_checked",
        )
        state["status"] = "authorized"
        state["sub_status"] = "permission_checked"
        return state

    def _risk_check_node(self, state: AgentState) -> AgentState:
        """风险初判节点。

        当前最小规则：
        - 默认 low；
        - 如果问题明显涉及经营分析，则提升为 medium。

        这里先不触发 Human Review，
        但要为后续“风险前置 -> 必要时中断”预留标准节点位置。
        """

        if any(keyword in state["query"] for keyword in ("经营", "分析", "指标", "趋势")):
            state["risk_level"] = "medium"

        self._update_task_run_stage(
            state,
            status="risk_checked",
            sub_status="risk_assessed",
            risk_level=state["risk_level"],
        )
        state["status"] = "risk_checked"
        state["sub_status"] = "risk_assessed"
        return state

    def _route_node(self, state: AgentState) -> AgentState:
        """场景路由节点。

        当前先用可解释规则替代 LLM 路由：
        - 经营分析类问题进入 `business_analysis`；
        - 制度政策类问题进入 `policy_qa`；
        - 其他问题进入 `general_qa`。

        后续接真实路由模型时，优先替换本节点，而不是外围 API 契约。
        """

        decision = self.task_router.route(state["query"])
        state["route"] = decision.route
        state["business_domain"] = decision.business_domain
        state["selected_agent"] = decision.selected_agent
        state["selected_capability"] = decision.selected_capability

        self._update_task_run_stage(
            state,
            status="routed",
            sub_status="route_selected",
            route=state["route"],
            selected_agent=state["selected_agent"],
            selected_capability=state["selected_capability"],
        )
        state["status"] = "routed"
        state["sub_status"] = "route_selected"
        return state

    def _execute_node(self, state: AgentState) -> dict:
        """执行节点。

        当前仍然是 mock 执行，
        但它已经被包装成统一的“执行阶段”，
        后续切到真实 LangGraph / Tool Calling 时，可以沿用同一入口。
        """

        self._update_task_run_stage(
            state,
            status="executing",
            sub_status="drafting_answer",
        )
        state["status"] = "executing"
        state["sub_status"] = "drafting_answer"

        if state["route"] == "business_analysis":
            return self._execute_clarification_path(state)

        return self._execute_answer_path(state)

    def _execute_clarification_path(self, state: AgentState) -> dict:
        """执行澄清分支。

        workflow 本身只负责决定“进入澄清”；
        具体的运行态创建、消息落库和响应构造都交给 `ClarificationManager`。
        """

        return self.clarification_manager.handle_metric_clarification(state)

    def _execute_answer_path(self, state: AgentState) -> dict:
        """执行直接回答分支。"""

        answer = (
            "这是第一阶段最小后端骨架返回的 mock answer。"
            f"系统已接收到你的问题：{state['query']}。"
            "当前已打通会话、任务运行、消息记录和统一响应结构，"
            "后续会在这个位置接入真实 Agent 工作流与 RAG 检索。"
        )
        citations = [
            {
                "document_id": "doc_mock_001",
                "document_title": "示例制度文档（Mock）",
                "chunk_id": "chunk_mock_001",
                "page_no": 1,
                "snippet": "当前为 mock 引用，用于预留答案可溯源接口结构。",
            }
        ]
        finished_at = datetime.now(timezone.utc)

        self.conversation_repository.add_message(
            conversation_id=state["conversation_id"],
            role="assistant",
            message_type="answer",
            content=answer,
            related_run_id=state["run_id"],
            structured_content={"citations": citations},
        )
        self.conversation_repository.upsert_memory(
            state["conversation_id"],
            last_route=state["route"],
            short_term_memory={
                "last_status": "succeeded",
                "last_answer_preview": answer[:80],
            },
        )
        self.conversation_repository.update_conversation(
            state["conversation_id"],
            current_route=state["route"],
            current_status="active",
            last_run_id=state["run_id"],
        )

        state["final_answer"] = answer
        state["citations"] = citations
        state["status"] = "succeeded"
        state["sub_status"] = "drafting_answer"

        self.state_manager.mark_answer_succeeded(
            state=state,
            answer=answer,
            citations=citations,
            finished_at=finished_at,
        )

        return {
            "data": {
                "answer": answer,
                "citations": citations,
            },
            "meta": build_response_meta(
                conversation_id=state["conversation_id"],
                run_id=state["run_id"],
                status="succeeded",
                sub_status="drafting_answer",
                need_human_review=False,
                need_clarification=False,
                is_async=False,
            ),
        }

    def _update_task_run_stage(self, state: AgentState, **updates) -> None:
        """统一更新任务运行状态。

        为什么集中封装：
        - 工作流节点最核心的职责之一就是状态迁移；
        - 如果每个节点都随手更新 task_run，后续很难保持状态字典一致；
        - 集中到一个方法里，更方便未来接审计日志或状态迁移校验。
        """

        self.state_manager.update_task_run_stage(state, **updates)

    def _get_or_create_conversation(self, conversation_id: str | None, user_id: int, query: str) -> dict:
        """获取或创建会话。"""

        if conversation_id:
            conversation = self.conversation_repository.get_conversation(conversation_id)
            if conversation is not None:
                return conversation

        title = query[:20]
        return self.conversation_repository.create_conversation(
            user_id=user_id,
            title=title,
            current_route="chat",
            current_status="active",
        )
