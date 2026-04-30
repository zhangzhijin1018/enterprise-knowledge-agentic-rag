"""Prompt 模板渲染器。"""

from __future__ import annotations

import json
import re
from typing import Any


class PromptRenderer:
    """轻量模板渲染器。

    本轮先不引入 Jinja2 依赖，而是支持最小 `{{ variable }}` 渲染。
    这已经足够覆盖当前 ReAct planner prompt 的变量注入，
    后续如果需要循环、条件或 PromptOps 平台，可以在这里替换实现，
    不需要改业务节点。
    """

    _VAR_PATTERN = re.compile(r"{{\s*([\w.]+)\s*}}")

    def render(self, template: str, variables: dict[str, Any]) -> str:
        """渲染模板。"""

        def _replace(match: re.Match[str]) -> str:
            value = self._resolve_value(variables, match.group(1))
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False, indent=2)
            if value is None:
                return ""
            return str(value)

        return self._VAR_PATTERN.sub(_replace, template)

    def _resolve_value(self, variables: dict[str, Any], path: str) -> Any:
        """解析 `a.b.c` 形式变量。"""

        current: Any = variables
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                current = getattr(current, part, None)
            if current is None:
                return None
        return current
