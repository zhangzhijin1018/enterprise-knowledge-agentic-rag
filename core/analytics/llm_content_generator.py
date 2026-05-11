"""
经营分析 LLM 内容生成器（v2 并行调用版本）。

=================================================================
核心设计
=================================================================
1. 并行调用：4 个 LLM 调用通过 asyncio.gather 并行执行
2. JSON Schema：使用 Pydantic 约束输出格式，确保解析稳定
3. 进度回调：每个产物完成后触发回调，支持 SSE 增量推送
4. 大小判断：结果小于 50KB 直接推送，大结果存库+推送链接

=================================================================
LLM 调用流程
=================================================================
SQL 执行结果
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  ParallelLLMGenerator.generate_all()                         │
│  并行启动 4 个协程：Summary / Insight / Chart / Report      │
└─────────────────────────────────────────────────────────────┘
    │
    ├──▶ SummaryGenerator.generate() ──▶ 触发 callback ──▶ SSE summary_done
    ├──▶ InsightGenerator.generate() ──▶ 触发 callback ──▶ SSE insight_done
    ├──▶ ChartDescGenerator.generate() ──▶ 触发 callback ──▶ SSE chart_done
    └──▶ ReportGenerator.generate() ──▶ 触发 callback ──▶ SSE report_done

=================================================================
SSE 推送策略
=================================================================
- 报告大小 < 50KB → 直接 SSE 推送 complete 事件
- 报告大小 >= 50KB → 存 Redis + 推送 download_url
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, TypedDict

from pydantic import BaseModel, Field, field_validator

from core.llm.gateway import LLMGateway
from core.llm.models import LLMMessage
from core.llm.structured import parse_structured_json

logger = logging.getLogger(__name__)


# =============================================================================
# 配置常量
# =============================================================================

# SSE 直接推送的最大结果大小（50KB）
MAX_SSE_INLINE_SIZE = 50 * 1024


# =============================================================================
# 输出 Schema 定义（带长度约束，适配 qwen-32b）
# =============================================================================


class InsightType(str):
    """洞察类型枚举"""
    TREND = "trend"           # 趋势洞察
    RANKING = "ranking"       # 排名洞察
    COMPARISON = "comparison" # 对比洞察
    ANOMALY = "anomaly"       # 异常提醒
    PATTERN = "pattern"       # 模式发现


class Importance(str):
    """重要性等级"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SummarySchema(BaseModel):
    """摘要输出 Schema - qwen-32b 优化版本"""

    main_text: str = Field(
        description="核心摘要，2-3句话，必须包含具体数值",
        max_length=500,
    )

    key_highlights: list[str] = Field(
        description="3-5个关键亮点，每个不超过20字",
        min_length=1,
        max_length=5,
    )

    confidence: float = Field(
        description="置信度 0-1",
        ge=0.0,
        le=1.0,
    )

    @field_validator("key_highlights")
    @classmethod
    def validate_highlights(cls, v: list[str]) -> list[str]:
        return [h[:20] for h in v[:5]]  # 最多5个，每个最多20字


class InsightCardSchema(BaseModel):
    """洞察卡片 Schema"""

    title: str = Field(
        description="洞察标题，不超过30字",
        max_length=30,
    )

    type: str = Field(
        description="洞察类型: trend/ranking/comparison/anomaly/pattern",
        default="trend",
    )

    summary: str = Field(
        description="洞察摘要，50-200字，包含业务意义",
        max_length=200,
    )

    importance: str = Field(
        description="重要性等级: high/medium/low",
        default="medium",
    )

    action_suggestion: str | None = Field(
        default=None,
        description="建议措施，不超过50字",
        max_length=50,
    )


class InsightsSchema(BaseModel):
    """洞察输出 Schema"""

    insights: list[InsightCardSchema] = Field(
        description="洞察卡片列表，最多5个",
        max_length=5,
    )

    overall_analysis: str = Field(
        description="整体分析结论，50-300字",
        max_length=300,
    )


