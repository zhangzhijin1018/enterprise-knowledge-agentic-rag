"""澄清分支控制模块。"""

from __future__ import annotations

from core.agent.control_plane.state_manager import WorkflowStateManager
from core.agent.state import AgentState
from core.common.response import build_response_meta
from core.repositories.conversation_repository import ConversationRepository


class ClarificationManager:
    """澄清分支处理器。"""

    def __init__(
        self,
        conversation_repository: ConversationRepository,
        state_manager: WorkflowStateManager,
    ) -> None:
        """注入澄清分支需要的依赖。"""

        self.conversation_repository = conversation_repository
        self.state_manager = state_manager

    def handle_metric_clarification(self, state: AgentState) -> dict:
        """处理“经营分析但缺指标”的最小澄清流程。"""

        clarification_question = "你想看哪个指标？发电量、收入还是成本？"
        clarification_slots = ["metric"]

        clarification_event = self.state_manager.create_clarification_runtime(
            state=state,
            question_text=clarification_question,
            target_slots=clarification_slots,
            resume_step="resume_after_metric_clarification",
        )

        self.conversation_repository.add_message(
            conversation_id=state["conversation_id"],
            role="assistant",
            message_type="clarification",
            content=clarification_question,
            related_run_id=state["run_id"],
            structured_content={
                "clarification_id": clarification_event["clarification_id"],
                "target_slots": clarification_slots,
            },
        )
        self.conversation_repository.upsert_memory(
            state["conversation_id"],
            last_route=state["route"],
            short_term_memory={
                "last_status": "awaiting_user_clarification",
                "clarification_id": clarification_event["clarification_id"],
            },
        )
        self.conversation_repository.update_conversation(
            state["conversation_id"],
            current_route=state["route"],
            current_status="active",
            last_run_id=state["run_id"],
        )

        state["clarification_id"] = clarification_event["clarification_id"]
        state["clarification_question"] = clarification_question
        state["clarification_slots"] = clarification_slots
        state["status"] = "awaiting_user_clarification"
        state["sub_status"] = "awaiting_slot_fill"

        return {
            "data": {
                "clarification": {
                    "clarification_id": clarification_event["clarification_id"],
                    "question": clarification_question,
                    "target_slots": clarification_slots,
                }
            },
            "meta": build_response_meta(
                conversation_id=state["conversation_id"],
                run_id=state["run_id"],
                status="awaiting_user_clarification",
                sub_status="awaiting_slot_fill",
                need_clarification=True,
                is_async=False,
            ),
        }
