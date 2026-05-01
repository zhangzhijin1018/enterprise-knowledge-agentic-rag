"""Analytics 局部 ReAct Planner。"""

from __future__ import annotations

from core.agent.control_plane.analytics_planner import AnalyticsPlan, AnalyticsPlanner
from core.agent.workflows.analytics.react.state import (
    AnalyticsReactState,
    ReactActionRecord,
    ReactObservationRecord,
    ReactStepOutput,
)
from core.agent.workflows.analytics.react.tools import AnalyticsReactToolRegistry
from core.agent.workflows.analytics.react.validator import ReactPlanValidator
from core.config.settings import Settings, get_settings
from core.llm import LLMGateway, LLMMessage, OpenAICompatibleLLMGateway
from core.prompts import PromptRegistry, PromptRenderer


class AnalyticsReactPlanner:
    """经营分析 analytics_plan 节点内部的局部 ReAct 子循环。

    这是“局部 ReAct”，不是全链路 ReAct：
    - 只在 planning 阶段工作；
    - 只调用白名单 planning 工具；
    - 最终输出仍然是 `AnalyticsPlan`；
    - 后续执行必须继续走 SQL Builder / SQL Guard / SQL Gateway。
    """

    def __init__(
        self,
        *,
        base_planner: AnalyticsPlanner,
        tool_registry: AnalyticsReactToolRegistry,
        llm_gateway: LLMGateway | None = None,
        prompt_registry: PromptRegistry | None = None,
        prompt_renderer: PromptRenderer | None = None,
        plan_validator: ReactPlanValidator | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.base_planner = base_planner
        self.tool_registry = tool_registry
        self.settings = settings or get_settings()
        self.llm_gateway = llm_gateway or OpenAICompatibleLLMGateway(settings=self.settings)
        self.prompt_registry = prompt_registry or PromptRegistry()
        self.prompt_renderer = prompt_renderer or PromptRenderer()
        self.plan_validator = plan_validator or ReactPlanValidator(
            metric_catalog=base_planner.metric_catalog,
            schema_registry=tool_registry.schema_registry,
        )

    def plan(
        self,
        *,
        query: str,
        conversation_memory: dict | None = None,
        trace_id: str | None = None,
    ) -> tuple[AnalyticsPlan, AnalyticsReactState]:
        """执行局部 ReAct 子循环并产出 AnalyticsPlan。

        ReAct 的每一步只保存轻量 thought/action/observation 摘要。
        如果没有产出可用候选，调用方应回退到确定性 Planner。
        """

        memory = conversation_memory or {}
        react_state = AnalyticsReactState(
            query=query,
            conversation_memory=memory,
            max_steps=self.settings.analytics_react_max_steps,
        )
        system_template = self.prompt_registry.load("analytics/react_planner_system")
        user_template = self.prompt_registry.load("analytics/react_planner_user")

        for step in range(1, react_state.max_steps + 1):
            messages = [
                LLMMessage(
                    role="system",
                    content=self.prompt_renderer.render(system_template, {}),
                ),
                LLMMessage(
                    role="user",
                    content=self.prompt_renderer.render(
                        user_template,
                        {
                            "query": query,
                            "conversation_memory": memory,
                            "steps": self._build_step_view(react_state),
                            "metric_names": self.base_planner.metric_catalog.list_metric_names(),
                            "group_by_keys": ["month", "region", "station"],
                        },
                    ),
                ),
            ]
            step_output = self.llm_gateway.structured_output(
                messages=messages,
                output_schema=ReactStepOutput,
                model=self.settings.llm_model_name,
                timeout_seconds=self.settings.llm_timeout_seconds,
                trace_id=trace_id,
                metadata={
                    "component": "analytics_react_planner",
                    "prompt_name": "analytics/react_planner_user",
                    "prompt_version": "v1",
                    "step": step,
                },
            )
            react_state.thoughts.append(step_output.thought[:300])
            react_state.actions.append(
                ReactActionRecord(
                    step=step,
                    action=step_output.action,
                    action_input=step_output.action_input,
                )
            )
            if step_output.action == "finish":
                react_state.final_plan_candidate = step_output.final_plan_candidate
                react_state.stopped_reason = step_output.stopped_reason or "finished"
                break

            observation = self.tool_registry.run(
                tool_name=step_output.action,
                tool_input=step_output.action_input,
                conversation_memory=memory,
            )
            react_state.observations.append(
                ReactObservationRecord(
                    step=step,
                    action=step_output.action,
                    observation=observation,
                )
            )
            if not observation.get("allowed", False):
                react_state.stopped_reason = f"forbidden_or_unknown_tool:{step_output.action}"
                break
        else:
            react_state.stopped_reason = "max_steps_reached"

        if react_state.final_plan_candidate is None:
            raise RuntimeError(f"ReAct planner 未产出可用候选：{react_state.stopped_reason}")

        candidate = react_state.final_plan_candidate
        # LLM 输出进入 AnalyticsPlan 前必须二次校验。
        # Prompt 只能作为软约束，Validator 才是工程侧的硬边界：
        # - 去掉非白名单字段；
        # - 拦截 SQL / task_run_update / review / export 等越界意图；
        # - 校验 metric / group_by / compare_target / top_n 等槽位是否可控。
        safe_slots = self.plan_validator.validate(candidate.slots)
        plan = self.base_planner.build_plan_from_slots(
            slots=safe_slots,
            planning_source="react_planner",
            confidence=candidate.confidence,
        )
        return plan, react_state

    def _build_step_view(self, react_state: AnalyticsReactState) -> list[dict]:
        """构造给下一步 prompt 使用的轻量历史。"""

        observations = {item.step: item for item in react_state.observations}
        return [
            {
                "step": action.step,
                "action": action.action,
                "action_input": action.action_input,
                "observation": observations.get(action.step).observation if observations.get(action.step) else {},
            }
            for action in react_state.actions
        ]
