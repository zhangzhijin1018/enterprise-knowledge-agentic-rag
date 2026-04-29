"""经营分析结果脱敏模块。

为什么经营分析不能把查询结果原样返回：
1. 同一张表里可能同时包含普通字段和敏感字段；
2. 即使 SQL 本身是只读且安全的，结果返回阶段仍然可能发生敏感信息暴露；
3. 企业系统的治理边界不止是“能不能查”，还包括“查到后能看到什么粒度”。

当前阶段这里不实现复杂动态脱敏引擎，而是先做一个稳定、可讲解、可测试的最小版本：
- visible_fields：结果允许直接返回的字段；
- sensitive_fields：结果中需要额外治理的字段；
- masked_fields：缺少敏感字段查看权限时，要做脱敏而不是原样暴露的字段。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DataMaskingResult:
    """结果脱敏处理后的结构化结果。"""

    rows: list[dict]
    columns: list[str]
    visible_fields: list[str] = field(default_factory=list)
    sensitive_fields: list[str] = field(default_factory=list)
    masked_fields: list[str] = field(default_factory=list)
    hidden_fields: list[str] = field(default_factory=list)
    governance_decision: str = "no_masking_needed"


class DataMaskingService:
    """经营分析结果脱敏服务。"""

    def apply(
        self,
        *,
        rows: list[dict],
        columns: list[str],
        visible_fields: list[str],
        sensitive_fields: list[str],
        masked_fields: list[str],
        user_permissions: list[str],
    ) -> DataMaskingResult:
        """按最小治理规则对结果进行可见性处理。

        规则：
        1. 如果字段不在 visible_fields 中，则直接隐藏；
        2. 如果字段是 sensitive_fields，且同时落在 masked_fields 中，
           那么用户缺少 `analytics:field:<field>:view_sensitive` 权限时要做脱敏；
        3. 当前阶段优先做“字段级隐藏/脱敏”两种最小动作，不做更复杂的行级策略引擎。
        """

        effective_visible_fields = columns if not visible_fields else [column for column in columns if column in visible_fields]
        hidden_fields = [column for column in columns if column not in effective_visible_fields]
        selected_sensitive_fields = [field_name for field_name in effective_visible_fields if field_name in set(sensitive_fields)]

        permission_set = set(user_permissions or [])
        effective_masked_fields = [
            field_name
            for field_name in selected_sensitive_fields
            if field_name in set(masked_fields)
            and f"analytics:field:{field_name}:view_sensitive" not in permission_set
        ]

        transformed_rows: list[dict] = []
        for row in rows:
            transformed_row: dict = {}
            for field_name in effective_visible_fields:
                if field_name not in row:
                    continue
                raw_value = row[field_name]
                if field_name in effective_masked_fields:
                    transformed_row[field_name] = self._mask_value(raw_value)
                else:
                    transformed_row[field_name] = raw_value
            transformed_rows.append(transformed_row)

        governance_decision = "no_masking_needed"
        if hidden_fields:
            governance_decision = "fields_hidden"
        if effective_masked_fields:
            governance_decision = "fields_masked"
        if hidden_fields and effective_masked_fields:
            governance_decision = "fields_hidden_and_masked"

        return DataMaskingResult(
            rows=transformed_rows,
            columns=effective_visible_fields,
            visible_fields=effective_visible_fields,
            sensitive_fields=selected_sensitive_fields,
            masked_fields=effective_masked_fields,
            hidden_fields=hidden_fields,
            governance_decision=governance_decision,
        )

    def _mask_value(self, raw_value: object) -> object:
        """对敏感值做最小脱敏。

        当前阶段策略尽量简单可维护：
        - 字符串保留首尾少量信息，便于用户知道“有值但已脱敏”；
        - 非字符串统一返回固定占位；
        - 这样既能体现治理效果，也不会把复杂脱敏规则过早做重。
        """

        if raw_value is None:
            return None
        if isinstance(raw_value, str):
            if len(raw_value) <= 2:
                return "*" * len(raw_value)
            return f"{raw_value[0]}***{raw_value[-1]}"
        return "***"
