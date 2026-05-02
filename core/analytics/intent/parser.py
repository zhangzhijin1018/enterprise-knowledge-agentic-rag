"""经营分析统一意图解析器（LLMAnalyticsIntentParser）。

核心职责：
1. 接收用户 query、conversation context、metric catalog 摘要
2. 通过 PromptRegistry / PromptRenderer / LLMGateway 调用模型
3. 要求模型输出 AnalyticsIntent 结构化 JSON
4. 不生成 SQL，不更新 task_run，不调用 SQL Gateway
5. 不触发 export/review，不绕过 Validator

设计原则：
- 不直接耦合具体 LLM SDK，通过 LLMGateway 统一访问
- Prompt 通过 PromptRegistry 文件化管理
- 输出通过 Pydantic Schema 和 Validator 双重校验
- LLM 只负责识别用户想要的指标（metric_code），不涉及数据源/表等内部信息
- 指标到数据源的映射由 MetricResolver 在本地完成
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.analytics.intent.schema import (
    AnalyticsIntent,
    ComplexityType,
    PlanningMode,
)
from core.analytics.metric_resolver import MetricResolver, get_global_metric_resolver
from core.common.exceptions import AppException
from core.config.settings import Settings
from core.llm import LLMGateway, LLMMessage, OpenAICompatibleLLMGateway
from core.prompts import PromptRegistry, PromptRenderer

if TYPE_CHECKING:
    from core.agent.control_plane.analytics_llm_schemas import AnalyticsIntentOutput


@dataclass(slots=True)
class IntentParserResult:
    """意图解析结果。

    包含解析后的 AnalyticsIntent 和元信息。
    """

    intent: AnalyticsIntent
    planning_source: str = "llm_parser"
    model: str | None = None
    latency_ms: float | None = None
    success: bool = True
    error_message: str | None = None


class LLMAnalyticsIntentParser:
    """经营分析统一意图解析器。

    通过 LLM 将用户问句解析为结构化 AnalyticsIntent。

    关键约束：
    - 不生成 SQL
    - 不执行 SQL
    - 不调用 SQL Gateway
    - 不更新 task_run
    - 不触发 export/review
    - 不绕过 Validator

    架构说明：
    - LLM 只负责语义理解：用户想要什么指标
    - MetricResolver 负责业务映射：指标代码 → 数据源/表/字段
    - 这种分离让 LLM prompt 保持简洁
    """

    def __init__(
        self,
        settings: Settings,
        *,
        llm_gateway: LLMGateway | None = None,
        prompt_registry: PromptRegistry | None = None,
        prompt_renderer: PromptRenderer | None = None,
        metric_resolver: MetricResolver | None = None,
    ) -> None:
        self.settings = settings
        self.llm_gateway = llm_gateway
        self.prompt_registry = prompt_registry or PromptRegistry()
        self.prompt_renderer = prompt_renderer or PromptRenderer()
        # 使用 MetricResolver 替代原来的 MetricCatalog + SchemaRegistry
        self.metric_resolver = metric_resolver or get_global_metric_resolver()

    def parse(
        self,
        query: str,
        conversation_memory: dict | None = None,
        *,
        trace_id: str | None = None,
        run_id: str | None = None,
    ) -> IntentParserResult:
        """解析用户问句为结构化意图。

        Args:
            query: 用户原始问句
            conversation_memory: 会话上下文
            trace_id: Trace ID（用于日志关联）
            run_id: Run ID（用于日志关联）

        Returns:
            IntentParserResult: 包含解析结果的 Result 对象
        """

        import time

        t0 = time.monotonic()

        try:
            intent = self._call_llm(
                query=query,
                conversation_memory=conversation_memory,
            )
            latency_ms = round((time.monotonic() - t0) * 1000, 1)

            return IntentParserResult(
                intent=intent,
                planning_source="llm_parser",
                latency_ms=latency_ms,
                success=True,
            )
        except Exception as exc:
            latency_ms = round((time.monotonic() - t0) * 1000, 1)
            return IntentParserResult(
                intent=self._create_fallback_intent(query, conversation_memory),
                planning_source="rule_fallback",
                latency_ms=latency_ms,
                success=False,
                error_message=str(exc),
            )

    def _call_llm(self, query: str, conversation_memory: dict | None) -> AnalyticsIntent:
        """调用 LLM 进行意图解析。"""

        gateway = self._resolve_llm_gateway()
        if gateway is None:
            return self._create_fallback_intent(query, conversation_memory)

        try:
            system_template = self.prompt_registry.load("analytics/intent_parser_system")
            user_template = self.prompt_registry.load("analytics/intent_parser_user")

            # 构建指标目录（只包含指标名称和代码，不包含数据源信息）
            metric_catalog_summary = self.metric_resolver.build_metric_catalog_for_llm()

            user_content = self.prompt_renderer.render(
                user_template,
                {
                    "query": query,
                    "conversation_memory": conversation_memory or {},
                    "metric_catalog_summary": metric_catalog_summary,
                },
            )

            output = gateway.structured_output(
                messages=[
                    LLMMessage(role="system", content=system_template),
                    LLMMessage(role="user", content=user_content),
                ],
                output_schema=AnalyticsIntent,
                model=self.settings.llm_model_name,
                timeout_seconds=self.settings.llm_timeout_seconds,
                metadata={
                    "component": "analytics_intent_parser",
                    "prompt_name": "analytics/intent_parser_user",
                    "prompt_version": "v1",
                    "trace_id": None,
                    "run_id": None,
                },
            )

            # 简化校验：只检查禁止字段和 group_by 白名单
            validated_intent = self._validate_output(output)
            return validated_intent

        except (AppException, ValueError) as exc:
            return self._create_fallback_intent(query, conversation_memory)

    def _resolve_llm_gateway(self) -> LLMGateway | None:
        """解析可用的 LLMGateway。"""

        if self.llm_gateway is not None:
            return self.llm_gateway

        if not self.settings.llm_api_key or self.settings.llm_api_key == "your-api-key":
            return None

        return OpenAICompatibleLLMGateway(settings=self.settings)

    def _validate_output(self, intent: AnalyticsIntent) -> AnalyticsIntent:
        """简化校验：只检查禁止字段和 group_by 白名单。"""

        # 检查禁止字段
        FORBIDDEN_FIELDS = frozenset([
            "raw_sql", "generated_sql", "sql_text", "sql",
            "executed_sql", "query_sql", "result_sql", "final_sql",
        ])

        intent_dict = intent.model_dump()
        for field_name in FORBIDDEN_FIELDS:
            if field_name in intent_dict and intent_dict[field_name]:
                raise ValueError(
                    f"LLM 输出包含禁止字段 '{field_name}'。"
                    f"意图解析器不能生成 SQL 相关字段。"
                )

        # 检查 group_by 白名单
        ALLOWED_GROUP_BY = frozenset([
            "region", "station", "month", "quarter", "year", "department", "group", None,
        ])
        if intent.group_by and intent.group_by not in ALLOWED_GROUP_BY:
            raise ValueError(
                f"group_by 字段 '{intent.group_by}' 不在白名单中。"
            )

        return intent

    def _create_fallback_intent(
        self,
        query: str,
        conversation_memory: dict | None,
    ) -> AnalyticsIntent:
        """创建回退意图（当 LLM 不可用时）。

        基于规则做最小化意图解析，作为 fallback 方案。
        """

        from core.analytics.intent.schema import (
            IntentConfidence,
            MetricIntent,
            OrgScopeIntent,
            TimeRangeIntent,
            TimeRangeType,
            OrgScopeType,
        )

        # 1. 指标提取（使用 MetricResolver 的关键词匹配）
        fallback_metric = self._find_metric_in_query(query)

        # 2. 时间范围提取
        fallback_time_range = self._extract_time_range(query)

        # 3. 组织范围提取
        fallback_org_scope = self._extract_org_scope(query)

        # 计算置信度
        has_metric = fallback_metric is not None
        has_time_range = fallback_time_range is not None

        if has_metric and has_time_range:
            confidence = 0.75
        elif has_metric or has_time_range:
            confidence = 0.65
        else:
            confidence = 0.4

        # 判断是否需要澄清
        need_clarification = not (has_metric and has_time_range)
        missing_fields = []
        ambiguous_fields = []
        clarification_question = None

        if not has_metric:
            missing_fields.append("metric")
        if not has_time_range:
            missing_fields.append("time_range")

        if need_clarification:
            clarification_question = self._generate_clarification_question(
                query=query,
                has_metric=has_metric,
                has_time_range=has_time_range,
            )

        # 构建 MetricIntent
        metric_intent = None
        if fallback_metric:
            metric_intent = MetricIntent(
                raw_text=fallback_metric.metric_name,
                metric_code=fallback_metric.metric_code,
                metric_name=fallback_metric.metric_name,
                confidence=0.7,
            )

        return AnalyticsIntent(
            original_query=query,
            task_type="analytics_query",
            complexity=ComplexityType.SIMPLE,
            planning_mode=PlanningMode.CLARIFICATION if need_clarification else PlanningMode.DIRECT,
            analysis_intent="simple_query",
            semantic_confidence=confidence,
            metric=metric_intent,
            time_range=fallback_time_range,
            org_scope=fallback_org_scope,
            compare_target="none",
            confidence=IntentConfidence(
                overall=confidence,
                semantic=confidence,
                metric=0.7 if has_metric else None,
                time_range=0.7 if has_time_range else None,
            ),
            need_clarification=need_clarification,
            clarification_question=clarification_question,
            missing_fields=missing_fields,
            ambiguous_fields=ambiguous_fields,
        )

    def _find_metric_in_query(self, query: str):
        """在用户 query 中查找匹配的指标。

        基于关键词匹配的简单规则，用于 LLM 不可用时的 fallback。
        """

        from core.analytics.metric_resolver import MetricMetadata

        query_lower = query.lower()

        # 按关键词匹配（按长度降序排列，避免短词匹配干扰）
        keyword_to_code = {
            "上网电量": "online",
            "售电量": "sales",
            "发电量": "generation",
            "化工销售收入": "chemical_sales_revenue",
            "化工销售": "chemical_sales_volume",
            "化工收入": "chemical_sales_revenue",
            "聚乙烯": "chemical_sales_volume",
            "上网": "online",
            "售电": "sales",
            "发电": "generation",
            "电量": "generation",
            "收入": "revenue",
            "成本": "cost",
            "利润": "profit",
        }

        # 按关键词长度降序排列
        sorted_keywords = sorted(keyword_to_code.keys(), key=len, reverse=True)

        for keyword in sorted_keywords:
            if keyword in query_lower:
                metric_code = keyword_to_code[keyword]
                return self.metric_resolver.resolve_or_none(metric_code)

        return None

    def _extract_time_range(self, query: str) -> TimeRangeIntent | None:
        """从问句中提取时间范围（规则方式）。"""

        import re

        from core.analytics.intent.schema import TimeRangeIntent, TimeRangeType

        patterns = [
            (r"(\d{4})年(\d{1,2})月", TimeRangeType.ABSOLUTE),
            (r"(\d{4})-(\d{2})", TimeRangeType.ABSOLUTE),
            (r"最近(\d+)个?月", TimeRangeType.RELATIVE),
            (r"上个月", TimeRangeType.RELATIVE),
            (r"本月", TimeRangeType.RELATIVE),
            (r"今年", TimeRangeType.RELATIVE),
            (r"去年", TimeRangeType.RELATIVE),
        ]

        for pattern, time_type in patterns:
            match = re.search(pattern, query)
            if match:
                if time_type == TimeRangeType.ABSOLUTE:
                    return TimeRangeIntent(
                        raw_text=match.group(0),
                        type=TimeRangeType.ABSOLUTE,
                        value=f"{match.group(1)}-{match.group(2).zfill(2)}",
                        start=f"{match.group(1)}-{match.group(2).zfill(2)}-01",
                        end=f"{match.group(1)}-{match.group(2).zfill(2)}-31",
                        confidence=0.8,
                    )
                else:
                    return TimeRangeIntent(
                        raw_text=match.group(0),
                        type=TimeRangeType.RELATIVE,
                        value=match.group(0),
                        confidence=0.7,
                    )

        return None

    def _extract_org_scope(self, query: str) -> OrgScopeIntent | None:
        """从问句中提取组织范围（规则方式）。"""

        from core.analytics.intent.schema import OrgScopeIntent, OrgScopeType

        org_keywords = {
            OrgScopeType.REGION: ["新疆", "新疆区域", "新疆维吾尔自治区"],
            OrgScopeType.STATION: ["光伏", "风电", "电站"],
        }

        for org_type, keywords in org_keywords.items():
            for keyword in keywords:
                if keyword in query:
                    return OrgScopeIntent(
                        raw_text=keyword,
                        type=org_type,
                        name=keyword,
                        confidence=0.8,
                    )

        return None

    def _generate_clarification_question(
        self,
        query: str,
        has_metric: bool,
        has_time_range: bool,
    ) -> str:
        """生成澄清问题。"""

        if not has_metric and not has_time_range:
            return "请告诉我你想查看哪个指标和时间范围？例如：发电量、上个月的情况。"
        elif not has_metric:
            return "你想查看哪个经营指标？例如：发电量、收入、成本、利润。"
        elif not has_time_range:
            return "你想查看哪个时间范围的指标？例如：本月、上个月、2024年3月。"
        else:
            return "请提供更完整的问题描述。"
