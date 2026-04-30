"""任务运行 Repository。

当前用内存实现存储 task run、slot snapshot 和 clarification event，
目的是先把“运行态对象”和“恢复执行对象”的关系跑通。
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database.models import ClarificationEvent, Conversation, SlotSnapshot, TaskRun

_TASK_RUNS: dict[str, dict] = {}
_SLOT_SNAPSHOTS: dict[str, dict] = {}
_CLARIFICATION_EVENTS: dict[str, dict] = {}

# task_run 里的轻快照必须明确禁止落入的大对象字段。
# 这些字段要么属于经营分析重结果，要么属于微观 workflow 临时上下文，
# 如果继续写回 task_run，就会重新把“权威运行态”变成“大对象垃圾桶”。
_FORBIDDEN_RUNTIME_SNAPSHOT_KEYS = {
    "tables",
    "chart_spec",
    "insight_cards",
    "report_blocks",
    "execution_result",
    "sql_bundle",
    "plan",
    "metric_definition",
    "data_source_definition",
    "table_definition",
    "permission_check_result",
    "data_scope_result",
    "guard_result",
    "audit_record",
    "masking_result",
    "analytics_result",
    "workflow_stage",
    "workflow_outcome",
    "next_step",
    "rows",
    "columns",
    "masked_rows",
    "masked_columns",
}

# slot_snapshot 的职责是“恢复执行态”，因此只允许保存补槽恢复所需的最小字段。
_ALLOWED_SLOT_SNAPSHOT_FIELDS = {
    "run_id",
    "task_type",
    "required_slots",
    "collected_slots",
    "missing_slots",
    "min_executable_satisfied",
    "awaiting_user_input",
    "resume_step",
    "updated_at",
}

# clarification_event 的职责是“可审计的交互事件”，
# 所以只允许保存追问、回复、解析结果和事件状态。
_ALLOWED_CLARIFICATION_EVENT_FIELDS = {
    "clarification_id",
    "run_id",
    "conversation_id",
    "question_text",
    "target_slots",
    "user_reply",
    "resolved_slots",
    "status",
    "created_at",
    "resolved_at",
}


def _utcnow() -> datetime:
    """返回当前 UTC 时间。"""

    return datetime.now(timezone.utc)


def _generate_prefixed_id(prefix: str) -> str:
    """生成带业务前缀的占位 ID。"""

    return f"{prefix}_{uuid4().hex[:12]}"


def _sanitize_runtime_snapshot(snapshot: dict | None) -> dict:
    """裁剪 task_run 里的轻量快照。

    为什么需要仓储层再做一次裁剪：
    1. 上层 Service / Workflow 已经按设计只写轻快照；
    2. 但仓储层仍要兜底，防止后续维护时有人把微观大对象重新塞回 task_run；
    3. 这样数据库模式和内存模式都能共享同一套边界约束。
    """

    if not isinstance(snapshot, dict):
        return {}
    return {
        key: value
        for key, value in snapshot.items()
        if key not in _FORBIDDEN_RUNTIME_SNAPSHOT_KEYS
    }


def _sanitize_slot_snapshot_record(record: dict) -> dict:
    """裁剪 slot_snapshot，只保留恢复执行所需字段。"""

    return {
        key: value
        for key, value in record.items()
        if key in _ALLOWED_SLOT_SNAPSHOT_FIELDS
    }


def _sanitize_clarification_event_record(record: dict) -> dict:
    """裁剪 clarification_event，只保留澄清交互事件字段。"""

    return {
        key: value
        for key, value in record.items()
        if key in _ALLOWED_CLARIFICATION_EVENT_FIELDS
    }


def reset_in_memory_task_run_store() -> None:
    """重置运行态相关内存存储。"""

    _TASK_RUNS.clear()
    _SLOT_SNAPSHOTS.clear()
    _CLARIFICATION_EVENTS.clear()


class TaskRunRepository:
    """任务运行数据访问层。

    职责分层说明：
    1. `task_run` 是权威运行态，负责保存跨请求可恢复、跨层可观测、跨系统可审计的主状态；
    2. `slot_snapshot` 是恢复执行态，只服务补槽和 clarification 恢复；
    3. `clarification_event` 是可审计交互事件，记录“系统怎么问、用户怎么答、解析出什么”；
    4. 经营分析 workflow 的微观大对象不能直接落到这里，而应该留在 workflow state
       或拆到 analytics_result_repository / sql_audit 等专属存储。
    """

    def __init__(self, session: Session | None = None) -> None:
        """初始化任务运行 Repository。

        设计说明：
        - 如果已有真实 Session，则优先走数据库；
        - 如果没有 Session，则自动回退到内存运行态存储；
        - 这样 Clarification、SlotSnapshot、TaskRun 的上层工作流都不需要感知底层模式切换。
        """

        self.session = session

    def _use_database(self) -> bool:
        """判断当前是否启用真实数据库模式。"""

        return self.session is not None

    def _serialize_task_run(self, task_run: TaskRun, conversation_uuid: str | None = None) -> dict:
        """把 ORM 任务运行对象转换成统一字典结构。

        这里会再次裁剪 input/output/context snapshot，
        目的是保证即使历史记录里曾出现过越界字段，对外读取时也尽量保持边界干净。
        """

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
            "input_snapshot": _sanitize_runtime_snapshot(task_run.input_snapshot or {}),
            "output_snapshot": _sanitize_runtime_snapshot(task_run.output_snapshot or {}),
            "context_snapshot": _sanitize_runtime_snapshot(task_run.context_snapshot or {}),
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
        run_id: str | None = None,
        trace_id: str | None = None,
        parent_task_id: str | None = None,
    ) -> dict:
        """创建任务运行记录。

        为什么这里要允许外部透传 `run_id / trace_id / parent_task_id`：
        1. 在传统“Service 直连执行”模式下，任务运行 ID 可以由 Repository 自己生成；
        2. 但在“Supervisor 宏观调度 -> Workflow 微观执行”模式下，
           宏观层已经先创建了统一的 `TaskEnvelope`；
        3. 这时业务工作流必须沿用上游透传的链路标识，才能保证：
           - Supervisor 事件
           - Workflow 内部 task_run
           - SQL Audit / Clarification / Review
           使用同一条 run/trace 链路。
        """

        if self._use_database():
            conversation = self._get_conversation_model(conversation_id)
            if conversation is None:
                raise ValueError(f"Conversation not found: {conversation_id}")
            task_run = TaskRun(
                run_id=run_id or _generate_prefixed_id("run"),
                task_id=_generate_prefixed_id("task"),
                parent_task_id=parent_task_id,
                conversation_id=conversation.id,
                user_id=user_id,
                trace_id=trace_id or _generate_prefixed_id("tr"),
                task_type=task_type,
                route=route,
                selected_agent="mock_chat_agent",
                selected_capability="local_mock_answer",
                risk_level=risk_level,
                review_status=review_status,
                status=status,
                sub_status=sub_status,
                input_snapshot=_sanitize_runtime_snapshot(input_snapshot),
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
        resolved_run_id = run_id or _generate_prefixed_id("run")
        record = {
            "run_id": resolved_run_id,
            "task_id": _generate_prefixed_id("task"),
            "parent_task_id": parent_task_id,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "trace_id": trace_id or _generate_prefixed_id("tr"),
            "task_type": task_type,
            "route": route,
            "selected_agent": "mock_chat_agent",
            "selected_capability": "local_mock_answer",
            "risk_level": risk_level,
            "review_status": review_status,
            "status": status,
            "sub_status": sub_status,
            "input_snapshot": _sanitize_runtime_snapshot(input_snapshot),
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
        _TASK_RUNS[resolved_run_id] = record
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
        """更新任务运行记录。

        边界约束：
        - task_run 是权威运行态，不应承载 workflow 微观大对象；
        - 因此对 input/output/context snapshot 会做一次仓储层裁剪；
        - 这样即使调用方误传 tables / sql_bundle / execution_result，也不会直接落库。
        """

        if "input_snapshot" in updates:
            updates["input_snapshot"] = _sanitize_runtime_snapshot(updates["input_snapshot"])
        if "output_snapshot" in updates:
            updates["output_snapshot"] = _sanitize_runtime_snapshot(updates["output_snapshot"])
        if "context_snapshot" in updates:
            updates["context_snapshot"] = _sanitize_runtime_snapshot(updates["context_snapshot"])

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
        """创建槽位快照。

        slot_snapshot 只服务“补槽后恢复执行”，不是 task_run 的替代品，
        因此这里只保存恢复执行必需的最小槽位状态。
        """

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
            return _sanitize_slot_snapshot_record({
                "run_id": snapshot.run_id,
                "task_type": snapshot.task_type,
                "required_slots": snapshot.required_slots or [],
                "collected_slots": snapshot.collected_slots or {},
                "missing_slots": snapshot.missing_slots or [],
                "min_executable_satisfied": snapshot.min_executable_satisfied,
                "awaiting_user_input": snapshot.awaiting_user_input,
                "resume_step": snapshot.resume_step,
                "updated_at": snapshot.updated_at,
            })

        record = _sanitize_slot_snapshot_record({
            "run_id": run_id,
            "task_type": task_type,
            "required_slots": required_slots,
            "collected_slots": collected_slots,
            "missing_slots": missing_slots,
            "min_executable_satisfied": min_executable_satisfied,
            "awaiting_user_input": awaiting_user_input,
            "resume_step": resume_step,
            "updated_at": _utcnow(),
        })
        _SLOT_SNAPSHOTS[run_id] = record
        return record

    def get_slot_snapshot(self, run_id: str) -> dict | None:
        """读取槽位快照。"""

        if self._use_database():
            statement = select(SlotSnapshot).where(SlotSnapshot.run_id == run_id)
            snapshot = self.session.execute(statement).scalar_one_or_none()
            if snapshot is None:
                return None
            return _sanitize_slot_snapshot_record({
                "run_id": snapshot.run_id,
                "task_type": snapshot.task_type,
                "required_slots": snapshot.required_slots or [],
                "collected_slots": snapshot.collected_slots or {},
                "missing_slots": snapshot.missing_slots or [],
                "min_executable_satisfied": snapshot.min_executable_satisfied,
                "awaiting_user_input": snapshot.awaiting_user_input,
                "resume_step": snapshot.resume_step,
                "updated_at": snapshot.updated_at,
            })

        return _SLOT_SNAPSHOTS.get(run_id)

    def update_slot_snapshot(self, run_id: str, **updates) -> dict | None:
        """更新槽位快照。"""

        updates = _sanitize_slot_snapshot_record(updates)

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
            return _sanitize_slot_snapshot_record({
                "run_id": snapshot.run_id,
                "task_type": snapshot.task_type,
                "required_slots": snapshot.required_slots or [],
                "collected_slots": snapshot.collected_slots or {},
                "missing_slots": snapshot.missing_slots or [],
                "min_executable_satisfied": snapshot.min_executable_satisfied,
                "awaiting_user_input": snapshot.awaiting_user_input,
                "resume_step": snapshot.resume_step,
                "updated_at": snapshot.updated_at,
            })

        record = self.get_slot_snapshot(run_id)
        if record is None:
            return None
        record.update(updates)
        record["updated_at"] = _utcnow()
        record = _sanitize_slot_snapshot_record(record)
        _SLOT_SNAPSHOTS[run_id] = record
        return record

    def create_clarification_event(
        self,
        run_id: str,
        conversation_id: str,
        question_text: str,
        target_slots: list[str],
    ) -> dict:
        """创建澄清事件。

        clarification_event 是“可审计的交互事件”，
        只记录系统提问、目标槽位、用户回复和解析结果，
        不承担微观 workflow 上下文和大对象存储职责。
        """

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
            return _sanitize_clarification_event_record({
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
            })

        now = _utcnow()
        clarification_id = _generate_prefixed_id("clr")
        record = _sanitize_clarification_event_record({
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
        })
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
            return _sanitize_clarification_event_record({
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
            })

        return _CLARIFICATION_EVENTS.get(clarification_id)

    def update_clarification_event(self, clarification_id: str, **updates) -> dict | None:
        """更新澄清事件。"""

        updates = _sanitize_clarification_event_record(updates)

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
            return _sanitize_clarification_event_record({
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
            })

        record = self.get_clarification_event(clarification_id)
        if record is None:
            return None
        record.update(updates)
        record = _sanitize_clarification_event_record(record)
        _CLARIFICATION_EVENTS[clarification_id] = record
        return record
