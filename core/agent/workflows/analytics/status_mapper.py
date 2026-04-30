"""经营分析微观状态到 Supervisor 宏观状态的映射层。

为什么不能把微观状态直接暴露给 Supervisor：
1. `analytics_build_sql / analytics_guard_sql / analytics_execute_sql` 这类状态只对经营分析专家有意义；
2. Supervisor 只需要知道任务是在执行、等待澄清、等待审核还是已经完成；
3. 如果宏观层直接依赖微观 node 名称，后续每个业务专家都需要把内部细节暴露出来，边界会迅速失控。

为什么 clarification 不是失败：
1. clarification 表示“缺少必要输入，等待用户补充”；
2. 它是标准可恢复中间态；
3. 如果把它建模成 failed，后续就无法自然表达“用户补完后继续恢复执行”。

为什么 review 是标准中断态：
1. review 不是业务逻辑失败；
2. 它表示当前流程被治理策略主动暂停；
3. 通过后可继续执行，拒绝后才终止，因此必须独立建模。
"""

from __future__ import annotations

from core.agent.supervisor.status import (
    SupervisorStatus,
    SupervisorSubStatus,
    build_supervisor_status_contract,
)
from core.agent.workflows.analytics.state import (
    AnalyticsWorkflowOutcome,
    AnalyticsWorkflowStage,
    AnalyticsWorkflowState,
)
from core.tools.a2a.contracts import StatusContract


class AnalyticsWorkflowStatusMapper:
    """经营分析微观状态映射器。"""

    @staticmethod
    def map_to_supervisor_status(state: AnalyticsWorkflowState) -> StatusContract:
        """把经营分析 workflow state 映射成 Supervisor 可理解的状态摘要。

        说明：
        - 这里输出的不是业务完整结果，而是宏观调度层需要理解的最小状态；
        - ResultContract 会携带完整 output_payload，状态摘要只负责表达生命周期语义。
        """

        outcome = state.get("workflow_outcome")
        stage = state.get("workflow_stage")

        if state.get("review_required") or outcome == AnalyticsWorkflowOutcome.REVIEW:
            return build_supervisor_status_contract(
                status=SupervisorStatus.WAITING_REVIEW,
                sub_status=SupervisorSubStatus.AWAITING_REVIEWER,
                review_status="pending",
                message="经营分析子 Agent 命中审核要求，当前进入等待审核状态",
            )

        if state.get("clarification_needed") or outcome == AnalyticsWorkflowOutcome.CLARIFY:
            return build_supervisor_status_contract(
                status=SupervisorStatus.AWAITING_USER_CLARIFICATION,
                sub_status=SupervisorSubStatus.AWAITING_USER_INPUT,
                message="经营分析子 Agent 缺少必要槽位，等待用户补充信息",
            )

        if outcome == AnalyticsWorkflowOutcome.FAIL:
            return build_supervisor_status_contract(
                status=SupervisorStatus.FAILED,
                sub_status=SupervisorSubStatus.TERMINAL_FAILURE,
                message="经营分析子 Agent 执行失败",
            )

        if stage == AnalyticsWorkflowStage.ANALYTICS_FINISH and outcome == AnalyticsWorkflowOutcome.FINISH:
            return build_supervisor_status_contract(
                status=SupervisorStatus.SUCCEEDED,
                sub_status=SupervisorSubStatus.COLLECTING_RESULT,
                message="经营分析子 Agent 已完成执行并返回最终结果",
            )

        return build_supervisor_status_contract(
            status=SupervisorStatus.EXECUTING,
            sub_status=SupervisorSubStatus.COLLECTING_RESULT,
            message="经营分析子 Agent 正在执行微观工作流",
        )
