"""反思机制 - 对审查结果进行二次校验。

反思机制核心思想：
1. Agent 在得出结论后，主动审视自己的推理过程
2. 检查是否有遗漏的风险点
3. 验证结论是否合理
4. 如有疑问，触发补充检索或 Human Review

实现方式：
- 使用 LLM 进行反思分析
- 支持结构化输出
- 集成到 LangGraph 工作流

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)


# ==================== 反思结果模型 ====================


class ReflectionResult:
    """反思结果模型。"""

    def __init__(
        self,
        status: str,  # "通过" | "需改进" | "错误"
        confidence: str,  # "高" | "中" | "低"
        issues: list[dict],
        suggestions: list[str],
        needs_additional_retrieval: bool,
        retrieval_queries: list[str],
        needs_human_review: bool,
        raw_result: str,
    ) -> None:
        self.status = status
        self.confidence = confidence
        self.issues = issues
        self.suggestions = suggestions
        self.needs_additional_retrieval = needs_additional_retrieval
        self.retrieval_queries = retrieval_queries
        self.needs_human_review = needs_human_review
        self.raw_result = raw_result

    def to_dict(self) -> dict:
        """转换为字典。"""
        return {
            "status": self.status,
            "confidence": self.confidence,
            "issues": self.issues,
            "suggestions": self.suggestions,
            "needs_additional_retrieval": self.needs_additional_retrieval,
            "retrieval_queries": self.retrieval_queries,
            "needs_human_review": self.needs_human_review,
            "raw_result": self.raw_result,
        }


# ==================== 反思引擎 ====================


class ReflectionEngine:
    """反思引擎 - 对Agent输出进行二次校验。

    反思流程：
    1. 接收Agent生成的审查报告
    2. LLM主动审视报告中的风险点
    3. 检查是否有遗漏或误判
    4. 返回反思结果和建议

    设计原因：
    1. 提高审查质量 - 避免遗漏重要风险
    2. 减少误判 - 通过二次校验减少错误
    3. 触发补充检索 - 如发现遗漏可触发RAG补充
    4. 提升置信度 - 对结果进行量化评估
    """

    def __init__(self, llm: BaseChatModel) -> None:
        """初始化反思引擎。

        Args:
            llm: LLM实例，用于执行反思思考
        """
        self.llm = llm

        # 反思提示词模板
        self.prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content="""你是一个严谨的合同审核复核专家，擅长发现合同审查中的遗漏和错误。"""),
            HumanMessage(content=self._build_reflection_prompt_template()),
        ])

        # 带JSON解析的chain
        self.chain = self.prompt | self.llm | JsonOutputParser()

        # 纯文本chain（用于调试）
        from langchain_core.output_parsers import StrOutputParser
        self.text_chain = self.prompt | self.llm | StrOutputParser()

        logger.info("ReflectionEngine 初始化完成")

    def _build_reflection_prompt_template(self) -> str:
        """构建反思提示词模板。"""
        return """请对以下合同审查报告进行反思校验。

## 合同信息
合同名称：{contract_name}
合同类型：{contract_type}
业务域：{business_domain}

## 已抽取的条款
{clauses_summary}

## 识别的风险
{risks_summary}

## 审查结论
{conclusion}

## 检索到的法规
{laws_summary}

## 检索到的模板
{templates_summary}

## 反思要求

请从以下维度进行反思：

1. **风险识别完整性**
   - 是否有遗漏的重要风险点？
   - 是否有条款类型未被分析？

2. **法规依据充分性**
   - 引用的法规是否准确？
   - 是否有遗漏的相关法规？

3. **结论合理性**
   - 风险等级判定是否合理？
   - 建议是否可行？

4. **遗漏检测**
   - 是否有缺失的必要条款？
   - 是否有模糊表述未被发现？

## 输出格式

请输出JSON格式的反思结果：

