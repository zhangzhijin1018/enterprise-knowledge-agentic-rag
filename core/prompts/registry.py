"""Prompt Registry。

Prompt 不应该散落在 service / node 代码里，原因是：
1. Prompt 是可迭代资产，需要能被版本化、替换和审查；
2. 业务代码里混大段 prompt 会让节点职责变得不清晰；
3. 后续做 A/B 测试、私有化模型适配或安全审查时，需要按 prompt_name 定位模板。
"""

from __future__ import annotations

from pathlib import Path

from core.common import error_codes
from core.common.exceptions import AppException


class PromptRegistry:
    """按名称加载 prompt 模板。"""

    def __init__(self, templates_root: Path | None = None) -> None:
        self.templates_root = templates_root or Path(__file__).resolve().parent / "templates"
        self._cache: dict[str, str] = {}

    def load(self, prompt_name: str) -> str:
        """加载模板内容。

        `prompt_name` 使用类似 `analytics/react_planner_system` 的逻辑名称，
        Registry 会映射到 `templates/analytics/react_planner_system.j2`。
        """

        if prompt_name in self._cache:
            return self._cache[prompt_name]
        template_path = self.templates_root / f"{prompt_name}.j2"
        if not template_path.exists():
            raise AppException(
                error_code=error_codes.ANALYTICS_QUERY_FAILED,
                message="Prompt 模板不存在",
                status_code=500,
                detail={"prompt_name": prompt_name, "template_path": str(template_path)},
            )
        content = template_path.read_text(encoding="utf-8")
        self._cache[prompt_name] = content
        return content
