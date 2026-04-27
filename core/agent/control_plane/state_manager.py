"""工作流运行态持久化控制模块。

当前模块专注处理三类对象的持久化更新：
- `task_run`
- `slot_snapshot`
- `clarification_event`

这样做可以让 workflow 主文件更多关注“流程顺序”，
而不是到处直接写 repository 调用细节。
"""

from __future__ import annotations

from datetime import datetime

from apps.api.schemas.chat import ChatRequest
from core.agent.state import AgentState
from core.repositories.task_run_repository import TaskRunRepository


class WorkflowStateManager:
    """工作流状态持久化管理器。"""

    def __init__(self, task_run_repository: TaskRunRepository) -> None:
        """注入任务运行仓储。"""

        self.task_run_repository = task_run_repository

    def create_task_run(
        self,
        conversation_id: str,
        user_id: int,
        payload: ChatRequest,
    ) -> dict:
        """创建最小任务运行记录。"""

        return self.task_run_repository.create_task_run(
            conversation_id=conversation_id,
            user_id=user_id,
            task_type="chat",
            route="chat",
            status="created",
            sub_status="request_received",
            input_snapshot=payload.model_dump(),
        )

    def update_task_run_stage(self, state: AgentState, **updates) -> None:
        """统一更新任务运行状态。"""

        self.task_run_repository.update_task_run(state["run_id"], **updates)

    def create_clarification_runtime(
        self,
        state: AgentState,
        question_text: str,
        target_slots: list[str],
        resume_step: str,
    ) -> dict:
        """创建澄清分支所需的运行态对象。"""

        self.task_run_repository.create_slot_snapshot(
            run_id=state["run_id"],
            task_type=state["task_type"],
            required_slots=target_slots,
            collected_slots={},
            missing_slots=target_slots,
            min_executable_satisfied=False,
            awaiting_user_input=True,
            resume_step=resume_step,
        )
        clarification_event = self.task_run_repository.create_clarification_event(
            run_id=state["run_id"],
            conversation_id=state["conversation_id"],
            question_text=question_text,
            target_slots=target_slots,
        )
        self.update_task_run_stage(
            state,
            status="awaiting_user_clarification",
            sub_status="awaiting_slot_fill",
        )
        return clarification_event

    def mark_answer_succeeded(
        self,
        state: AgentState,
        answer: str,
        citations: list[dict],
        finished_at: datetime,
    ) -> None:
        """把任务运行标记为成功完成。"""

        self.update_task_run_stage(
            state,
            status="succeeded",
            sub_status="drafting_answer",
            output_snapshot={"answer": answer, "citations": citations},
            finished_at=finished_at,
        )
