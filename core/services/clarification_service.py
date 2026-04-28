"""澄清恢复 Service。"""

from __future__ import annotations

from datetime import datetime, timezone

from apps.api.schemas.clarification import ClarificationReplyRequest
from core.common import error_codes
from core.common.exceptions import AppException
from core.common.response import build_response_meta
from core.repositories.conversation_repository import ConversationRepository
from core.repositories.task_run_repository import TaskRunRepository
from core.security.auth import UserContext


class ClarificationService:
    """处理澄清回复与最小恢复执行。"""

    def __init__(
        self,
        conversation_repository: ConversationRepository,
        task_run_repository: TaskRunRepository,
    ) -> None:
        """显式注入仓储依赖。"""

        self.conversation_repository = conversation_repository
        self.task_run_repository = task_run_repository

    def reply(
        self,
        clarification_id: str,
        payload: ClarificationReplyRequest,
        user_context: UserContext,
    ) -> dict:
        """处理用户澄清回复。

        当前阶段先演示最小恢复流程：
        1. 找到澄清事件；
        2. 校验当前用户是否有权处理该澄清；
        2. 更新槽位快照；
        3. 记录用户补充消息；
        4. 追加一条 mock 恢复执行结果；
        5. 更新 task run 状态。
        """

        clarification_event = self.task_run_repository.get_clarification_event(clarification_id)
        if clarification_event is None:
            raise AppException(
                error_code=error_codes.CLARIFICATION_NOT_FOUND,
                message="指定澄清事件不存在",
                status_code=404,
                detail={"clarification_id": clarification_id},
            )

        conversation = self.conversation_repository.get_conversation(
            clarification_event["conversation_id"]
        )
        if conversation is None:
            raise AppException(
                error_code=error_codes.CONVERSATION_NOT_FOUND,
                message="澄清事件关联的会话不存在",
                status_code=404,
                detail={
                    "clarification_id": clarification_id,
                    "conversation_id": clarification_event["conversation_id"],
                },
            )

        # 澄清回复本质上仍然是在补充用户自己的会话上下文。
        # 如果这里不校验 owner，攻击者只要猜到 clarification_id，
        # 就有机会篡改他人的槽位信息和后续回答。
        if conversation["user_id"] != user_context.user_id:
            raise AppException(
                error_code=error_codes.PERMISSION_DENIED,
                message="当前用户无权回复该澄清事件",
                status_code=403,
                detail={
                    "clarification_id": clarification_id,
                    "conversation_id": clarification_event["conversation_id"],
                    "resource_type": "clarification",
                    "owner_user_id": conversation["user_id"],
                    "current_user_id": user_context.user_id,
                },
            )

        # 当前阶段澄清回复仍然是最小规则式解析，
        # 但不能再把所有回复都硬编码成 metric。
        # 否则经营分析如果追问的是 time_range，这里会把用户回答错误地写进 metric。
        target_slots = clarification_event.get("target_slots") or []
        primary_target_slot = target_slots[0] if target_slots else "metric"
        resolved_slots = {primary_target_slot: payload.reply}
        now = datetime.now(timezone.utc)

        self.task_run_repository.update_clarification_event(
            clarification_id,
            user_reply=payload.reply,
            resolved_slots=resolved_slots,
            status="resolved",
            resolved_at=now,
        )

        self.task_run_repository.update_slot_snapshot(
            clarification_event["run_id"],
            collected_slots=resolved_slots,
            missing_slots=[],
            min_executable_satisfied=True,
            awaiting_user_input=False,
        )

        self.conversation_repository.add_message(
            conversation_id=clarification_event["conversation_id"],
            role="user",
            message_type="clarification_reply",
            content=payload.reply,
            related_run_id=clarification_event["run_id"],
        )

        resumed_answer = (
            f"已收到你补充的{primary_target_slot}信息“{payload.reply}”。"
            "当前系统继续执行最小 mock 流程，"
            "后续这里会替换为真实工作流恢复与结果生成逻辑。"
        )

        self.conversation_repository.add_message(
            conversation_id=clarification_event["conversation_id"],
            role="assistant",
            message_type="answer",
            content=resumed_answer,
            related_run_id=clarification_event["run_id"],
        )

        self.conversation_repository.upsert_memory(
            clarification_event["conversation_id"],
            last_route="chat",
            last_metric=payload.reply if primary_target_slot == "metric" else None,
            last_time_range={"label": payload.reply} if primary_target_slot == "time_range" else {},
            short_term_memory={
                "last_status": "succeeded_after_clarification",
                "clarification_id": clarification_id,
                "resolved_slot_name": primary_target_slot,
            },
        )

        self.task_run_repository.update_task_run(
            clarification_event["run_id"],
            status="succeeded",
            sub_status="resumed_after_clarification",
            output_snapshot={"answer": resumed_answer, "resolved_slots": resolved_slots},
            finished_at=now,
        )

        return {
            "data": {
                "message": "已收到补充信息，任务继续执行",
            },
            "meta": build_response_meta(
                conversation_id=clarification_event["conversation_id"],
                run_id=clarification_event["run_id"],
                status="succeeded",
                sub_status="resumed_after_clarification",
                need_clarification=False,
                is_async=False,
            ),
        }