```json
{
    "status": "通过/需改进/错误",
    "confidence": "高/中/低",
    "issues": [
        {
            "type": "遗漏/误判/不充分",
            "description": "问题描述",
            "location": "相关条款或位置",
            "severity": "高/中/低"
        }
    ],
    "suggestions": [
        "改进建议1",
        "改进建议2"
    ],
    "needs_additional_retrieval": true/false,
    "retrieval_queries": [
        "补充检索query1",
        "补充检索query2"
    ],
    "needs_human_review": true/false,
    "human_review_reason": "需要复核的具体原因（如需）"
}
```

请只输出JSON，不要有其他内容。"""

    async def reflect(
        self,
        contract_name: str,
        contract_type: Optional[str],
        business_domain: str,
        clauses: list[dict],
        risks: list[dict],
        conclusion: str,
        laws_context: Optional[list[dict]] = None,
        templates_context: Optional[list[dict]] = None,
    ) -> ReflectionResult:
        """执行反思校验。

        Args:
            contract_name: 合同名称
            contract_type: 合同类型
            business_domain: 业务域
            clauses: 已抽取的条款
            risks: 识别的风险
            conclusion: 审查结论
            laws_context: 检索到的法规
            templates_context: 检索到的模板

        Returns:
            反思结果
        """
        logger.info(f"开始执行反思校验 | contract={contract_name}")

        # 构建提示词
        clauses_summary = self._summarize_clauses(clauses)
        risks_summary = self._summarize_risks(risks)
        laws_summary = self._summarize_laws(laws_context or [])
        templates_summary = self._summarize_templates(templates_context or [])

        prompt_input = {
            "contract_name": contract_name,
            "contract_type": contract_type or "未知",
            "business_domain": business_domain,
            "clauses_summary": clauses_summary,
            "risks_summary": risks_summary,
            "conclusion": conclusion,
            "laws_summary": laws_summary,
            "templates_summary": templates_summary,
        }

        try:
            # 调用 LLM
            result = await self.chain.ainvoke(prompt_input)

            # 解析结果
            reflection = ReflectionResult(
                status=result.get("status", "需改进"),
                confidence=result.get("confidence", "中"),
                issues=result.get("issues", []),
                suggestions=result.get("suggestions", []),
                needs_additional_retrieval=result.get("needs_additional_retrieval", False),
                retrieval_queries=result.get("retrieval_queries", []),
                needs_human_review=result.get("needs_human_review", False),
                raw_result=str(result),
            )

            logger.info(
                f"反思完成 | status={reflection.status} | "
                f"confidence={reflection.confidence} | "
                f"issues={len(reflection.issues)}"
            )

            return reflection

        except Exception as e:
            logger.error(f"反思执行失败: {e}", exc_info=True)
            # 返回默认结果
            return ReflectionResult(
                status="需改进",
                confidence="低",
                issues=[{"type": "错误", "description": f"反思过程异常: {str(e)}", "severity": "高"}],
                suggestions=["建议人工复核"],
                needs_additional_retrieval=False,
                retrieval_queries=[],
                needs_human_review=True,
                raw_result="反思执行失败",
            )

    def reflect_sync(
        self,
        contract_name: str,
        contract_type: Optional[str],
        business_domain: str,
        clauses: list[dict],
        risks: list[dict],
        conclusion: str,
        laws_context: Optional[list[dict]] = None,
        templates_context: Optional[list[dict]] = None,
    ) -> ReflectionResult:
        """同步执行反思。"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(
            self.reflect(
                contract_name=contract_name,
                contract_type=contract_type,
                business_domain=business_domain,
                clauses=clauses,
                risks=risks,
                conclusion=conclusion,
                laws_context=laws_context,
                templates_context=templates_context,
            )
        )

    # ==================== 辅助方法 ====================

    def _summarize_clauses(self, clauses: list[dict]) -> str:
        """生成条款摘要。"""
        if not clauses:
            return "无条款数据"

        # 按类型分组
        by_type = {}
        for clause in clauses:
            ctype = clause.get("clause_type", "其他")
            if ctype not in by_type:
                by_type[ctype] = []
            by_type[ctype].append(clause)

        lines = []
        for ctype, items in by_type.items():
            lines.append(f"- {ctype}: {len(items)}条")
            for item in items[:2]:  # 每类最多显示2条
                lines.append(f"  • {item.get('clause_id', '')}: {item.get('clause_title', '')[:30]}...")

        return "\n".join(lines) if lines else "无条款"

    def _summarize_risks(self, risks: list[dict]) -> str:
        """生成风险摘要。"""
        if not risks:
            return "未识别到风险"

        high = [r for r in risks if r.get("risk_type") == "high"]
        medium = [r for r in risks if r.get("risk_type") == "medium"]
        low = [r for r in risks if r.get("risk_type") == "low"]

        lines = [f"高风险: {len(high)}项", f"中风险: {len(medium)}项", f"低风险: {len(low)}项"]

        # 显示高风险项详情
        if high:
            lines.append("\n高风险项详情：")
            for r in high[:3]:
                lines.append(f"  • [{r.get('risk_id')}] {r.get('risk_description', '')}")
                lines.append(f"    相关条款: {r.get('related_clause', '')}")

        return "\n".join(lines)

    def _summarize_laws(self, laws: list[dict]) -> str:
        """生成法规摘要。"""
        if not laws:
            return "无检索到法规"

        lines = [f"共检索到 {len(laws)} 条法规："]
        for law in laws[:5]:
            lines.append(f"  • {law.get('title', '')} - {law.get('chapter', '')}")

        return "\n".join(lines)

    def _summarize_templates(self, templates: list[dict]) -> str:
        """生成模板摘要。"""
        if not templates:
            return "无检索到模板"

        lines = [f"共检索到 {len(templates)} 个模板："]
        for tpl in templates[:3]:
            lines.append(f"  • {tpl.get('name', '')} (v{tpl.get('version', '')})")

        return "\n".join(lines)


