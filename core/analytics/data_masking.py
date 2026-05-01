"""
经营分析结果脱敏模块（字段级最小治理）。

=================================================================
为什么需要脱敏
=================================================================
1. 同一张表里可能同时包含普通字段和敏感字段（如 station 和 power_generation）；
2. 即使 SQL 本身是只读且安全的，结果返回阶段仍然可能发生敏感信息暴露；
3. 企业系统的治理边界不止是"能不能查"，还包括"查到后能看到什么粒度"：
   - 普通员工可以看发电量数字，但不能看具体电站名称；
   - 分析师可以看脱敏后的电站名称（哈***站），但不能看原名。

=================================================================
当前阶段策略
=================================================================
不实现复杂的动态脱敏引擎，而是先做一个稳定、可讲解、可测试的最小版本：

－ visible_fields：结果允许直接返回的字段，不在列表中的字段直接隐藏
－ sensitive_fields：结果中需要额外治理的字段集合
－ masked_fields：缺少 view_sensitive 权限时要做脱敏的字段
－ hidden_fields：不在 visible_fields 中的字段，直接隐藏（不返回）

脱敏算法（_mask_value）：
- 字符串：保留首尾信息（"哈密电站" → "哈***站"），便于用户知道"有值但已脱敏"
- 数字/其他：统一返回 "***"
- None：直接返回 None

=================================================================
治理决策（governance_decision）分类
=================================================================
- "no_masking_needed"          → 无隐藏字段，无脱敏字段（全可见）
- "fields_hidden"              → 有隐藏字段（但无脱敏）
- "fields_masked"              → 有脱敏字段（但无隐藏）
- "fields_hidden_and_masked"   → 同时存在隐藏和脱敏
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DataMaskingResult:
    """
    结果脱敏处理后的结构化结果（不可变数据类）。

    字段说明：
    - rows：脱敏后的行数据（dict 列表），每个 dict 的 key 是列名，value 是脱敏后的值
    - columns：脱敏后的列名列表（已排除 hidden_fields）
    - visible_fields：允许直接返回的字段（effective 集合）
    - sensitive_fields：此次结果中实际存在的敏感字段
    - masked_fields：此次执行了脱敏的字段列表，前端可用于标注"已脱敏"提示
    - hidden_fields：此次被隐藏的字段列表，用于审计记录
    - governance_decision：治理决策摘要字符串
    """

    rows: list[dict]
    columns: list[str]
    visible_fields: list[str] = field(default_factory=list)
    sensitive_fields: list[str] = field(default_factory=list)
    masked_fields: list[str] = field(default_factory=list)
    hidden_fields: list[str] = field(default_factory=list)
    governance_decision: str = "no_masking_needed"


class DataMaskingService:
    """
    经营分析结果脱敏服务（字段级、规则驱动）。

    设计决策：
    - 当前只做"字段级隐藏/脱敏"两种最小动作，不做行级策略引擎
    - 权限模型：analytics:field:{field_name}:view_sensitive
    - 脱敏策略：字符串保留首尾，非字符串显示占位符
    """

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
        """
        按治理规则对结果进行可见性处理。

        三步决策流程：
        步骤 1：可见性过滤
          - 如果 visible_fields 为空 → 所有列可见
          - 如果 visible_fields 非空 → 只保留在列表中的列
          - 不在 visible_fields 中的列 → 加入 hidden_fields

        步骤 2：敏感字段识别
          - 在 visible_fields 范围内，找出同时出现在 sensitive_fields 中的字段

        步骤 3：脱敏决策
          - 在敏感字段中，找出同时出现在 masked_fields 中的字段
          - 如果用户缺少 analytics:field:{field}:view_sensitive 权限 → 执行脱敏
          - 如果用户有该权限 → 不脱敏（保留原值）

        性能考量：
        - 使用 set 进行权限检查（O(1) 查找），避免每次循环全量遍历
        - 每行每列遍历一次，时间复杂度 O(rows × columns)

        参数说明：
        - rows：原始查询结果行数据，每行是一个 dict
        - columns：原始列名列表
        - visible_fields：允许可见的字段列表（来自 schema_registry）
        - sensitive_fields：敏感字段列表（来自 schema_registry）
        - masked_fields：需要脱敏的字段列表（来自 schema_registry）
        - user_permissions：用户权限列表，用于判断 view_sensitive 权限
        """

        # 步骤 1：可见性过滤
        # visible_fields 为空 → 所有列均可见（宽松模式）
        # visible_fields 非空 → 只保留交集
        effective_visible_fields = columns if not visible_fields else [column for column in columns if column in visible_fields]
        # 被隐藏的字段 = 原始列 - effective 可见列
        hidden_fields = [column for column in columns if column not in effective_visible_fields]

        # 步骤 2：在可见列中找出敏感字段
        selected_sensitive_fields = [field_name for field_name in effective_visible_fields if field_name in set(sensitive_fields)]

        # 步骤 3：脱敏决策
        # 用户权限转为 set 用于 O(1) 查找
        permission_set = set(user_permissions or [])
        # 只有同时满足以下条件才脱敏：
        # 1. 是敏感字段
        # 2. 在 masked_fields 中
        # 3. 用户缺少 analytics:field:{field}:view_sensitive 权限
        effective_masked_fields = [
            field_name
            for field_name in selected_sensitive_fields
            if field_name in set(masked_fields)
            and f"analytics:field:{field_name}:view_sensitive" not in permission_set
        ]

        # 步骤 4：逐行逐列应用脱敏规则
        transformed_rows: list[dict] = []
        for row in rows:
            transformed_row: dict = {}
            for field_name in effective_visible_fields:
                # 防御性检查：如果行数据中不存在该字段，跳过（不抛异常）
                if field_name not in row:
                    continue
                raw_value = row[field_name]
                # 脱敏字段 → 调用 _mask_value；普通字段 → 保留原值
                if field_name in effective_masked_fields:
                    transformed_row[field_name] = self._mask_value(raw_value)
                else:
                    transformed_row[field_name] = raw_value
            transformed_rows.append(transformed_row)

        # 步骤 5：构造治理决策摘要
        # 优先级从高到低排列，方便前端和审计快速判断治理程度
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
        """
        对单个敏感值做最小脱敏。

        脱敏策略（按优先级）：
        1. None → None（空值不过度处理）
        2. 字符串长度 <= 2 → 全星号（太短，无法保留首尾）
        3. 字符串长度 > 2 → 保留首字+***+尾字（如 "哈密电站" → "哈***站"）
           - 优点：用户能感知"有值但已脱敏"，必要时可申请查看完整值
           - 性能：O(1)，不涉及加密或哈希
        4. 非字符串（数字等）→ "***"（统一占位符）
           - 后续可升级为数值范围脱敏（如 4200 → "4xxx"）

        为什么不使用更复杂的脱敏策略（如加密、哈希、加噪）：
        - 当前阶段优先保证可维护性和可理解性
        - 加密会增加密钥管理复杂度
        - 哈希会使结果完全不可读（用户无法区分"4200"和"3900"）
        - 后续可按字段类型升级策略（如数值型做加噪，字符串型做 AES 加密）
        """

        if raw_value is None:
            return None
        if isinstance(raw_value, str):
            if len(raw_value) <= 2:
                return "*" * len(raw_value)
            return f"{raw_value[0]}***{raw_value[-1]}"
        return "***"
