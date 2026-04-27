"""任务路由控制模块。

当前阶段仍然不用真实 LLM 路由，
但先把“根据问题内容做可解释路由”从 workflow 主文件里抽离出来，
这样后续无论替换为规则引擎、分类模型还是 LangGraph node，
外围工作流入口都不需要大改。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TaskRoutingDecision:
    """任务路由决策结果。"""

    # 当前问题应进入的主业务路由。
    route: str

    # 更偏业务语义层的领域标记。
    business_domain: str

    # 当前阶段占位业务 Agent 名称。
    selected_agent: str

    # 当前阶段占位能力名称。
    selected_capability: str

    # 是否需要先进入澄清补槽流程。
    need_clarification: bool


class TaskRouter:
    """最小任务路由器。"""

    def route(self, query: str) -> TaskRoutingDecision:
        """根据用户问题返回最小路由结果。"""

        if self.should_require_clarification(query):
            return TaskRoutingDecision(
                route="business_analysis",
                business_domain="analytics",
                selected_agent="mock_business_analysis_agent",
                selected_capability="clarification_workflow",
                need_clarification=True,
            )

        if any(keyword in query for keyword in ("制度", "政策", "规程")):
            return TaskRoutingDecision(
                route="policy_qa",
                business_domain="policy",
                selected_agent="mock_policy_agent",
                selected_capability="mock_rag_answer",
                need_clarification=False,
            )

        return TaskRoutingDecision(
            route="general_qa",
            business_domain="general",
            selected_agent="mock_general_agent",
            selected_capability="mock_direct_answer",
            need_clarification=False,
        )

    def should_require_clarification(self, query: str) -> bool:
        """判断是否需要先追问澄清。

        当前采用最小可解释规则：
        - 经营分析类问题如果没说明核心指标，则先补槽；
        - 明示“澄清 / clarify”也视为需要进入澄清分支。
        """

        normalized_query = query.lower()
        analytics_keywords = ("分析", "统计", "指标", "经营", "趋势")
        known_metrics = ("发电量", "收入", "成本", "利润", "产量")

        if any(keyword in query for keyword in analytics_keywords) and not any(
            metric in query for metric in known_metrics
        ):
            return True

        if "clarify" in normalized_query or "澄清" in query:
            return True

        return False