# ==================== 简化反思器（用于快速集成） ====================


class SimpleReflection:
    """简化的反思器 - 基于规则的快速检查。

    当 LLM 不可用时，使用规则进行快速反思。
    """

    @staticmethod
    def reflect(
        clauses: list[dict],
        risks: list[dict],
        conclusion: str,
    ) -> ReflectionResult:
        """基于规则的快速反思。

        检查规则：
        1. 必须有条款数据
        2. 高风险必须有具体条款
        3. 结论必须与风险匹配
        """
        issues = []
        suggestions = []

        # 检查1：条款数据
        if not clauses:
            issues.append({
                "type": "遗漏",
                "description": "未抽取到合同条款",
                "severity": "高",
            })
            suggestions.append("请重新解析合同文档")

        # 检查2：风险与条款匹配
        risk_clause_ids = {r.get("related_clause") for r in risks}
        clause_ids = {c.get("clause_id") for c in clauses}
        unmatched = risk_clause_ids - clause_ids

        if unmatched:
            issues.append({
                "type": "不匹配",
                "description": f"部分风险项找不到对应条款: {unmatched}",
                "severity": "中",
            })

        # 检查3：结论与风险匹配
        high_risk_count = len([r for r in risks if r.get("risk_type") == "high"])

        if high_risk_count > 0 and "高风险" not in conclusion:
            issues.append({
                "type": "误判",
                "description": "存在高风险项但结论未提及",
                "severity": "高",
            })
            suggestions.append("结论应明确提及高风险项")

        # 判断状态
        if not issues:
            status = "通过"
            confidence = "高"
        elif any(i.get("severity") == "高" for i in issues):
            status = "需改进"
            confidence = "低"
        else:
            status = "需改进"
            confidence = "中"

        # 判断是否需要人工复核
        needs_human_review = high_risk_count > 0

        return ReflectionResult(
            status=status,
            confidence=confidence,
            issues=issues,
            suggestions=suggestions,
            needs_additional_retrieval=len(issues) > 0,
            retrieval_queries=["补充检索相关法规"] if issues else [],
            needs_human_review=needs_human_review,
            raw_result="基于规则的快速反思",
        )
