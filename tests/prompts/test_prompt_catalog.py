"""Prompt Catalog 治理测试。"""

from __future__ import annotations

import re

from core.prompts import PromptRegistry, list_prompt_catalog
from core.prompts.renderer import PromptRenderer


_VAR_PATTERN = re.compile(r"{{\s*([\w.]+)\s*}}")


def _sample_variables() -> dict:
    """为 catalog 中所有 prompt 准备可渲染的测试变量。"""

    return {
        "query": "最近收入同比对比",
        "conversation_memory": {"last_metric": "收入"},
        "steps": [],
        "metric_names": ["收入", "成本", "利润", "发电量"],
        "group_by_keys": ["month", "region", "station"],
        "current_slots": {"time_range": {"label": "近一个月"}},
        "allowed_slots": ["metric", "time_range", "group_by"],
    }


def test_prompt_catalog_templates_exist() -> None:
    """Catalog 中登记的 Prompt 必须都能被 Registry 加载。

    这个测试用于防止后续只改 catalog 不补模板，或移动模板后忘记更新登记项。
    """

    registry = PromptRegistry()

    for entry in list_prompt_catalog():
        assert registry.load(entry.name)
        assert entry.domain
        assert entry.output_schema


def test_prompt_catalog_entries_have_governance_fields() -> None:
    """每个 Prompt 登记项都必须包含生产治理字段。"""

    for entry in list_prompt_catalog():
        assert entry.name
        assert entry.domain
        assert entry.purpose
        assert entry.input_variables is not None
        assert entry.output_schema
        assert entry.risk_level
        assert entry.owner
        assert entry.version


def test_prompt_catalog_declares_all_template_variables() -> None:
    """模板中出现的变量必须在 catalog 中声明。

    catalog 声明了但模板暂未使用的变量允许存在，因为生产治理中常会提前声明
    兼容变量，便于后续模板版本灰度；但反过来不允许模板偷偷新增未登记变量。
    """

    registry = PromptRegistry()

    for entry in list_prompt_catalog():
        template = registry.load(entry.name)
        template_vars = {match.group(1) for match in _VAR_PATTERN.finditer(template)}
        assert template_vars.issubset(set(entry.input_variables)), entry.name


def test_prompt_catalog_templates_can_render_with_sample_variables() -> None:
    """Catalog 中所有模板都应能用测试变量完成离线渲染。"""

    registry = PromptRegistry()
    renderer = PromptRenderer()
    variables = _sample_variables()

    for entry in list_prompt_catalog():
        rendered = renderer.render(registry.load(entry.name), variables)
        assert "{{" not in rendered
        assert "}}" not in rendered
