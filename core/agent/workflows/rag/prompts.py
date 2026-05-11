"""RAG Agent Prompt 模板。

包含系统提示、查询理解提示、答案生成提示等。
"""

from __future__ import annotations

# ==================== 系统提示 ====================

SYSTEM_PROMPT = """你是一个企业知识问答助手，名为"能源小智"。

你的职责是：
1. 基于知识库中的文档回答用户问题
2. 如果知识库中有明确答案，基于文档准确回答
3. 如果知识库中没有相关信息，明确告知用户
4. 在回答中适当引用参考文档

你的能力：
- 理解集团制度政策
- 了解安全生产规程
- 熟悉设备检修流程
- 掌握新能源运维知识

回答要求：
- 语言简洁、专业、易懂
- 引用文档时标注来源 [1], [2] 等
- 不确定的内容不编造，如实说明
- 对于涉及安全、合规等重要内容，建议用户咨询专业人士
"""


# ==================== 查询理解提示 ====================

QUERY_UNDERSTANDING_PROMPT = """分析用户的问题，确定检索范围和意图。

问题：{query}

请确定：
1. 涉及的业务领域（制度政策/安全生产/设备检修/新能源运维/其他）
2. 需要的过滤条件（部门/安全级别/有效期等）
3. 是否需要澄清
4. 问题类型（事实查询/解释说明/操作指导/风险提示）

只返回 JSON 格式：
{{"domain": "...", "filters": {{}}, "need_clarification": false, "question_type": "...", "clarification_message": ""}}"""


# ==================== 答案生成提示 ====================

ANSWER_GENERATION_PROMPT = """基于以下检索到的文档内容，回答用户的问题。

检索到的文档：
---
{context}
---

用户问题：{query}

要求：
1. 如果文档中有明确答案，基于文档内容准确回答
2. 如果文档中没有相关信息，明确说明"知识库中未找到相关信息"
3. 在回答末尾列出参考来源，使用 [1], [2] 等格式标注
4. 对于涉及安全、合规的重要内容，给出适当提醒

回答："""


# ==================== 结果评估提示 ====================

RETRIEVAL_EVALUATION_PROMPT = """评估检索到的文档是否足够回答用户的问题。

用户问题：{query}

检索到的文档：
---
{context}
---

请评估：
1. 文档内容是否与问题相关
2. 文档内容是否足够回答问题
3. 是否存在矛盾或不一致的信息
4. 是否需要补充检索

返回 JSON 格式：
{{
    "sufficient": true/false,
    "relevance_score": 0.0-1.0,
    "coverage_score": 0.0-1.0,
    "confidence_score": 0.0-1.0,
    "issues": ["问题1", "问题2"],
    "suggestions": ["建议1", "建议2"]
}}"""


# ==================== 无结果提示 ====================

NO_RESULT_PROMPT = """知识库中未找到与您问题相关的内容。

这可能是因为：
1. 相关文档尚未入库
2. 文档内容与问题的表述方式不同
3. 问题超出了当前知识库的范围

建议您：
1. 尝试使用不同的关键词描述您的问题
2. 联系知识库管理员确认相关文档是否已上传
3. 如果问题涉及最新政策或规定，建议查阅官方发布的最新文件
"""


# ==================== 引用格式提示 ====================

CITATION_FORMAT_PROMPT = """
在回答中添加引用时，请遵循以下格式：

回答正文...

参考来源：
[1] 文档标题 - 章节名称 (第X页)
[2] 文档标题 - 章节名称 (第X页)

注意：
- 只引用与回答内容直接相关的文档
- 避免过度引用，保持回答简洁
- 表格数据也需要标注来源
"""


# ==================== 辅助函数 ====================

def build_answer_prompt(query: str, context: str) -> str:
    """构建答案生成 Prompt。

    Args:
        query: 用户问题
        context: 检索上下文

    Returns:
        格式化的 Prompt
    """
    return ANSWER_GENERATION_PROMPT.format(
        query=query,
        context=context or "无相关文档",
    )


def build_evaluation_prompt(query: str, context: str) -> str:
    """构建评估 Prompt。

    Args:
        query: 用户问题
        context: 检索上下文

    Returns:
        格式化的 Prompt
    """
    return RETRIEVAL_EVALUATION_PROMPT.format(
        query=query,
        context=context or "无相关文档",
    )


def build_clarification_prompt(query: str, issues: list[str]) -> str:
    """构建澄清 Prompt。

    Args:
        query: 用户原始问题
        issues: 需要澄清的问题列表

    Returns:
        格式化的澄清消息
    """
    issues_text = "\n".join(f"{i+1}. {issue}" for i, issue in enumerate(issues))

    return f"""您的问题「{query}」需要进一步澄清：

{issues_text}

请补充上述信息，以便我为您提供更准确的答案。
"""
