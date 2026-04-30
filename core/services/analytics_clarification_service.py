"""经营分析 clarification 恢复 Service。

这层只负责经营分析自己的澄清恢复闭环，不扩展到其他子 Agent。

关键设计：
1. clarification 是可恢复中间态，不是 failed；
2. 恢复执行不是恢复原 Python 线程，而是基于：
   - clarification_event
   - slot_snapshot
   - task_run
   重新进入经营分析 workflow；
3. clarification_event 和 slot_snapshot 必须同时存在：
   - clarification_event 负责保存“系统怎么问、用户怎么答、解析出了什么”；
   - slot_snapshot 负责保存“当前还缺什么、是否满足最小可执行条件、下一步从哪恢复”。
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.common import error_codes
from core.common.exceptions import AppException
from core.common.response import build_response_meta
from core.repositories.conversation_repository import ConversationRepository
from core.repositories.task_run_repository import TaskRunRepository
from core.security.auth import UserContext
from core.services.analytics_service import AnalyticsService


class AnalyticsClarificationService:
    """经营分析澄清恢复应用服务。"""

    def __init__(
        self,
        *,
        conversation_repository: ConversationRepository,
        task_run_repository: TaskRunRepository,
        analytics_service: AnalyticsService,
    ) -> None:
        self.conversation_repository = conversation_repository
        self.task_run_repository = task_run_repository
        self.analytics_service = analytics_service

    def get_detail(self, clarification_id: str, user_context: UserContext) -> dict:
        """读取经营分析澄清详情。"""

        clarification_event, task_run, _slot_snapshot, conversation = self._load_context(
            clarification_id=clarification_id,
            user_context=user_context,
        )
        return {
            "data": {
                "clarification_id": clarification_event["clarification_id"],
                "run_id": clarification_event["run_id"],
                "conversation_id": clarification_event["conversation_id"],
                "question": clarification_event["question_text"],
                "target_slots": clarification_event.get("target_slots") or [],
                "user_reply": clarification_event.get("user_reply"),
                "resolved_slots": clarification_event.get("resolved_slots") or {},
                "status": clarification_event["status"],
                "created_at": clarification_event["created_at"],
                "resolved_at": clarification_event.get("resolved_at"),
            },
            "meta": build_response_meta(
                conversation_id=conversation["conversation_id"],
                run_id=task_run["run_id"],
                status=task_run["status"],
                sub_status=task_run["sub_status"],
                is_async=False,
            ),
        }

    def reply(
        self,
        *,
        clarification_id: str,
        reply: str,
        user_context: UserContext,
        output_mode: str | None = None,
        need_sql_explain: bool | None = None,
    ) -> dict:
        """处理经营分析 clarification 回复并恢复 workflow。

        这里恢复的是“业务状态机”，不是恢复旧线程。
        真正的恢复动作是：
        1. 读取原始 run 和补槽快照；
        2. 合并用户补充出来的新槽位；
        3. 重新判断最小可执行条件；
        4. 如果仍不满足，继续进入 clarification；
        5. 如果满足，则复用原 `run_id` 重新进入 Analytics StateGraph。
        """

        normalized_reply = reply.strip()
        if not normalized_reply:
            raise AppException(
                error_code=error_codes.ANALYTICS_QUERY_FAILED,
                message="澄清补充内容不能为空",
                status_code=400,
                detail={},
            )

        clarification_event, task_run, slot_snapshot, conversation = self._load_context(
            clarification_id=clarification_id,
            user_context=user_context,
        )
        if clarification_event["status"] != "pending":
            raise AppException(
                error_code=error_codes.ANALYTICS_QUERY_FAILED,
                message="该澄清事件已经处理，不能重复回复",
                status_code=409,
                detail={
                    "clarification_id": clarification_id,
                    "status": clarification_event["status"],
                },
            )

        original_query = (task_run.get("input_snapshot") or {}).get("query")
        if not original_query:
            raise AppException(
                error_code=error_codes.ANALYTICS_QUERY_FAILED,
                message="原始经营分析问题缺失，无法恢复执行",
                status_code=500,
                detail={"run_id": task_run["run_id"]},
            )

        memory = self.conversation_repository.get_memory(conversation["conversation_id"])
        resolution = self.analytics_service.analytics_planner.semantic_resolver.resolve(
            query=normalized_reply,
            conversation_memory=memory,
        )
        resolved_slots = {
            key: value
            for key, value in resolution.slots.items()
            if key
            in {
                "metric",
                "time_range",
                "org_scope",
                "group_by",
                "compare_target",
                "top_n",
                "sort_direction",
                "secondary_metrics",
                "metric_candidates",
            }
        }
        merged_slots = dict(slot_snapshot.get("collected_slots") or {})
        merged_slots.update(resolved_slots)
        resumed_plan = self.analytics_service.analytics_planner.build_plan_from_slots(
            slots=merged_slots,
            planning_source=f"clarification_resume+{resolution.planning_source}",
            confidence=max(0.8, resolution.confidence),
        )
        now = datetime.now(timezone.utc)

        self.task_run_repository.update_clarification_event(
            clarification_id,
            user_reply=normalized_reply,
            resolved_slots=resolved_slots,
            status="resolved",
            resolved_at=now,
        )
        self.task_run_repository.update_slot_snapshot(
            task_run["run_id"],
            **self.analytics_service.snapshot_builder.build_slot_snapshot_payload(plan=resumed_plan),
        )
        self.conversation_repository.add_message(
            conversation_id=conversation["conversation_id"],
            role="user",
            message_type="analytics_clarification_reply",
            content=normalized_reply,
            related_run_id=task_run["run_id"],
            structured_content={"clarification_id": clarification_id, "resolved_slots": resolved_slots},
        )

        if not resumed_plan.is_executable:
            return self.analytics_service._build_clarification_response(
                conversation_id=conversation["conversation_id"],
                task_run=task_run,
                plan=resumed_plan,
            )

        self.task_run_repository.update_task_run(
            task_run["run_id"],
            status="executing",
            sub_status="resumed_after_clarification",
            error_code=None,
            error_message=None,
            context_snapshot=self.analytics_service.snapshot_builder.build_context_snapshot(
                slots=resumed_plan.slots,
                planning_source=resumed_plan.planning_source,
                confidence=resumed_plan.confidence,
                resume_step="run_sql_pipeline",
            ),
        )

        if self.analytics_service.workflow_adapter is None:
            raise AppException(
                error_code=error_codes.ANALYTICS_QUERY_FAILED,
                message="当前未配置经营分析 workflow adapter，无法恢复执行",
                status_code=500,
                detail={"run_id": task_run["run_id"]},
            )

        resumed_result = self.analytics_service.workflow_adapter.resume_from_clarification(
            query=original_query,
            user_context=user_context,
            conversation_id=conversation["conversation_id"],
            run_id=task_run["run_id"],
            trace_id=task_run["trace_id"],
            output_mode=output_mode or (task_run.get("input_snapshot") or {}).get("output_mode") or "lite",
            need_sql_explain=(
                need_sql_explain
                if need_sql_explain is not None
                else bool((task_run.get("input_snapshot") or {}).get("need_sql_explain", False))
            ),
            recovered_plan=resumed_plan,
            existing_task_run=self.task_run_repository.get_task_run(task_run["run_id"]) or task_run,
            parent_task_id=task_run.get("parent_task_id"),
        )
        resumed_result["meta"]["sub_status"] = "resumed_after_clarification"
        return resumed_result

    def _load_context(
        self,
        *,
        clarification_id: str,
        user_context: UserContext,
    ) -> tuple[dict, dict, dict, dict]:
        """统一加载并校验 clarification 恢复上下文。"""

        clarification_event = self.task_run_repository.get_clarification_event(clarification_id)
        if clarification_event is None:
            raise AppException(
                error_code=error_codes.CLARIFICATION_NOT_FOUND,
                message="指定经营分析澄清事件不存在",
                status_code=404,
                detail={"clarification_id": clarification_id},
            )
        task_run = self.task_run_repository.get_task_run(clarification_event["run_id"])
        if task_run is None or task_run["task_type"] != "analytics":
            raise AppException(
                error_code=error_codes.ANALYTICS_RUN_NOT_FOUND,
                message="澄清事件关联的经营分析任务不存在",
                status_code=404,
                detail={"clarification_id": clarification_id, "run_id": clarification_event["run_id"]},
            )
        slot_snapshot = self.task_run_repository.get_slot_snapshot(task_run["run_id"])
        if slot_snapshot is None:
            raise AppException(
                error_code=error_codes.ANALYTICS_QUERY_FAILED,
                message="经营分析槽位恢复快照不存在，无法恢复执行",
                status_code=500,
                detail={"run_id": task_run["run_id"]},
            )
        conversation = self.conversation_repository.get_conversation(clarification_event["conversation_id"])
        if conversation is None:
            raise AppException(
                error_code=error_codes.CONVERSATION_NOT_FOUND,
                message="经营分析澄清关联的会话不存在",
                status_code=404,
                detail={"conversation_id": clarification_event["conversation_id"]},
            )
        if conversation["user_id"] != user_context.user_id:
            raise AppException(
                error_code=error_codes.PERMISSION_DENIED,
                message="当前用户无权处理该经营分析澄清",
                status_code=403,
                detail={
                    "clarification_id": clarification_id,
                    "conversation_id": clarification_event["conversation_id"],
                    "owner_user_id": conversation["user_id"],
                    "current_user_id": user_context.user_id,
                },
            )
        return clarification_event, task_run, slot_snapshot, conversation
