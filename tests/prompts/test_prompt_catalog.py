"""Prompt Catalog 治理测试。"""

from __future__ import annotations

from core.prompts import PromptRegistry, list_prompt_catalog


def test_prompt_catalog_templates_exist() -> None:
    """Catalog 中登记的 Prompt 必须都能被 Registry 加载。

    这个测试用于防止后续只改 catalog 不补模板，或移动模板后忘记更新登记项。
    """

    registry = PromptRegistry()

    for entry in list_prompt_catalog():
        assert registry.load(entry.name)
        assert entry.domain
        assert entry.output_schema