class ChartSchema(BaseModel):
    """图表 Schema"""

    chart_type: str = Field(
        description="图表类型: line/bar/pie/scatter/ranking_bar/grouped_bar",
    )

    title: str = Field(
        description="图表标题",
        max_length=50,
    )

    description: str = Field(
        description="图表描述，20-100字",
        max_length=100,
    )

    x_field: str | None = Field(
        default=None,
        description="X轴字段名",
    )

    y_field: str | None = Field(
        default=None,
        description="Y轴字段名",
    )


class ReportBlockSchema(BaseModel):
    """报告块 Schema"""

    block_type: str = Field(
        description="块类型: overview/findings/trend/recommendation",
    )

    title: str = Field(
        description="块标题",
        max_length=30,
    )

    content: str = Field(
        description="块内容",
        max_length=1000,
    )


class ReportSchema(BaseModel):
    """完整报告 Schema"""

    blocks: list[ReportBlockSchema] = Field(
        description="报告块列表",
        max_length=10,
    )

    executive_summary: str = Field(
        description="执行摘要",
        max_length=300,
    )

    next_steps: list[str] = Field(
        description="后续步骤建议",
        max_length=3,
    )


# =============================================================================
# Prompt 模板（优化版，适配 qwen-32b）
# =============================================================================

SUMMARY_SYSTEM_PROMPT = """你是一个专业的数据分析助手。

输入数据：
- 指标名称: {metric}
- 时间范围: {time_range}
- 组织范围: {org_scope}
- 查询结果: {result_data}

请生成 JSON 格式的摘要，必须包含：
1. main_text: 2-3句核心结论，必须包含具体数值
2. key_highlights: 3个关键亮点，每个不超过20字
3. confidence: 0-1之间的置信度

示例输出：
{{"main_text": "当月发电量1.23亿千瓦时，同比增长12.2%，表现优异", "key_highlights": ["同比增长12.2%", "创近6月新高", "风电贡献突出"], "confidence": 0.95}}
"""

INSIGHT_SYSTEM_PROMPT = """你是一个资深数据分析师。

洞察类型说明：
- trend：趋势洞察，描述数据随时间的变化规律
- ranking：排名洞察，指出排名靠前/靠后的维度
- comparison：对比洞察，分析不同维度或时期的数据差异
- anomaly：异常提醒，发现数据中的异常值或异常模式
- pattern：模式发现，发现数据中的规律或周期性

要求：
1. 每个洞察必须有业务意义，不是简单描述数字
2. importance=high 放前面
3. 最多生成5个洞察
4. 每个洞察 summary 不超过200字
5. 输出 JSON 格式

示例：
{{"insights": [
  {{"title": "发电量同比增长显著", "type": "comparison", "summary": "3月份发电量达1.23亿千瓦时，较去年同期增长12.2%，主要受益于风电利用小时数提升", "importance": "high", "action_suggestion": "建议分析风电增长驱动因素"}}
], "overall_analysis": "整体来看，3月份经营数据表现良好，发电量同比增长超预期"}}
"""

CHART_SYSTEM_PROMPT = """根据以下数据，推荐合适的可视化方案。

数据：{data_sample}
分组维度：{group_by}

输出 JSON 格式：
{{"chart_type": "line/bar/pie/scatter/ranking_bar/grouped_bar", "title": "图表标题", "description": "图表描述20-100字", "x_field": "x轴字段", "y_field": "y轴字段"}}

图表类型选择原则：
- line：用于展示时间趋势（按月/按年变化）
- bar：用于对比不同维度的数值
- pie：用于展示占比结构
- ranking_bar：用于展示 TOP N 排名
- grouped_bar：用于同时展示同比/环比对比
"""

REPORT_SYSTEM_PROMPT = """你是一个专业的商业报告撰写专家，擅长撰写清晰、有说服力的分析报告。

报告风格：
- 专业但不晦涩，用业务语言而非技术语言
- 结论先行，重点结论放在最前面
- 数据支撑要有具体数值
- 要有行动建议，不能只描述现状

输出 JSON 格式，包含：
1. blocks: 报告块列表，每个块包含 block_type/title/content
2. executive_summary: 执行摘要
3. next_steps: 后续步骤建议（最多3条）

块类型说明：
- overview: 分析概览
- findings: 关键发现
- trend: 趋势分析
- recommendation: 建议
"""


