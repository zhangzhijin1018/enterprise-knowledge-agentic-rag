"""Supervisor 宏观状态定义。

这一层定义的是 **宏观调度层** 的状态，而不是经营分析内部的 SQL / clarification / summarize 节点状态。

设计原则：
1. Supervisor 只关心任务生命周期；
2. 不把业务专家内部的微观执行细节泄漏到宏观层；
3. clarification / review / waiting_remote 都被视为“标准中断态”，而不是简单失败。
"""

from __future__ import annotations

from enum import Enum

class SupervisorStatus(str, Enum):
    """Supervisor 宏观主状态。

    这些状态描述的是“宏观调度层看到的任务现在处于什么阶段”。
    """

    # 任务刚刚被 Supervisor 接收，尚未完成本地/远程派单。
    # 这是宏观层的起始态，属于可继续推进的短暂中间态。
    CREATED = "created"

    # 任务已经完成目标解析并被派发出去。
    # 该状态属于宏观层的可恢复中间态，后续会继续进入 executing / waiting_remote。
    DISPATCHED = "dispatched"

    # 任务正在目标业务专家内部执行。
    # 这里不区分 SQL build、guard、execute 等微观细节，只表达“子 Agent 正在干活”。
    EXECUTING = "executing"

    # 任务缺少必要槽位，正在等待用户澄清补充信息。
    # 这是标准可恢复中间态，不应被误判成 failed。
    AWAITING_USER_CLARIFICATION = "awaiting_user_clarification"

    # 任务已经被委托给远程专家，但结果尚未返回。
    # 这是宏观层保留给 A2A 远程执行链路的标准等待态。
    WAITING_REMOTE = "waiting_remote"

    # 任务命中了人工审核策略，正在等待 reviewer 决策。
    # 这也是标准中断态，而不是成功或失败。
    WAITING_REVIEW = "waiting_review"

    # 任务成功完成，Supervisor 已经拿到稳定业务结果。
    SUCCEEDED = "succeeded"

    # 任务执行失败，且当前没有进入可恢复等待态。
    FAILED = "failed"

    # 任务被显式取消。
    CANCELLED = "cancelled"

    # 任务因超时、等待过久等原因过期。
    EXPIRED = "expired"


class SupervisorSubStatus(str, Enum):
    """Supervisor 宏观子状态。

    子状态用于表达宏观层的更细粒度阶段，但仍然不暴露业务专家内部 node 细节。
    """

    # Supervisor 正在做任务类型识别、目标专家解析、基础风控判断。
    ROUTING = "routing"

    # Supervisor 准备把任务交给本地业务专家 handler。
    DELEGATING_LOCAL = "delegating_local"

    # Supervisor 准备把任务交给远程 A2A 专家。
    DELEGATING_REMOTE = "delegating_remote"

    # Supervisor 已经拿到子 Agent 执行结果，正在做标准化封装与结果汇总。
    COLLECTING_RESULT = "collecting_result"

    # 远程专家结果尚未返回，仍处于等待态。
    AWAITING_REMOTE_RESULT = "awaiting_remote_result"

    # 正在等待 reviewer 处理审核任务。
    AWAITING_REVIEWER = "awaiting_reviewer"

    # 当前任务因为缺少用户输入而暂停，等待用户继续补全。
    AWAITING_USER_INPUT = "awaiting_user_input"

    # 当前任务在宏观层被认定为失败。
    TERMINAL_FAILURE = "terminal_failure"


def build_supervisor_status_contract(
    *,
    status: SupervisorStatus,
    sub_status: SupervisorSubStatus | None = None,
    review_status: str | None = None,
    message: str | None = None,
) -> "StatusContract":
    """构造标准化 Supervisor 状态契约。

    为什么要集中构造：
    1. 避免在多个模块里散落字符串常量；
    2. 统一 Supervisor 对外暴露的状态形状；
    3. 后续如果要补更多审计字段或可观测性字段，可以集中演进。
    """

    from core.tools.a2a.contracts.models import StatusContract

    return StatusContract(
        status=status.value,
        sub_status=sub_status.value if sub_status is not None else None,
        review_status=review_status,
        message=message,
    )
