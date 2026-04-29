"""Supervisor 宏观调度服务。

Supervisor 是“谁来做”的决策层，不是“怎么做”的执行层。

这一层当前只负责：
1. 接收业务请求；
2. 解析目标业务专家；
3. 构造 TaskEnvelope；
4. 调用本地专家样板或 A2A-ready 委托；
5. 汇总标准化结果。

为什么不能把微观业务逻辑写进这里：
1. Supervisor 如果掺杂经营分析 SQL / 合同规则 / RAG 检索细节，就会迅速膨胀成万能 God Service；
2. 宏观调度与微观执行分层后，后续每个业务专家都可以独立演进 workflow；
3. 这正是“A2A 宏观调度 + LangGraph 微观执行”的核心边界。
"""

from __future__ import annotations

from core.agent.supervisor.delegation_controller import DelegationController
from core.runtime.events import EventBus, InMemoryEventBus
from core.tools.a2a import ResultContract, StatusContract


class SupervisorService:
    """最小 Supervisor 宏观调度服务。"""

    def __init__(
        self,
        *,
        delegation_controller: DelegationController,
        event_bus: EventBus | None = None,
    ) -> None:
        self.delegation_controller = delegation_controller
        self.event_bus = event_bus or InMemoryEventBus()

    def handle_request(
        self,
        *,
        task_type: str,
        input_payload: dict,
        source_agent: str = "supervisor",
        parent_task_id: str | None = None,
    ) -> ResultContract:
        """接收一个业务请求，并完成最小宏观调度。

        当前阶段先支持：
        - 本地经营分析专家样板；
        - A2A-ready 远程委托占位；
        - 基于事件总线发布最小 task_submitted / task_finished 事件。
        """

        target = self.delegation_controller.resolve_target(task_type)
        envelope = self.delegation_controller.build_envelope(
            task_type=task_type,
            source_agent=source_agent,
            target_agent=target.agent_card.agent_name,
            input_payload=input_payload,
            parent_task_id=parent_task_id,
        )
        self.event_bus.publish(
            stream="supervisor.tasks",
            event_type="task_submitted",
            payload={
                "task_type": task_type,
                "source_agent": source_agent,
                "target_agent": target.agent_card.agent_name,
            },
            trace_id=envelope.trace_id,
            run_id=envelope.run_id,
        )

        result = self.delegation_controller.dispatch(envelope)

        self.event_bus.publish(
            stream="supervisor.tasks",
            event_type="task_finished",
            payload={
                "task_type": task_type,
                "target_agent": result.target_agent,
                "status": result.status.status,
                "sub_status": result.status.sub_status,
            },
            trace_id=result.trace_id,
            run_id=result.run_id,
        )
        return result

    def handle_local_failure(
        self,
        *,
        task_type: str,
        message: str,
        source_agent: str = "supervisor",
    ) -> ResultContract:
        """构造最小失败结果。

        当前方法主要用于保留 Supervisor 层“统一失败结果”的输出形状。
        """

        target = self.delegation_controller.resolve_target(task_type)
        envelope = self.delegation_controller.build_envelope(
            task_type=task_type,
            source_agent=source_agent,
            target_agent=target.agent_card.agent_name,
            input_payload={},
        )
        return ResultContract(
            run_id=envelope.run_id,
            trace_id=envelope.trace_id,
            parent_task_id=envelope.parent_task_id,
            task_type=task_type,
            source_agent=source_agent,
            target_agent=target.agent_card.agent_name,
            status=StatusContract(status="failed", sub_status="supervisor_failure", message=message),
            output_payload={},
            error={"message": message},
        )
