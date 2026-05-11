"""
Mock LLM 响应生成器 - 用于模拟大模型生成自然语言内容。

当无法访问真实 LLM API 时，此模块提供：
1. 自然语言摘要生成
2. 智能洞察发现
3. 图表描述推荐
4. 报告块生成

设计原则：
- 模拟真实 LLM 的输出格式
- 生成自然、流畅的语言
- 支持多种场景的数据
- 保持与 LLMContentGenerator 相同的输出结构
"""

from __future__ import annotations

import random
import re
from typing import Any


# =============================================================================
# 自然语言模板库
# =============================================================================

class NaturalLanguageTemplates:
    """自然语言模板库 - 用于生成自然流畅的摘要和洞察"""

    # 趋势描述模板
    TREND_TEMPLATES = [
        "呈上升趋势",
        "稳步增长",
        "持续攀升",
        "保持增长态势",
        "表现强劲",
    ]

    TREND_UP_PHRASES = [
        "表现亮眼",
        "表现优异",
        "超出预期",
        "再创新高",
        "增速明显",
    ]

    TREND_DOWN_PHRASES = [
        "略有下滑",
        "低于预期",
        "需要关注",
        "面临压力",
        "出现下降",
    ]

    # 排名描述模板
    RANKING_TEMPLATES = [
        "位列第一",
        "排名第一",
        "位居榜首",
        "稳居第一",
        "遥遥领先",
    ]

    # 对比描述模板
    COMPARISON_UP = [
        "同比增长{value}%",
        "较去年提升{value}%",
        "同比增加{value}%",
        "涨幅达{value}%",
    ]

    COMPARISON_DOWN = [
        "同比下降{value}%",
        "较去年减少{value}%",
        "同比降低{value}%",
        "降幅达{value}%",
    ]

    # 概览开头模板
    OVERVIEW_OPENINGS = [
        "根据查询结果，",
        "分析显示，",
        "数据显示，",
        "从数据来看，",
        "整体来看，",
    ]

    # 概览结尾模板
    OVERVIEW_ENDINGS = [
        "，可作为经营决策参考。",
        "，建议持续关注。",
        "，建议进一步分析原因。",
        "，整体表现良好。",
        "，需要引起重视。",
    ]

    # 洞察类型描述
    INSIGHT_TYPES = {
        "trend": "趋势洞察",
        "ranking": "排名洞察",
        "comparison": "对比洞察",
        "anomaly": "异常提醒",
        "pattern": "模式发现",
    }

    # 后续建议模板
    RECOMMENDATIONS = [
        "建议进一步下钻到区域或电站维度进行深入分析",
        "可增加同比/环比对比，观察变化趋势",
        "建议结合历史数据进行预测分析",
        "可对比不同指标间的相关性",
        "建议关注异常值背后的业务原因",
    ]