# =============================================================================
# 生成结果类型定义
# =============================================================================


class LLMGenerationResult(TypedDict):
    """LLM 生成结果类型"""
    summary: dict | None
    insights: dict | None
    chart: dict | None
    report: dict | None


# =============================================================================
# 并行 LLM 生成器
# =============================================================================


class ParallelLLMGenerator:
    """并行 LLM 生成器（v2 版本）

    使用 asyncio.gather 实现 4 个 LLM 调用的并行执行，
    最早完成的结果可以立即推送给前端。

    使用方式：
    ```python
    generator = ParallelLLMGenerator(llm_gateway)
    result = await generator.generate_all(
        original_query="查询新疆区域2024年3月发电量",
        slots={"metric": "发电量", "time_range": {...}, ...},
        rows=[...],
        progress_callback=lambda product, progress, data: print(f"{product}: {progress}%")
    )
    ```
    """

    def __init__(
        self,
        llm_gateway: LLMGateway,
        model: str = "qwen-32b",
        temperature: float = 0.7,
        max_retries: int = 2,
    ) -> None:
        """
        初始化并行生成器。

        Args:
            llm_gateway: LLM 网关实例
            model: 模型名称，默认 qwen-32b
            temperature: 生成温度，默认 0.7
            max_retries: 最大重试次数
        """
        self.llm_gateway = llm_gateway
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries

    async def generate_all(
        self,
        *,
        original_query: str,
        slots: dict,
        rows: list[dict],
        columns: list[str],
        row_count: int,
        progress_callback: Callable[[str, int, dict], None] | None = None,
    ) -> LLMGenerationResult:
        """并行生成所有内容

        Args:
            original_query: 用户原始问题
            slots: 解析后的槽位
            rows: SQL 查询结果
            columns: 列名列表
            row_count: 总行数
            progress_callback: 进度回调，每完成一个产物调用

        Returns:
            包含所有生成结果的字典
        """

        # 准备共享上下文
        metric = slots.get("metric", "指标")
        time_range = self._format_time_range(slots.get("time_range"))
        org_scope = self._format_org_scope(slots.get("org_scope"))
        group_by = slots.get("group_by")

        # 格式化结果数据
        result_data = self._format_result_data(rows)

        # 并行启动所有任务
        tasks = [
            self._generate_summary_with_retry(
                original_query=original_query,
                metric=metric,
                time_range=time_range,
                org_scope=org_scope,
                result_data=result_data,
                progress_callback=progress_callback,
            ),
            self._generate_insights_with_retry(
                original_query=original_query,
                metric=metric,
                time_range=time_range,
                org_scope=org_scope,
                result_data=result_data,
                progress_callback=progress_callback,
            ),
            self._generate_chart_with_retry(
                metric=metric,
                group_by=group_by,
                result_data=result_data[:10] if len(result_data) > 10 else result_data,
                progress_callback=progress_callback,
            ),
            self._generate_report_with_retry(
                original_query=original_query,
                metric=metric,
                time_range=time_range,
                result_data=result_data,
                progress_callback=progress_callback,
            ),
        ]

        # 等待所有任务完成
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 整理结果
        summary_result = results[0] if not isinstance(results[0], Exception) else None
        insight_result = results[1] if not isinstance(results[1], Exception) else None
        chart_result = results[2] if not isinstance(results[2], Exception) else None
        report_result = results[3] if not isinstance(results[3], Exception) else None

        # 记录异常
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                product_names = ["summary", "insights", "chart", "report"]
                logger.error(f"LLM {product_names[i]} 生成失败: {result}")

        return LLMGenerationResult(
            summary=summary_result,
            insights=insight_result,
            chart=chart_result,
            report=report_result,
        )

    async def _generate_summary_with_retry(
        self,
        original_query: str,
        metric: str,
        time_range: str,
        org_scope: str,
        result_data: str,
        progress_callback: Callable[[str, int, dict], None] | None,
    ) -> dict | None:
        """生成摘要（带重试）"""

        for attempt in range(self.max_retries):
            try:
                result = await self._generate_summary(
                    original_query=original_query,
                    metric=metric,
                    time_range=time_range,
                    org_scope=org_scope,
                    result_data=result_data,
                )

                if progress_callback and result:
                    progress_callback("summary", 25, result)

                return result

            except Exception as e:
                logger.warning(f"Summary 生成失败 (尝试 {attempt + 1}/{self.max_retries}): {e}")
                if attempt == self.max_retries - 1:
                    return None

        return None

    async def _generate_summary(
        self,
        original_query: str,
        metric: str,
        time_range: str,
        org_scope: str,
        result_data: str,
    ) -> dict:
        """调用 LLM 生成摘要"""

        user_prompt = f"""请分析以下数据，生成 JSON 格式的摘要：

## 用户查询
{original_query}

## 查询条件
- 指标：{metric}
- 时间范围：{time_range}
- 组织范围：{org_scope}

## 查询结果
{result_data}

请直接输出 JSON，不要包含其他文字。"""

        messages = [
            LLMMessage(role="system", content=SUMMARY_SYSTEM_PROMPT.format(
                metric=metric,
                time_range=time_range,
                org_scope=org_scope,
                result_data=result_data,
            )),
            LLMMessage(role="user", content=user_prompt),
        ]

        # 同步调用 LLM（Gateway 内部是同步实现）
        response = self.llm_gateway.chat(
            messages=messages,
            model=self.model,
        )

        # 解析结构化输出
        parsed = parse_structured_json(response.content, SummarySchema)
        return parsed.model_dump()

    async def _generate_insights_with_retry(
        self,
        original_query: str,
        metric: str,
        time_range: str,
        org_scope: str,
        result_data: str,
        progress_callback: Callable[[str, int, dict], None] | None,
    ) -> dict | None:
        """生成洞察（带重试）"""

        for attempt in range(self.max_retries):
            try:
                result = await self._generate_insights(
                    original_query=original_query,
                    metric=metric,
                    time_range=time_range,
                    org_scope=org_scope,
                    result_data=result_data,
                )

                if progress_callback and result:
                    progress_callback("insight", 50, result)

                return result

            except Exception as e:
                logger.warning(f"Insights 生成失败 (尝试 {attempt + 1}/{self.max_retries}): {e}")
                if attempt == self.max_retries - 1:
                    return None

        return None

    async def _generate_insights(
        self,
        original_query: str,
        metric: str,
        time_range: str,
        org_scope: str,
        result_data: str,
    ) -> dict:
        """调用 LLM 生成洞察"""

        user_prompt = f"""请分析以下数据，发现有价值的洞察。直接输出 JSON：

## 用户查询
{original_query}

## 查询条件
- 指标：{metric}
- 时间范围：{time_range}
- 组织范围：{org_scope}

## 查询结果
{result_data}
"""

        messages = [
            LLMMessage(role="system", content=INSIGHT_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]

        response = self.llm_gateway.chat(
            messages=messages,
            model=self.model,
        )

        parsed = parse_structured_json(response.content, InsightsSchema)
        return parsed.model_dump()

    async def _generate_chart_with_retry(
        self,
        metric: str,
        group_by: str | None,
        result_data: str,
        progress_callback: Callable[[str, int, dict], None] | None,
    ) -> dict | None:
        """生成图表配置（带重试）"""

        for attempt in range(self.max_retries):
            try:
                result = await self._generate_chart(
                    metric=metric,
                    group_by=group_by,
                    result_data=result_data,
                )

                if progress_callback and result:
                    progress_callback("chart", 75, result)

                return result

            except Exception as e:
                logger.warning(f"Chart 生成失败 (尝试 {attempt + 1}/{self.max_retries}): {e}")
                if attempt == self.max_retries - 1:
                    return None

        return None

    async def _generate_chart(
        self,
        metric: str,
        group_by: str | None,
        result_data: str,
    ) -> dict:
        """调用 LLM 生成图表配置"""

        user_prompt = f"""请为以下数据推荐合适的可视化方案。直接输出 JSON：

- 指标：{metric}
- 分组维度：{group_by or '无'}

数据：
{result_data}
"""

        messages = [
            LLMMessage(role="system", content=CHART_SYSTEM_PROMPT.format(
                data_sample=result_data,
                group_by=group_by or '无',
            )),
            LLMMessage(role="user", content=user_prompt),
        ]

        response = self.llm_gateway.chat(
            messages=messages,
            model=self.model,
        )

        parsed = parse_structured_json(response.content, ChartSchema)
        return parsed.model_dump()

    async def _generate_report_with_retry(
        self,
        original_query: str,
        metric: str,
        time_range: str,
        result_data: str,
        progress_callback: Callable[[str, int, dict], None] | None,
    ) -> dict | None:
        """生成报告（带重试）"""

        for attempt in range(self.max_retries):
            try:
                result = await self._generate_report(
                    original_query=original_query,
                    metric=metric,
                    time_range=time_range,
                    result_data=result_data,
                )

                if progress_callback and result:
                    progress_callback("report", 100, result)

                return result

            except Exception as e:
                logger.warning(f"Report 生成失败 (尝试 {attempt + 1}/{self.max_retries}): {e}")
                if attempt == self.max_retries - 1:
                    return None

        return None

    async def _generate_report(
        self,
        original_query: str,
        metric: str,
        time_range: str,
        result_data: str,
    ) -> dict:
        """调用 LLM 生成报告"""

        user_prompt = f"""请撰写一份完整的分析报告。直接输出 JSON：

## 用户问题
{original_query}

## 指标
{metric}

## 时间范围
{time_range}

## 数据
{result_data}
"""

        messages = [
            LLMMessage(role="system", content=REPORT_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]

        response = self.llm_gateway.chat(
            messages=messages,
            model=self.model,
        )

        parsed = parse_structured_json(response.content, ReportSchema)
        return parsed.model_dump()

    def _format_result_data(self, rows: list[dict]) -> str:
        """格式化查询结果为易读文本"""
        if not rows:
            return "查询结果为空"

        lines = []
        for i, row in enumerate(rows[:20]):  # 最多显示20行
            row_str = "，".join([f"{k}={v}" for k, v in row.items() if v is not None])
            lines.append(f"  {i + 1}. {row_str}")

        if len(rows) > 20:
            lines.append(f"  ... (共 {len(rows)} 行)")

        return "\n".join(lines)

    def _format_time_range(self, time_range: dict | None) -> str:
        if not time_range:
            return "未指定"
        return time_range.get("label") or time_range.get("raw_text") or "未指定"

    def _format_org_scope(self, org_scope: dict | None) -> str:
        if not org_scope:
            return "全部范围"
        if isinstance(org_scope, str):
            return org_scope
        return org_scope.get("value") or org_scope.get("name") or "全部范围"


# =============================================================================
# 便捷函数
# =============================================================================


def calculate_result_size(result: dict) -> int:
    """计算结果 JSON 的大小（字节数）

    Args:
        result: 要计算的结果字典

    Returns:
        JSON 编码后的字节数
    """
    return len(json.dumps(result, ensure_ascii=False).encode("utf-8"))


def should_inline_result(result: dict) -> tuple[bool, int]:
    """判断结果是否应该直接通过 SSE 推送

    Args:
        result: 要判断的结果字典

    Returns:
        (是否内联推送, 结果大小)
    """
    result_size = calculate_result_size(result)
    return result_size < MAX_SSE_INLINE_SIZE, result_size


# =============================================================================
# 兼容层：保留原有类名
# =============================================================================


class LLMContentGenerator(ParallelLLMGenerator):
    """兼容层：保留原有类名，内部委托给 ParallelLLMGenerator"""

    def __init__(
        self,
        llm_gateway: LLMGateway | None = None,
        model: str = "qwen-32b",
        temperature: float = 0.7,
    ) -> None:
        gateway = llm_gateway or LLMGateway()
        super().__init__(
            llm_gateway=gateway,
            model=model,
            temperature=temperature,
        )


def create_llm_generator(
    llm_gateway: LLMGateway | None = None,
    model: str = "qwen-32b",
) -> ParallelLLMGenerator:
    """便捷函数：创建 LLM 内容生成器"""
    gateway = llm_gateway or LLMGateway()
    return ParallelLLMGenerator(llm_gateway=gateway, model=model)
