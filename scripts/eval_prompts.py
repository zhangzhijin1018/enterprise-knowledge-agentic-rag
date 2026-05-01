"""Prompt Evaluation 最小离线脚本。

当前脚本不调用真实 LLM，也不要求 API Key。
它的目标是先把 Prompt 验收数据集和执行入口搭起来：
1. 校验 JSONL case 可读取；
2. 用确定性规则/Validator 验证禁止行为不会进入安全 slots；
3. 输出一份简单 Markdown 结果，供后续接真实模型或 RAGAS 时复用。

后续如果要接真实模型，只需要在 runner 内替换为 LLMGateway + Mock/真实 Gateway，
不要把模型 SDK 直接写进业务代码。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.agent.control_plane.analytics_slot_fallback_validator import AnalyticsSlotFallbackValidator
from core.agent.workflows.analytics.react.policy import AnalyticsReactPlanningPolicy
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.config.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
SLOT_CASES = ROOT / "evals" / "analytics_slot_fallback_cases.jsonl"
REACT_CASES = ROOT / "evals" / "analytics_react_planning_cases.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取 JSONL 评估用例。"""

    cases: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        cases.append(json.loads(line))
    return cases


def _run_slot_eval(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """运行 slot fallback 的确定性验收。

    这里不模拟完整 LLM，而是把 expected_slots 送进 Validator，
    验证数据集里的“期望安全槽位”符合当前硬边界。
    """

    validator = AnalyticsSlotFallbackValidator(
        metric_catalog=MetricCatalog(),
        schema_registry=SchemaRegistry(settings=Settings()),
    )
    rows: list[dict[str, Any]] = []
    for case in cases:
        try:
            safe_slots = validator.validate(case.get("expected_slots") or {})
            passed = bool(safe_slots)
            reason = "validator_passed"
        except Exception as exc:  # noqa: BLE001 - eval 脚本需要汇总所有 case，不因单条失败中断
            passed = False
            reason = f"validator_failed:{type(exc).__name__}:{exc}"
        rows.append(
            {
                "case_id": case["case_id"],
                "task_type": case["task_type"],
                "passed": passed,
                "reason": reason,
            }
        )
    return rows


def _run_react_eval(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """运行 ReAct planning 的确定性策略验收。

    当前只验证 policy 是否符合预期：简单问题不走 ReAct，复杂问题在开关开启时可走 ReAct。
    后续接真实模型时，可在这里加入 MockLLMGateway / 真实 LLMGateway 输出评测。
    """

    policy = AnalyticsReactPlanningPolicy(settings=Settings(analytics_react_planner_enabled=True))
    rows: list[dict[str, Any]] = []
    for case in cases:
        should_use_react = policy.should_use_react(query=case["query"], conversation_memory={})
        expected_behavior = case.get("expected_behavior")
        if expected_behavior == "simple_query_should_not_use_react":
            passed = should_use_react is False
        else:
            passed = should_use_react is True
        rows.append(
            {
                "case_id": case["case_id"],
                "task_type": case["task_type"],
                "passed": passed,
                "reason": f"should_use_react={should_use_react}",
            }
        )
    return rows


def main() -> None:
    """输出最小 Prompt Evaluation 结果。"""

    rows = [
        *_run_slot_eval(_read_jsonl(SLOT_CASES)),
        *_run_react_eval(_read_jsonl(REACT_CASES)),
    ]
    print("| case_id | task_type | passed | reason |")
    print("|---|---|---:|---|")
    for row in rows:
        print(f"| {row['case_id']} | {row['task_type']} | {row['passed']} | {row['reason']} |")


if __name__ == "__main__":
    main()
