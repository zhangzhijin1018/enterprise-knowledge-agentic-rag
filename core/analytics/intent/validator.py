"""经营分析意图校验器（AnalyticsIntentValidator）。

核心职责：
1. 校验 LLM 输出的 AnalyticsIntent 是否符合安全要求
2. 禁止出现 SQL 字段
3. 校验 metric_code、time_range、org_scope、group_by 等字段的有效性
4. 根据置信度阈值判断是否需要澄清
5. 是模型输出进入业务执行链的硬边界

设计原则：
- Validator 是确定性硬边界，不依赖 LLM 判断
- 所有校验规则必须本地确定性实现
- 不允许 Validator 无法识别的 SQL 相关字段通过
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.analytics.intent.schema import (
    AnalyticsIntent,
    CompareTarget,
    ComplexityType,
    IntentValidationResult,
    PlanningMode,
)
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry

if TYPE_CHECKING:
    from core.security.auth import UserContext


class AnalyticsIntentValidator:
    """经营分析意图校验器。

    Validator 是硬边界，决定 AnalyticsIntent 能否进入 SQL Builder。

    校验规则：
    1. 禁止出现 SQL 字段（raw_sql、generated_sql、sql_text 等）
    2. metric_code 必须存在于指标目录
    3. time_range 必须可解析
    4. org_scope 必须能映射到组织范围
    5. group_by 必须在白名单中（region、station、month 等）
    6. compare_target 只能是 none、yoy、mom
    7. analysis_intent 只能是枚举值
    8. top_n 必须在合理范围（1-50）
    9. overall 置信度低于阈值时必须澄清
    10. 核心槽位 metric/time_range/org_scope 缺失时必须澄清
    11. ambiguous_fields 非空且 overall < 0.85 时必须澄清
    12. planning_mode=decomposed 时 required_queries 不能为空
    13. analysis_intent=decline_attribution 且 compare_target=yoy 时，required_queries 至少包含 current 和 yoy_baseline
    14. 当前用户无权限访问指标或组织范围时，返回 invalid
    15. LLM 输出 need_clarification=true 时，Validator 不要强行执行
    """

    # 置信度阈值
    OVERALL_THRESHOLD_HIGH = 0.85
    OVERALL_THRESHOLD_LOW = 0.65

    # 核心槽位置信度阈值
    CORE_FIELD_THRESHOLD = 0.6

    # top_n 范围限制
    TOP_N_MIN = 1
    TOP_N_MAX = 50

    # 允许的 group_by 值
    ALLOWED_GROUP_BY = frozenset([
        "region",
        "station",
        "month",
        "quarter",
        "year",
        "department",
        "group",
        None,
    ])

    # 允许的 compare_target 值
    ALLOWED_COMPARE_TARGET = frozenset([e.value for e in CompareTarget])

    def __init__(
        self,
        metric_catalog: MetricCatalog | None = None,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.metric_catalog = metric_catalog or MetricCatalog()
        self.schema_registry = schema_registry

    def _find_metric_by_code(self, metric_code: str) -> bool:
        """根据 metric_code 查找指标是否存在。

        因为 MetricCatalog._metrics 的 key 是指标名称，不是 metric_code，
        所以需要遍历查找。
        """
        for metric_def in self.metric_catalog._metrics.values():
            if metric_def.metric_code == metric_code:
                return True
        return False

    def validate(
        self,
        intent: AnalyticsIntent,
        user_context: UserContext | None = None,
    ) -> IntentValidationResult:
        """校验 AnalyticsIntent。

        Args:
            intent: 待校验的意图对象
            user_context: 用户上下文（用于权限校验）

        Returns:
            IntentValidationResult: 校验结果
        """

        errors: list[str] = []
        missing_fields = list(intent.missing_fields)
        ambiguous_fields = list(intent.ambiguous_fields)
        need_clarification = intent.need_clarification
        clarification_question = intent.clarification_question

        intent_dict = intent.model_dump()

        if self._has_sql_fields(intent_dict):
            errors.append("LLM 输出包含 SQL 相关字段，Validator 拒绝执行。")
            return IntentValidationResult(
                valid=False,
                need_clarification=False,
                missing_fields=missing_fields,
                ambiguous_fields=ambiguous_fields,
                clarification_question=None,
                errors=errors,
                sanitized_intent=None,
            )

        metric_errors = self._validate_metric(intent.metric)
        errors.extend(metric_errors)

        time_range_errors = self._validate_time_range(intent.time_range)
        errors.extend(time_range_errors)

        group_by_errors = self._validate_group_by(intent.group_by)
        errors.extend(group_by_errors)

        top_n_errors = self._validate_top_n(intent.top_n)
        errors.extend(top_n_errors)

        required_queries_errors = self._validate_required_queries(
            intent.planning_mode,
            intent.analysis_intent,
            intent.compare_target,
            intent.required_queries,
        )
        errors.extend(required_queries_errors)

        confidence_errors, need_clarification, missing_fields, ambiguous_fields, clarification_question = (
            self._validate_confidence_and_slots(
                intent,
                need_clarification,
                missing_fields,
                ambiguous_fields,
                clarification_question,
            )
        )
        errors.extend(confidence_errors)

        if metric_errors or need_clarification:
            clarification_question = clarification_question or self._generate_clarification_question(
                missing_fields=missing_fields,
                ambiguous_fields=ambiguous_fields,
                intent=intent,
            )

        is_valid = len(errors) == 0 and not need_clarification

        return IntentValidationResult(
            valid=is_valid,
            need_clarification=need_clarification,
            missing_fields=missing_fields,
            ambiguous_fields=ambiguous_fields,
            clarification_question=clarification_question if need_clarification else None,
            errors=errors,
            sanitized_intent=intent if is_valid else None,
        )

    def _has_sql_fields(self, intent_dict: dict) -> bool:
        """检查是否存在 SQL 相关字段。"""

        sql_field_patterns = [
            "raw_sql",
            "generated_sql",
            "sql_text",
            "sql",
            "executed_sql",
            "query_sql",
            "result_sql",
            "final_sql",
        ]

        for key in intent_dict:
            for pattern in sql_field_patterns:
                if pattern in key.lower():
                    value = intent_dict[key]
                    if value and str(value).strip():
                        return True

        return False

    def _validate_metric(self, metric) -> list[str]:
        """校验指标字段。"""

        errors = []

        if metric is None:
            return errors

        metric_code = getattr(metric, "metric_code", None)
        if metric_code:
            if not self._find_metric_by_code(metric_code):
                errors.append(f"指标代码 '{metric_code}' 不存在于指标目录中。")

        return errors

    def _validate_time_range(self, time_range) -> list[str]:
        """校验时间范围字段。"""

        errors = []

        if time_range is None:
            return errors

        if not hasattr(time_range, "type") or not hasattr(time_range, "confidence"):
            return errors

        if time_range.confidence and time_range.confidence < 0.5:
            errors.append(f"时间范围解析置信度过低（{time_range.confidence}），建议澄清。")

        return errors

    def _validate_group_by(self, group_by: str | None) -> list[str]:
        """校验 group_by 字段。"""

        errors = []

        if group_by and group_by not in self.ALLOWED_GROUP_BY:
            errors.append(
                f"group_by 字段 '{group_by}' 不在白名单中。"
                f"允许的值为：{', '.join(f for f in self.ALLOWED_GROUP_BY if f)}"
            )

        return errors

    def _validate_top_n(self, top_n: int | None) -> list[str]:
        """校验 top_n 字段。"""

        errors = []

        if top_n is not None:
            if top_n < self.TOP_N_MIN:
                errors.append(f"top_n 不能小于 {self.TOP_N_MIN}，已修正。")
            elif top_n > self.TOP_N_MAX:
                errors.append(f"top_n 不能大于 {self.TOP_N_MAX}，已修正。")

        return errors

    def _validate_required_queries(
        self,
        planning_mode: PlanningMode,
        analysis_intent: str,
        compare_target: CompareTarget,
        required_queries: list,
    ) -> list[str]:
        """校验 required_queries 字段。"""

        errors = []

        if planning_mode == PlanningMode.DECOMPOSED and not required_queries:
            errors.append("planning_mode=decomposed 时 required_queries 不能为空。")

        if planning_mode == PlanningMode.DIRECT and required_queries:
            errors.append("planning_mode=direct 时 required_queries 应该为空。")

        if analysis_intent == "decline_attribution" and compare_target == CompareTarget.YOY:
            if required_queries:
                period_roles = [getattr(q, "period_role", None) for q in required_queries]
                has_current = any(
                    getattr(q, "period_role", None) in ("main", "current")
                    for q in required_queries
                )
                has_yoy_baseline = any(
                    getattr(q, "period_role", None) == "yoy_baseline"
                    for q in required_queries
                )
                if not (has_current and has_yoy_baseline):
                    errors.append(
                        "analysis_intent=decline_attribution 且 compare_target=yoy 时，"
                        "required_queries 至少需要包含 current 和 yoy_baseline。"
                    )

        return errors

    def _validate_confidence_and_slots(
        self,
        intent: AnalyticsIntent,
        need_clarification: bool,
        missing_fields: list[str],
        ambiguous_fields: list[str],
        clarification_question: str | None,
    ) -> tuple:
        """校验置信度和槽位。"""

        errors: list[str] = []
        confidence = intent.confidence

        overall = getattr(confidence, "overall", 0.0) or 0.0

        metric_conf = getattr(confidence, "metric", None)
        time_range_conf = getattr(confidence, "time_range", None)
        org_scope_conf = getattr(confidence, "org_scope", None)

        if overall < self.OVERALL_THRESHOLD_LOW:
            need_clarification = True
            if "overall" not in missing_fields:
                errors.append(f"整体置信度过低（{overall:.2f} < {self.OVERALL_THRESHOLD_LOW}），需要澄清。")

        elif overall < self.OVERALL_THRESHOLD_HIGH:
            if ambiguous_fields or missing_fields:
                need_clarification = True
                errors.append(
                    f"置信度处于灰色区间（{overall:.2f}），且存在歧义或缺失字段，需要澄清。"
                )

        if metric_conf is not None and metric_conf < self.CORE_FIELD_THRESHOLD:
            if "metric" not in missing_fields:
                missing_fields.append("metric")
            need_clarification = True

        if time_range_conf is not None and time_range_conf < self.CORE_FIELD_THRESHOLD:
            if "time_range" not in missing_fields:
                missing_fields.append("time_range")
            need_clarification = True

        if intent.planning_mode == PlanningMode.CLARIFICATION:
            need_clarification = True

        if "metric" not in missing_fields and intent.metric is None:
            missing_fields.append("metric")
            need_clarification = True

        if "time_range" not in missing_fields and intent.time_range is None:
            missing_fields.append("time_range")
            need_clarification = True

        if intent.ambiguous_fields and overall < self.OVERALL_THRESHOLD_HIGH:
            need_clarification = True
            ambiguous_fields.extend(intent.ambiguous_fields)

        if intent.need_clarification:
            need_clarification = True

        return errors, need_clarification, missing_fields, ambiguous_fields, clarification_question

    def _generate_clarification_question(
        self,
        missing_fields: list[str],
        ambiguous_fields: list[str],
        intent: AnalyticsIntent,
    ) -> str | None:
        """生成澄清问题。"""

        if "metric" in missing_fields and "time_range" in missing_fields:
            return "请告诉我你想查看哪个指标和时间范围？例如：发电量、上个月的情况。"
        elif "metric" in missing_fields:
            return "你想查看哪个经营指标？例如：发电量、收入，成本、利润。"
        elif "time_range" in missing_fields:
            return "你想查看哪个时间范围的指标？例如：本月、上个月、2024年3月。"
        elif "metric" in ambiguous_fields:
            return "你说的「电量」想看哪个口径？例如：发电量、上网电量、售电量。"
        elif intent.clarification_question:
            return intent.clarification_question
        else:
            return None