class MockLLMResponseGenerator:
    """Mock LLM 响应生成器

    核心职责：
    1. 根据 slots 和 SQL 结果生成自然语言摘要
    2. 生成智能洞察卡片
    3. 推荐图表类型
    4. 生成完整报告块

    使用方式：
    ```python
    generator = MockLLMResponseGenerator()
    result = generator.generate_all(
        original_query="查询新疆区域2024年3月发电量",
        slots={"metric": "发电量", "time_range": {...}, ...},
        rows=[...],
    )
    ```
    """

    def __init__(self, seed: int | None = None) -> None:
        """初始化生成器

        Args:
            seed: 随机种子，用于复现相同结果
        """
        self.templates = NaturalLanguageTemplates()
        if seed is not None:
            random.seed(seed)

    def generate_all(
        self,
        *,
        original_query: str,
        slots: dict,
        rows: list[dict],
        columns: list[str],
        row_count: int,
        additional_context: dict | None = None,
    ) -> dict:
        """一次性生成所有内容

        返回结构与 LLMContentGenerator.generate_all() 保持一致。
        """
        summary = self.generate_summary(
            original_query=original_query,
            slots=slots,
            rows=rows,
        )

        insights = self.generate_insights(
            original_query=original_query,
            slots=slots,
            rows=rows,
            summary=summary["main_text"],
        )

        chart_desc = self.generate_chart_desc(
            slots=slots,
            rows=rows,
        )

        report = self.generate_report(
            original_query=original_query,
            summary=summary,
            insights=insights,
            data_details={"rows": rows, "columns": columns, "row_count": row_count},
        )

        return {
            "summary": summary,
            "insights": insights,
            "chart_desc": chart_desc,
            "report": report,
        }

    def generate_summary(
        self,
        *,
        original_query: str,
        slots: dict,
        rows: list[dict],
    ) -> dict:
        """生成自然语言摘要"""

        metric = slots.get("metric", "指标")
        time_label = slots.get("time_range", {}).get("label", "当前")
        org_scope = self._format_org_scope(slots.get("org_scope"))
        compare_target = slots.get("compare_target")
        group_by = slots.get("group_by")

        # 无数据情况
        if not rows:
            return {
                "main_text": f"在{time_label}的{org_scope}范围内，未查询到与「{metric}」相关的数据。建议调整查询条件或确认数据是否存在。",
                "key_highlights": ["查询结果为空"],
                "data_summary": "无数据",
                "confidence": 0.5,
            }

        # 提取关键数值
        key_value = self._extract_key_value(rows)
        opening = random.choice(self.templates.OVERVIEW_OPENINGS)

        # 有对比的情况
        if compare_target in {"mom", "yoy"} and "current_value" in rows[0]:
            current = rows[0].get("current_value", 0) or 0
            compare = rows[0].get("compare_value", 0) or 0
            if compare != 0:
                change_pct = ((current - compare) / compare) * 100
                compare_label = "环比" if compare_target == "mom" else "同比"

                if change_pct > 0:
                    change_text = f"同比增长{abs(change_pct):.1f}%"
                    trend_phrase = random.choice(self.templates.TREND_UP_PHRASES)
                else:
                    change_text = f"同比下降{abs(change_pct):.1f}%"
                    trend_phrase = random.choice(self.templates.TREND_DOWN_PHRASES)

                main_text = (
                    f"{opening}{time_label}{org_scope}的{metric}达到 {current:,.2f}，"
                    f"{change_text}，{trend_phrase}。"
                )
            else:
                main_text = (
                    f"{opening}{time_label}{org_scope}的{metric}达到 {current:,.2f}。"
                )

        # 分组查询
        elif group_by in {"month", "region", "station"}:
            dimension_map = {"month": "月份", "region": "区域", "station": "电站"}
            dimension = dimension_map.get(group_by, "维度")
            analysis_type = "趋势" if group_by == "month" else "排名"

            if group_by == "month":
                trend_desc = self._analyze_trend(rows)
                main_text = (
                    f"{opening}{time_label}的{metric}{trend_desc}，"
                    f"共涉及 {len(rows)} 个{analysis_type}，可继续做对比或下钻分析。"
                )
            else:
                top_name = rows[0].get(group_by, "未知")
                top_value = self._extract_key_value([rows[0]])
                main_text = (
                    f"{opening}{time_label}{org_scope}的{metric}已完成{analysis_type}分析。"
                    f"其中 {top_name} 表现最佳，达到 {top_value:,.2f}。"
                )

        # 简单汇总
        else:
            main_text = (
                f"{opening}{time_label}{org_scope}的{metric}为 {key_value:,.2f}。"
            )

        # 添加结尾
        main_text += random.choice(self.templates.OVERVIEW_ENDINGS)

        # 生成关键亮点
        highlights = self._generate_highlights(slots, rows, compare_target)

        return {
            "main_text": main_text,
            "key_highlights": highlights,
            "data_summary": f"共 {len(rows)} 行数据，关键值：{key_value:,.2f}" if rows else "无数据",
            "confidence": 0.95,
        }

    def generate_insights(
        self,
        *,
        original_query: str,
        slots: dict,
        rows: list[dict],
        summary: str | None = None,
        additional_context: dict | None = None,
    ) -> dict:
        """生成智能洞察卡片"""

        insights = []
        metric = slots.get("metric", "指标")
        compare_target = slots.get("compare_target")
        group_by = slots.get("group_by")

        # 检测对比洞察
        if compare_target in {"mom", "yoy"} and "current_value" in rows[0]:
            current = rows[0].get("current_value", 0) or 0
            compare = rows[0].get("compare_value", 0) or 0
            if compare != 0:
                change_pct = ((current - compare) / compare) * 100
                compare_label = "环比" if compare_target == "mom" else "同比"

                if change_pct > 0:
                    insights.append({
                        "title": f"{metric}{compare_label}增长",
                        "type": "comparison",
                        "summary": f"当前值 {current:,.2f} 较{compare_label} {compare:,.2f} 增长 {abs(change_pct):.1f}%，表现优异。",
                        "evidence": {
                            "current_value": current,
                            "compare_value": compare,
                            "delta": current - compare,
                            "change_pct": round(change_pct, 1),
                        },
                        "importance": "high",
                        "action_suggestion": "建议分析增长驱动因素，保持良好势头。",
                    })
                else:
                    insights.append({
                        "title": f"{metric}{compare_label}下降",
                        "type": "comparison",
                        "summary": f"当前值 {current:,.2f} 较{compare_label} {compare:,.2f} 下降 {abs(change_pct):.1f}%，需要关注。",
                        "evidence": {
                            "current_value": current,
                            "compare_value": compare,
                            "delta": current - compare,
                            "change_pct": round(change_pct, 1),
                        },
                        "importance": "high",
                        "action_suggestion": "建议深入分析下降原因，制定改进措施。",
                    })

        # 检测趋势洞察（按月分组）
        if group_by == "month" and len(rows) >= 3:
            trend_desc = self._analyze_trend(rows)
            insights.append({
                "title": f"{metric}趋势洞察",
                "type": "trend",
                "summary": f"数据显示 {metric}{trend_desc}，共 {len(rows)} 个数据点。",
                "evidence": {
                    "data_points": len(rows),
                    "sample": rows[:3],
                },
                "importance": "medium",
                "action_suggestion": "可进一步分析各月份驱动因素。",
            })

        # 检测排名洞察（按区域/电站分组）
        if group_by in {"region", "station"} and len(rows) > 1:
            top_row = max(rows, key=lambda r: self._extract_key_value([r]))
            top_name = top_row.get(group_by, "未知")
            top_value = self._extract_key_value([top_row])

            dimension = "电站" if group_by == "station" else "区域"
            insights.append({
                "title": f"{metric}{dimension}排名",
                "type": "ranking",
                "summary": f"{top_name}表现最佳，{metric}达到 {top_value:,.2f}，领先其他{top_dimension}。",
                "evidence": {
                    "dimension": top_name,
                    "value": top_value,
                    "row_count": len(rows),
                },
                "importance": "high",
                "action_suggestion": f"建议总结{top_name}的优秀实践，推广到其他{top_dimension}。",
            })

        # 检测异常值
        anomaly_rows = [
            row for row in rows
            if (row.get("current_value") or row.get("total_value") or 0) <= 0
        ]
        if anomaly_rows:
            insights.append({
                "title": "异常值提醒",
                "type": "anomaly",
                "summary": f"数据中发现 {len(anomaly_rows)} 条异常记录（零值或负值），建议核查数据质量。",
                "evidence": {
                    "anomaly_count": len(anomaly_rows),
                    "anomaly_rows": anomaly_rows[:3],  # 只保留前3条
                },
                "importance": "high",
                "action_suggestion": "建议联系数据负责人核查异常数据来源。",
            })

        # 生成整体分析结论
        if summary:
            overall = summary
        else:
            overall = f"本轮查询涉及 {metric}，共返回 {len(rows)} 条数据记录。"

        return {
            "insights": insights,
            "overall_analysis": overall,
            "data_quality_note": f"存在 {len(anomaly_rows)} 条异常记录" if anomaly_rows else None,
        }

    def generate_chart_desc(
        self,
        *,
        slots: dict,
        rows: list[dict],
    ) -> dict:
        """生成图表描述"""

        metric = slots.get("metric", "指标")
        group_by = slots.get("group_by")
        compare_target = slots.get("compare_target")

        # 选择图表类型
        if group_by == "month":
            chart_type = "line"
            title = f"{metric}月度趋势"
            description = f"折线图展示 {metric} 在各月份的连续变化趋势，便于观察周期性规律和长期走势。"
        elif group_by in {"region", "station"}:
            chart_type = "bar"
            dimension = "区域" if group_by == "region" else "电站"
            title = f"{metric}{dimension}分布"
            description = f"柱状图对比各{metric}在不同{dimension}的数值，直观展示各维度间的差异。"
        else:
            chart_type = "pie"
            title = f"{metric}构成"
            description = f"饼图展示 {metric} 的构成结构，适合展示占比关系。"

        # 添加对比说明
        if compare_target:
            compare_label = "环比" if compare_target == "mom" else "同比"
            description += f"图表中同时展示当前期与{compare_label}对比数据。"

        return {
            "chart_type": chart_type,
            "title": title,
            "description": description,
            "x_axis_label": group_by if group_by else None,
            "y_axis_label": metric,
            "key_insight_from_chart": f"通过图表可直观对比各维度的 {metric} 表现。",
        }

    def generate_report(
        self,
        *,
        original_query: str,
        summary: dict,
        insights: dict,
        data_details: dict,
    ) -> dict:
        """生成完整报告"""

        metric = slots = {}
        blocks = []

        # 执行摘要
        blocks.append({
            "block_type": "overview",
            "title": "分析概览",
            "content": summary.get("main_text", "暂无数据"),
            "importance": "high",
        })

        # 关键发现
        insight_list = insights.get("insights", [])
        if insight_list:
            findings_text = "\n".join([
                f"• **{insight['title']}**：{insight['summary']}"
                for insight in insight_list
            ])
            blocks.append({
                "block_type": "findings",
                "title": "关键发现",
                "content": findings_text,
                "importance": "high",
            })

        # 后续建议
        recommendations_text = "\n".join([
            f"{i+1}. {rec}"
            for i, rec in enumerate(random.sample(self.templates.RECOMMENDATIONS, min(3, len(self.templates.RECOMMENDATIONS))))
        ])
        blocks.append({
            "block_type": "recommendation",
            "title": "后续建议",
            "content": recommendations_text,
            "importance": "medium",
        })

        return {
            "blocks": blocks,
            "executive_summary": summary.get("main_text", ""),
            "next_steps": self.templates.RECOMMENDATIONS[:3],
        }

    # =============================================================================
    # 辅助方法
    # =============================================================================

    def _format_org_scope(self, org_scope: dict | str | None) -> str:
        """格式化组织范围"""
        if not org_scope:
            return "全部范围"
        if isinstance(org_scope, str):
            return org_scope
        if isinstance(org_scope, dict):
            return org_scope.get("value") or org_scope.get("name") or "全部范围"
        return "全部范围"

    def _extract_key_value(self, rows: list[dict]) -> float:
        """提取关键数值"""
        if not rows:
            return 0.0
        first_row = rows[0]
        return float(
            first_row.get("current_value")
            or first_row.get("total_value")
            or first_row.get("value")
            or 0
        )

    def _analyze_trend(self, rows: list[dict]) -> str:
        """分析数据趋势"""
        if len(rows) < 2:
            return "变化不明显"

        values = []
        for row in rows:
            v = row.get("current_value") or row.get("total_value") or 0
            values.append(float(v))

        first = values[0]
        last = values[-1]

        if last > first * 1.1:
            return "整体呈上升趋势"
        elif last < first * 0.9:
            return "整体呈下降趋势"
        else:
            return "整体保持稳定"

    def _generate_highlights(
        self,
        slots: dict,
        rows: list[dict],
        compare_target: str | None,
    ) -> list[str]:
        """生成关键亮点"""
        highlights = []
        metric = slots.get("metric", "指标")

        if not rows:
            return ["查询结果为空"]

        # 关键数值
        key_value = self._extract_key_value(rows)
        highlights.append(f"{metric}关键值：{key_value:,.2f}")

        # 对比情况
        if compare_target in {"mom", "yoy"} and "current_value" in rows[0]:
            current = rows[0].get("current_value", 0) or 0
            compare = rows[0].get("compare_value", 0) or 0
            if compare != 0:
                change_pct = ((current - compare) / compare) * 100
                direction = "增长" if change_pct > 0 else "下降"
                highlights.append(f"{compare_target.upper()}：{direction} {abs(change_pct):.1f}%")

        # 数据规模
        highlights.append(f"共 {len(rows)} 条记录")

        return highlights[:3]  # 最多3个亮点


# =============================================================================
# 全局单例
# =============================================================================

_mock_generator: MockLLMResponseGenerator | None = None


def get_mock_generator() -> MockLLMResponseGenerator:
    """获取 Mock 生成器单例"""
    global _mock_generator
    if _mock_generator is None:
        _mock_generator = MockLLMResponseGenerator()
    return _mock_generator
