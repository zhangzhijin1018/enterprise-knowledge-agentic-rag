"""任务运行 Repository。

当前用内存实现存储 task run、slot snapshot 和 clarification event，
目的是先把“运行态对象”和“恢复执行对象”的关系跑通。
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from core.database.models import ClarificationEvent, Conversation, SlotSnapshot, TaskRun

_TASK_RUNS: dict[str, dict] = {}
_SLOT_SNAPSHOTS: dict[str, dict] = {}
_CLARIFICATION_EVENTS: dict[str, dict] = {}


def _utcnow() -> datetime:
    """返回当前 UTC 时间。"""

    return datetime.now(timezone.utc)


def _generate_prefixed_id(prefix: str) -> str:
    """生成带业务前缀的占位 ID。"""

    return f"{prefix}_{uuid4().hex[:12]}"


def reset_in_memory_task_run_store() -> None:
    """重置运行态相关内存存储。"""

    _TASK_RUNS.clear()
    _SLOT_SNAPSHOTS.clear()
    _CLARIFICATION_EVENTS.clear()


class TaskRunRepository:
    """任务运行数据访问层。"""

    def __init__(self, session=None) -> None:
        """保留 session 参数，为后续切换真实 ORM 实现预留入口。"""

        self.session = session

    def _use_database(self) -> bool:
        """判断当前是否启用真实数据库模式。"""

        return self.session is not None

    def _serialize_task_run(self, task_run: TaskRun, conversation_uuid: str | None = None) -> dict:
        """把 ORM 任务运行对象转换成统一字典结构。"""

        return {
            "run_id": task_run.run_id,
            "task_id": task_run.task_id,
            "parent_task_id": task_run.parent_task_id,
            "conversation_id": conversation_uuid,
            "user_id": task_run.user_id,
            "trace_id": task_run.trace_id,
            "task_type": task_run.task_type,
            "route": task_run.route,
            "selected_agent": task_run.selected_agent,
            "selected_capability": task_run.selected_capability,
            "risk_level": task_run.risk_level,
            "review_status": task_run.review_status,
            "status": task_run.status,
            "sub_status": task_run.sub_status,
            "input_snapshot": task_run.input_snapshot or {},
            "output_snapshot": task_run.output_snapshot or {},
            "context_snapshot": task_run.context_snapshot or {},
            "retry_count": task_run.retry_count,
            "error_code": task_run.error_code,
            "error_message": task_run.error_message,
            "started_at": task_run.started_at,
            "finished_at": task_run.finished_at,
            "created_at": task_run.created_at,
            "updated_at": task_run.updated_at,
        }

    def _get_conversation_model(self, conversation_id: str) -> Conversation | None:
        """在数据库模式下根据对外会话 ID 读取会话 ORM 对象。"""

        if not self._use_database():
            return None
        statement = select(Conversation).where(Conversation.conversation_uuid == conversation_id)
        return self.session.execute(statement).scalar_one_or_none()

    def _get_task_run_model(self, run_id: str) -> TaskRun | None:
        """读取任务运行 ORM 对象。"""

        if not self._use_database():
            return None
        statement = select(TaskRun).where(TaskRun.run_id == run_id)
        return self.session.execute(statement).scalar_one_or_none()

    def create_task_run(
        self,
        conversation_id: str,
        user_id: int,
        task_type: str,
        route: str,
        status: str,
        sub_status: str | None,
        input_snapshot: dict,
        risk_level: str = "low",
        review_status: str = "not_required",
    ) -> dict:
        """创建任务运行记录。"""

        if self._use_database():
            conversation = self._get_conversation_model(conversation_id)
            if conversation is None:
                raise ValueError(f"Conversation not found: {conversation_id}")
            task_run = TaskRun(
                run_id=_generate_prefixed_id("run"),
                task_id=_generate_prefixed_id("task"),
                parent_task_id=None,
                conversation_id=conversation.id,
                user_id=user_id,
                trace_id=_generate_prefixed_id("tr"),
                task_type=task_type,
                route=route,
                selected_agent="mock_chat_agent",
                selected_capability="local_mock_answer",
                risk_level=risk_level,
                review_status=review_status,
                status=status,
                sub_status=sub_status,
                input_snapshot=input_snapshot,
                output_snapshot={},
                context_snapshot={},
                retry_count=0,
                error_code=None,
                error_message=None,
                started_at=_utcnow(),
                finished_at=None,
            )
            self.session.add(task_run)
            self.session.flush()
            self.session.refresh(task_run)
            return self._serialize_task_run(
                task_run,
                conversation_uuid=conversation.conversation_uuid,
            )

        now = _utcnow()
        run_id = _generate_prefixed_id("run")
        record = {
            "run_id": run_id,
            "task_id": _generate_prefixed_id("task"),
            "parent_task_id": None,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "trace_id": _generate_prefixed_id("tr"),
            "task_type": task_type,
            "route": route,
            "selected_agent": "mock_chat_agent",
            "selected_capability": "local_mock_answer",
            "risk_level": risk_level,
            "review_status": review_status,
            "status": status,
            "sub_status": sub_status,
            "input_snapshot": input_snapshot,
            "output_snapshot": {},
            "context_snapshot": {},
            "retry_count": 0,
            "error_code": None,
            "error_message": None,
            "started_at": now,
            "finished_at": None,
            "created_at": now,
            "updated_at": now,
        }
        _TASK_RUNS[run_id] = record
        return record

    def get_task_run(self, run_id: str) -> dict | None:
        """读取任务运行记录。"""

        if self._use_database():
            task_run = self._get_task_run_model(run_id)
            if task_run is None:
                return None
            conversation_uuid = None
            if task_run.conversation_id is not None:
                statement = select(Conversation).where(Conversation.id == task_run.conversation_id)
                conversation = self.session.execute(statement).scalar_one_or_none()
                if conversation is not None:
                    conversation_uuid = conversation.conversation_uuid
            return self._serialize_task_run(task_run, conversation_uuid=conversation_uuid)

        return _TASK_RUNS.get(run_id)

    def update_task_run(self, run_id: str, **updates) -> dict | None:
        """更新任务运行记录。"""

        if self._use_database():
            task_run = self._get_task_run_model(run_id)
            if task_run is None:
                return None
            for key, value in updates.items():
                if hasattr(task_run, key):
                    setattr(task_run, key, value)
            self.session.flush()
            self.session.refresh(task_run)
            conversation_uuid = None
            if task_run.conversation_id is not None:
                statement = select(Conversation).where(Conversation.id == task_run.conversation_id)
                conversation = self.session.execute(statement).scalar_one_or_none()
                if conversation is not None:
                    conversation_uuid = conversation.conversation_uuid
            return self._serialize_task_run(task_run, conversation_uuid=conversation_uuid)

        record = self.get_task_run(run_id)
        if record is None:
            return None

        record.update(updates)
        record["updated_at"] = _utcnow()
        return record

    def create_slot_snapshot(
        self,
        run_id: str,
        task_type: str,
        required_slots: list[str],
        collected_slots: dict,
        missing_slots: list[str],
        min_executable_satisfied: bool,
        awaiting_user_input: bool,
        resume_step: str | None,
    ) -> dict:
        """创建槽位快照。"""

        if self._use_database():
            snapshot = SlotSnapshot(
                run_id=run_id,
                task_type=task_type,
                required_slots=required_slots,
                collected_slots=collected_slots,
                missing_slots=missing_slots,
                min_executable_satisfied=min_executable_satisfied,
                awaiting_user_input=awaiting_user_input,
                resume_step=resume_step,
            )
            self.session.add(snapshot)
            self.session.flush()
            self.session.refresh(snapshot)
            return {
                "run_id": snapshot.run_id,
                "task_type": snapshot.task_type,
                "required_slots": snapshot.required_slots or [],
                "collected_slots": snapshot.collected_slots or {},
                "missing_slots": snapshot.missing_slots or [],
                "min_executable_satisfied": snapshot.min_executable_satisfied,
                "awaiting_user_input": snapshot.awaiting_user_input,
                "resume_step": snapshot.resume_step,
                "updated_at": snapshot.updated_at,
            }

        record = {
            "run_id": run_id,
            "task_type": task_type,
            "required_slots": required_slots,
            "collected_slots": collected_slots,
            "missing_slots": missing_slots,
            "min_executable_satisfied": min_executable_satisfied,
            "awaiting_user_input": awaiting_user_input,
            "resume_step": resume_step,
            "updated_at": _utcnow(),
        }
        _SLOT_SNAPSHOTS[run_id] = record
        return record

    def get_slot_snapshot(self, run_id: str) -> dict | None:
        """读取槽位快照。"""

        if self._use_database():
            statement = select(SlotSnapshot).where(SlotSnapshot.run_id == run_id)
            snapshot = self.session.execute(statement).scalar_one_or_none()
            if snapshot is None:
                return None
            return {
                "run_id": snapshot.run_id,
                "task_type": snapshot.task_type,
                "required_slots": snapshot.required_slots or [],
                "collected_slots": snapshot.collected_slots or {},
                "missing_slots": snapshot.missing_slots or [],
                "min_executable_satisfied": snapshot.min_executable_satisfied,
                "awaiting_user_input": snapshot.awaiting_user_input,
                "resume_step": snapshot.resume_step,
                "updated_at": snapshot.updated_at,
            }

        return _SLOT_SNAPSHOTS.get(run_id)

    def update_slot_snapshot(self, run_id: str, **updates) -> dict | None:
        """更新槽位快照。"""

        if self._use_database():
            statement = select(SlotSnapshot).where(SlotSnapshot.run_id == run_id)
            snapshot = self.session.execute(statement).scalar_one_or_none()
            if snapshot is None:
                return None
            for key, value in updates.items():
                if hasattr(snapshot, key):
                    setattr(snapshot, key, value)
            self.session.flush()
            self.session.refresh(snapshot)
            return {
                "run_id": snapshot.run_id,
                "task_type": snapshot.task_type,
                "required_slots": snapshot.required_slots or [],
                "collected_slots": snapshot.collected_slots or {},
                "missing_slots": snapshot.missing_slots or [],
                "min_executable_satisfied": snapshot.min_executable_satisfied,
                "awaiting_user_input": snapshot.awaiting_user_input,
                "resume_step": snapshot.resume_step,
                "updated_at": snapshot.updated_at,
            }

        record = self.get_slot_snapshot(run_id)
        if record is None:
            return None
        record.update(updates)
        record["updated_at"] = _utcnow()
        return record

    def create_clarification_event(
        self,
        run_id: str,
        conversation_id: str,
        question_text: str,
        target_slots: list[str],
    ) -> dict:
        """创建澄清事件。"""

        if self._use_database():
            conversation = self._get_conversation_model(conversation_id)
            if conversation is None:
                raise ValueError(f"Conversation not found: {conversation_id}")
            clarification = ClarificationEvent(
                clarification_uuid=_generate_prefixed_id("clr"),
                run_id=run_id,
                conversation_id=conversation.id,
                question_text=question_text,
                target_slots=target_slots,
                user_reply=None,
                resolved_slots={},
                status="pending",
                created_at=_utcnow(),
                resolved_at=None,
            )
            self.session.add(clarification)
            self.session.flush()
            self.session.refresh(clarification)
            return {
                "clarification_id": clarification.clarification_uuid,
                "run_id": clarification.run_id,
                "conversation_id": conversation_id,
                "question_text": clarification.question_text,
                "target_slots": clarification.target_slots or [],
                "user_reply": clarification.user_reply,
                "resolved_slots": clarification.resolved_slots or {},
                "status": clarification.status,
                "created_at": clarification.created_at,
                "resolved_at": clarification.resolved_at,
            }

        now = _utcnow()
        clarification_id = _generate_prefixed_id("clr")
        record = {
            "clarification_id": clarification_id,
            "run_id": run_id,
            "conversation_id": conversation_id,
            "question_text": question_text,
            "target_slots": target_slots,
            "user_reply": None,
            "resolved_slots": {},
            "status": "pending",
            "created_at": now,
            "resolved_at": None,
        }
        _CLARIFICATION_EVENTS[clarification_id] = record
        return record

    def get_clarification_event(self, clarification_id: str) -> dict | None:
        """读取澄清事件。"""

        if self._use_database():
            statement = select(ClarificationEvent).where(
                ClarificationEvent.clarification_uuid == clarification_id
            )
            clarification = self.session.execute(statement).scalar_one_or_none()
            if clarification is None:
                return None
            conversation_uuid = None
            if clarification.conversation_id is not None:
                statement = select(Conversation).where(Conversation.id == clarification.conversation_id)
                conversation = self.session.execute(statement).scalar_one_or_none()
                if conversation is not None:
                    conversation_uuid = conversation.conversation_uuid
            return {
                "clarification_id": clarification.clarification_uuid,
                "run_id": clarification.run_id,
                "conversation_id": conversation_uuid,
                "question_text": clarification.question_text,
                "target_slots": clarification.target_slots or [],
                "user_reply": clarification.user_reply,
                "resolved_slots": clarification.resolved_slots or {},
                "status": clarification.status,
                "created_at": clarification.created_at,
                "resolved_at": clarification.resolved_at,
            }

        return _CLARIFICATION_EVENTS.get(clarification_id)

    def update_clarification_event(self, clarification_id: str, **updates) -> dict | None:
        """更新澄清事件。"""

        if self._use_database():
            statement = select(ClarificationEvent).where(
                ClarificationEvent.clarification_uuid == clarification_id
            )
            clarification = self.session.execute(statement).scalar_one_or_none()
            if clarification is None:
                return None
            for key, value in updates.items():
                if hasattr(clarification, key):
                    setattr(clarification, key, value)
            self.session.flush()
            self.session.refresh(clarification)
            conversation_uuid = None
            if clarification.conversation_id is not None:
                statement = select(Conversation).where(Conversation.id == clarification.conversation_id)
                conversation = self.session.execute(statement).scalar_one_or_none()
                if conversation is not None:
                    conversation_uuid = conversation.conversation_uuid
            return {
                "clarification_id": clarification.clarification_uuid,
                "run_id": clarification.run_id,
                "conversation_id": conversation_uuid,
                "question_text": clarification.question_text,
                "target_slots": clarification.target_slots or [],
                "user_reply": clarification.user_reply,
                "resolved_slots": clarification.resolved_slots or {},
                "status": clarification.status,
                "created_at": clarification.created_at,
                "resolved_at": clarification.resolved_at,
            }

        record = self.get_clarification_event(clarification_id)
        if record is None:
            return None
        record.update(updates)
        return record
