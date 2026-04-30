"""A2A Gateway 最小抽象。

当前阶段不是完整远程分布式 A2A 系统，而是先把网关边界稳定下来：
1. Supervisor 不直接关心目标专家到底是本地 workflow 还是远端服务；
2. Gateway 统一接收 TaskEnvelope，统一返回 ResultContract；
3. 后续如果切到 HTTP/JSON、Redis Streams 事件驱动或独立远端进程，
   只需要替换 Gateway 内部 transport，而不需要改上层宏观调度代码。
"""

from __future__ import annotations

from typing import Callable

from core.agent.supervisor.status import (
    SupervisorStatus,
    SupervisorSubStatus,
    build_supervisor_status_contract,
)
from core.tools.a2a.contracts import ResultContract, TaskEnvelope


class A2AGateway:
    """A2A Gateway 最小实现。

    当前支持两种模式：
    - 本地 handler 调用：用于第一轮样板接线；
    - 远端委托占位：用于保留 A2A-ready 边界。
    """

    def delegate_local(
        self,
        *,
        envelope: TaskEnvelope,
        local_handler: Callable[[TaskEnvelope], ResultContract],
    ) -> ResultContract:
        """把任务委托给本地业务专家样板。"""

        return local_handler(envelope)

    def delegate_remote_ready(self, *, envelope: TaskEnvelope) -> ResultContract:
        """远端委托占位。

        第一轮只保留契约边界，不直接接完整远端 transport。
        """

        return ResultContract(
            run_id=envelope.run_id,
            trace_id=envelope.trace_id,
            parent_task_id=envelope.parent_task_id,
            task_type=envelope.task_type,
            source_agent=envelope.source_agent,
            target_agent=envelope.target_agent,
            status=build_supervisor_status_contract(
                status=SupervisorStatus.WAITING_REMOTE,
                sub_status=SupervisorSubStatus.AWAITING_REMOTE_RESULT,
                message="当前阶段仅完成 A2A-ready 委托边界，尚未接入真实远端 transport",
            ),
            output_payload={},
            error=None,
        )
