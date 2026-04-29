"""A2A 宏观调度契约测试。"""

from __future__ import annotations

from core.tools.a2a import AgentCardRef, DelegationTarget, ResultContract, StatusContract, TaskEnvelope


def test_a2a_contracts_can_be_constructed() -> None:
    """TaskEnvelope / ResultContract 应可最小构造。"""

    agent_card = AgentCardRef(
        agent_name="analytics_expert",
        description="经营分析专家",
        capabilities=["business_analysis"],
        execution_mode="local",
    )
    target = DelegationTarget(
        task_type="business_analysis",
        route_key="analytics",
        agent_card=agent_card,
        preferred_transport="local",
    )
    envelope = TaskEnvelope(
        run_id="sup_001",
        trace_id="tr_001",
        parent_task_id=None,
        task_type="business_analysis",
        source_agent="supervisor",
        target_agent=target.agent_card.agent_name,
        input_payload={"query": "帮我分析一下上个月新疆区域发电量"},
    )
    result = ResultContract(
        run_id="run_001",
        trace_id="tr_001",
        parent_task_id="sup_001",
        task_type="business_analysis",
        source_agent="supervisor",
        target_agent="analytics_expert",
        status=StatusContract(status="succeeded", sub_status="explaining_result"),
        output_payload={"data": {"summary": "ok"}},
    )

    assert envelope.task_type == "business_analysis"
    assert envelope.trace_id == "tr_001"
    assert result.status.status == "succeeded"
    assert result.output_payload["data"]["summary"] == "ok"
