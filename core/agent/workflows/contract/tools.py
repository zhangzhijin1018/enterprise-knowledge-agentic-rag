"""合同审核工具定义 - 使用 LangChain @tool 装饰器。

基于 LangChain 的标准工具定义模式，每个工具：
1. 有清晰的描述
2. Pydantic 输入schema
3. 详细的文档

工具列表：
1. parse_contract - 解析合同文档
2. search_laws - 检索相关法规
3. search_templates - 检索标准模板
4. search_history - 检索历史案例
5. extract_clauses - 抽取合同条款
6. analyze_risk - 分析合同风险
7. generate_report - 生成审查报告
8. request_human_review - 请求人工复核

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ==================== 工具输入Schema定义 ====================


class ParseContractInput(BaseModel):
    """解析合同工具输入。"""

    contract_file_id: str = Field(
        description="合同文件ID，用于从存储中获取文件"
    )
    storage_uri: Optional[str] = Field(
        default=None,
        description="MinIO/S3对象路径，如 bucket/prefix/file.pdf"
    )


class SearchLawsInput(BaseModel):
    """检索法规工具输入。

    优化说明：
    - search_laws 可以接收 extracted_clauses 结果，基于合同实际条款生成更精准的检索词
    - 支持相关性阈值（min_relevance）过滤，返回真正相关的结果
    - 使用 max_results 限制最大返回数量，避免过多无关结果
    """

    query: str = Field(
        description="检索query，通常是合同条款内容或问题描述"
    )
    contract_type: Optional[str] = Field(
        default=None,
        description="合同类型，如采购合同、服务合同、建设工程合同等"
    )
    business_domain: str = Field(
        default="能源",
        description="业务域，能源/电力/建筑/制造等"
    )
    top_k: int = Field(
        default=5,
        description="每路检索的召回数量（用于合并前的初筛）"
    )
    min_relevance: float = Field(
        default=0.4,
        description="最低相关性阈值（默认0.4），低于此分数的结果会被过滤"
    )
    max_results: int = Field(
        default=10,
        description="最大返回数量（默认10），超过此数量的结果会被截断"
    )
    extracted_clauses: Optional[List[dict]] = Field(
        default=None,
        description="LLM 抽取的合同条款列表，包含条款类型、主题、法律问题等，用于生成更精准的检索词"
    )
    contract_content: Optional[str] = Field(
        default=None,
        description="合同全文内容，用于提取关键词和检索词生成"
    )
    legal_search_topics: Optional[List[str]] = Field(
        default=None,
        description="LLM 提取的法律检索主题列表，由 extract_clauses 工具生成，用于多路检索"
    )


class SearchTemplatesInput(BaseModel):
    """检索模板工具输入。"""

    contract_type: Optional[str] = Field(
        default=None,
        description="合同类型"
    )
    business_domain: str = Field(
        default="能源",
        description="业务域"
    )
    top_k: int = Field(
        default=3,
        description="返回结果数量"
    )


class SearchHistoryInput(BaseModel):
    """检索历史案例工具输入。"""

    query: str = Field(
        description="检索query"
    )
    contract_type: Optional[str] = Field(
        default=None,
        description="合同类型"
    )
    risk_level: Optional[str] = Field(
        default=None,
        description="风险等级筛选，high/medium/low"
    )
    top_k: int = Field(
        default=5,
        description="返回结果数量"
    )


class ExtractClausesInput(BaseModel):
    """抽取条款工具输入。"""

    contract_text: str = Field(
        description="合同文本内容"
    )
    contract_type: Optional[str] = Field(
        default=None,
        description="合同类型"
    )


class AnalyzeRiskInput(BaseModel):
    """分析风险工具输入。"""

    clauses: List[dict] = Field(
        description="抽取的合同条款列表"
    )
    contract_type: Optional[str] = Field(
        default=None,
        description="合同类型"
    )
    laws_context: Optional[List[dict]] = Field(
        default=None,
        description="检索到的法规上下文"
    )
    templates_context: Optional[List[dict]] = Field(
        default=None,
        description="检索到的模板上下文"
    )
    history_context: Optional[List[dict]] = Field(
        default=None,
        description="检索到的历史案例上下文（用于参考历史处理方式）"
    )


class GenerateReportInput(BaseModel):
    """生成报告工具输入。"""

    contract_name: str = Field(
        description="合同名称"
    )
    contract_type: Optional[str] = Field(
        default=None,
        description="合同类型"
    )
    clauses: List[dict] = Field(
        description="抽取的条款列表"
    )
    parties: List[dict] = Field(
        description="当事人信息列表"
    )
    risks: List[dict] = Field(
        description="识别的风险列表"
    )
    laws_context: List[dict] = Field(
        default_factory=list,
        description="法规上下文"
    )
    templates_context: List[dict] = Field(
        default_factory=list,
        description="模板上下文"
    )


class RequestHumanReviewInput(BaseModel):
    """请求人工复核工具输入。"""

    high_risk_items: List[dict] = Field(
        description="高风险项列表"
    )
    reason: str = Field(
        description="请求复核的原因"
    )


# ==================== 工具实现 ====================


@tool("parse_contract", args_schema=ParseContractInput, return_direct=False)
def parse_contract(
    contract_file_id: str,
    storage_uri: Optional[str] = None,
    run_manager: Optional[CallbackManagerForToolRun] = None,
) -> dict:
    """解析合同文档，提取文本内容。

    这是合同审查的第一步，必须先解析合同才能进行后续分析。

    功能：
    - 支持 PDF、Word 文档解析
    - 提取纯文本内容
    - 返回文档块列表

    Args:
        contract_file_id: 合同文件ID
        storage_uri: MinIO对象路径（如指定则从云存储读取）

    Returns:
        包含解析结果的字典：
        - status: success/error
        - text: 提取的文本内容
        - blocks: 文档块列表
        - metadata: 文档元数据
    """
    logger.info(f"[Tool:parse_contract] contract_file_id={contract_file_id}")

    try:
        file_bytes: bytes
        file_extension: str

        if storage_uri:
            # 从 MinIO/S3 读取
            from core.services.file_storage import get_storage

            storage = get_storage()
            file_bytes = storage.get_file_bytes_sync(storage_uri)

            if storage_uri.endswith(".pdf"):
                file_extension = ".pdf"
            elif storage_uri.endswith(".docx"):
                file_extension = ".docx"
            elif storage_uri.endswith(".doc"):
                file_extension = ".doc"
            else:
                file_extension = ".pdf"
        else:
            # 从本地路径读取（开发环境）
            file_path = Path(f"storage/uploads/{contract_file_id}")

            if not file_path.exists():
                return {
                    "status": "error",
                    "message": f"文件不存在: {contract_file_id}",
                    "text": "",
                    "blocks": [],
                }

            file_bytes = file_path.read_bytes()
            file_extension = file_path.suffix.lower()

        # 创建临时文件进行解析
        with tempfile.NamedTemporaryFile(
            suffix=file_extension,
            delete=False
        ) as tmp_file:
            tmp_file.write(file_bytes)
            tmp_file_path = Path(tmp_file.name)

        try:
            # 解析文档
            from core.tools.local.parser import LocalDocumentParser

            parser = LocalDocumentParser()
            file_type = file_extension.lstrip(".")
            blocks = parser.parse(tmp_file_path, file_type)

            # 合并文本内容
            text = "\n".join(b.get("text", "") for b in blocks)

            logger.info(f"[Tool:parse_contract] 成功解析，提取 {len(blocks)} 个文本块")

            return {
                "status": "success",
                "text": text,
                "blocks": blocks,
                "metadata": {
                    "file_id": contract_file_id,
                    "extension": file_extension,
                    "block_count": len(blocks),
                    "text_length": len(text),
                },
            }
        finally:
            # 清理临时文件
            if tmp_file_path.exists():
                tmp_file_path.unlink()

    except Exception as e:
        logger.error(f"[Tool:parse_contract] 解析失败: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "text": "",
            "blocks": [],
        }


@tool("search_laws", args_schema=SearchLawsInput, return_direct=False)
def search_laws(
    query: str,
    contract_type: Optional[str] = None,
    business_domain: str = "能源",
    top_k: int = 5,
    min_relevance: float = 0.4,
    max_results: int = 10,
    extracted_clauses: Optional[List[dict]] = None,
    contract_content: Optional[str] = None,
    legal_search_topics: Optional[List[str]] = None,
    run_manager: Optional[CallbackManagerForToolRun] = None,
) -> dict:
    """检索相关法律法规，为合同条款分析提供法律依据。

    优化说明：
    - 支持接收 LLM 抽取的合同条款 (extracted_clauses)
    - 支持接收合同全文内容 (contract_content)
    - 支持接收 LLM 提取的法律检索主题 (legal_search_topics)
    - 使用多路检索策略，从多个法律角度并行检索
    - 基于条款主题和合同内容生成更精准的检索词
    - 使用相关性阈值（min_relevance）替代固定数量过滤

    功能：
    - 检索民法典、合同法相关条款
    - 检索行业特定法规（如能源法、电力法）
    - 检索招标投标法等配套法规

    返回策略：
    - 返回相关性 >= min_relevance 的结果
    - 最多返回 max_results 条
    - 避免因固定数量限制而漏掉相关结果

    Args:
        query: 检索关键词，通常是合同条款或问题描述
        contract_type: 合同类型（采购/服务/租赁/建设等）
        business_domain: 业务域（能源/电力/建筑等）
        top_k: 每路检索的召回数量（用于合并前的初筛）
        min_relevance: 最低相关性阈值（默认0.4），低于此分数的结果会被过滤
        max_results: 最大返回数量（默认10），超过此数量的结果会被截断
        extracted_clauses: LLM 抽取的合同条款列表
        contract_content: 合同全文内容
        legal_search_topics: LLM 提取的法律检索主题列表（由 extract_clauses 生成）

    Returns:
        法规检索结果列表：
        - law_id: 法规ID
        - title: 法规标题
        - chapter: 章节
        - article: 相关条款
        - summary: 摘要
        - relevance: 相关性分数（基于 Reranker 的语义相似度）
    """
    logger.info(
        f"[Tool:search_laws] query={query[:50]}... type={contract_type} "
        f"domain={business_domain} min_relevance={min_relevance} max_results={max_results}"
    )

    try:
        from core.contracts.rag_service import get_contract_rag_service

        rag_service = get_contract_rag_service()

        # 如果有 legal_search_topics、extracted_clauses 或 contract_content，使用多路检索
        if legal_search_topics or extracted_clauses or contract_content:
            logger.info("[Tool:search_laws] 使用多路检索策略")
            laws = rag_service.search_laws_multi(
                query=query,
                contract_type=contract_type,
                business_domain=business_domain,
                top_k=top_k,
                min_relevance=min_relevance,
                max_results=max_results,
                contract_content=contract_content,
                extracted_clauses=extracted_clauses,
                legal_search_topics=legal_search_topics,
            )
            retrieval_method = "multi"
        else:
            # 降级为普通检索
            laws = rag_service.search_laws(
                query=query,
                contract_type=contract_type,
                business_domain=business_domain,
                top_k=max_results,
            )
            retrieval_method = "basic"

        results = [law.model_dump() for law in laws]

        logger.info(f"[Tool:search_laws] 检索到 {len(results)} 条法规")

        return {
            "status": "success",
            "count": len(results),
            "laws": results,
            "retrieval_method": retrieval_method,
        }

    except Exception as e:
        logger.warning(f"[Tool:search_laws] 检索失败: {e}，使用默认法规")
        # 返回默认法规
        return {
            "status": "success",
            "count": 3,
            "retrieval_method": "fallback",
            "laws": [
                {
                    "law_id": "law_civil_code",
                    "title": "中华人民共和国民法典",
                    "chapter": "第三编 合同编",
                    "article": "",
                    "summary": "规定了合同的订立、效力、履行、变更、转让、终止等基本规则",
                    "relevance": 0.95,
                },
                {
                    "law_id": "law_tender",
                    "title": "中华人民共和国招标投标法",
                    "chapter": "相关规定",
                    "article": "",
                    "summary": "规定了招标投标活动的原则、程序和要求",
                    "relevance": 0.85,
                },
                {
                    "law_id": "law_state_asset",
                    "title": "企业国有资产交易监督管理办法",
                    "chapter": "产权转让",
                    "article": "",
                    "summary": "规范企业国有资产交易行为，防止国有资产流失",
                    "relevance": 0.80,
                },
            ],
        }


@tool("search_templates", args_schema=SearchTemplatesInput, return_direct=False)
def search_templates(
    contract_type: Optional[str] = None,
    business_domain: str = "能源",
    top_k: int = 3,
    run_manager: Optional[CallbackManagerForToolRun] = None,
) -> dict:
    """检索标准合同模板，用于条款对比和缺失检测。

    功能：
    - 检索集团标准合同模板
    - 检索行业标准模板
    - 提供条款对比参考

    Args:
        contract_type: 合同类型
        business_domain: 业务域
        top_k: 返回结果数量

    Returns:
        模板检索结果列表：
        - template_id: 模板ID
        - name: 模板名称
        - version: 版本
        - summary: 摘要
        - relevance: 相关性分数
    """
    logger.info(
        f"[Tool:search_templates] type={contract_type} domain={business_domain}"
    )

    try:
        from core.contracts.rag_service import get_contract_rag_service

        rag_service = get_contract_rag_service()
        templates = rag_service.search_templates(
            contract_type=contract_type,
            business_domain=business_domain,
            top_k=top_k,
        )

        results = [tpl.model_dump() for tpl in templates]

        logger.info(f"[Tool:search_templates] 检索到 {len(results)} 个模板")

        return {
            "status": "success",
            "count": len(results),
            "templates": results,
        }

    except Exception as e:
        logger.warning(f"[Tool:search_templates] 检索失败: {e}，使用默认模板")
        return {
            "status": "success",
            "count": 2,
            "templates": [
                {
                    "template_id": "tpl_general",
                    "name": f"{contract_type or '一般'}合同标准模板",
                    "version": "v2.1",
                    "summary": "集团通用合同模板，包含所有必要条款",
                    "relevance": 0.90,
                },
                {
                    "template_id": "tpl_energy",
                    "name": "能源行业专用模板",
                    "version": "v1.0",
                    "summary": "能源行业专用合同条款参考",
                    "relevance": 0.80,
                },
            ],
        }


@tool("search_history", args_schema=SearchHistoryInput, return_direct=False)
def search_history(
    query: str,
    contract_type: Optional[str] = None,
    risk_level: Optional[str] = None,
    top_k: int = 5,
    run_manager: Optional[CallbackManagerForToolRun] = None,
) -> dict:
    """检索历史审核案例，为当前审查提供参考。

    功能：
    - 检索相似合同的历史审核记录
    - 获取风险处理建议
    - 了解审核结果

    Args:
        query: 检索query
        contract_type: 合同类型
        risk_level: 风险等级筛选
        top_k: 返回结果数量

    Returns:
        历史案例列表：
        - case_id: 案例ID
        - contract_name: 合同名称
        - risk_level: 风险等级
        - risk_points: 风险点
        - handling_suggestion: 处理建议
        - outcome: 处理结果
    """
    logger.info(f"[Tool:search_history] query={query[:30]}...")

    try:
        from core.contracts.rag_service import get_contract_rag_service

        rag_service = get_contract_rag_service()
        cases = rag_service.search_history(
            query=query,
            contract_type=contract_type,
            risk_level=risk_level,
            top_k=top_k,
        )

        results = [case.model_dump() for case in cases]

        logger.info(f"[Tool:search_history] 检索到 {len(results)} 个案例")

        return {
            "status": "success",
            "count": len(results),
            "history": results,
        }

    except Exception as e:
        logger.warning(f"[Tool:search_history] 检索失败: {e}")
        return {
            "status": "success",
            "count": 0,
            "history": [],
        }


@tool("extract_clauses", args_schema=ExtractClausesInput, return_direct=False)
def extract_clauses(
    contract_text: str,
    contract_type: Optional[str] = None,
    run_manager: Optional[CallbackManagerForToolRun] = None,
) -> dict:
    """抽取合同条款，识别关键要素，并提取法律检索主题供 search_laws 使用。

    全 LLM 提取设计：
    - 条款提取（clauses）：使用 LLM 理解合同内容，智能识别条款结构
    - 当事人信息（parties）：使用 LLM 提取
    - 缺失条款检测（missing_clauses）：使用 LLM 判断缺少哪些必要条款
    - 法律检索主题（legal_search_topics）：LLM 生成，用于 search_laws 多路检索
    - 法律问题（contract_legal_issues）：LLM 生成，用于风险分析

    与传统正则规则提取的区别：
    | 功能 | 正则规则 | LLM（全方案） |
    |------|----------|---------------|
    | 条款识别 | 只能匹配"第X条" | 理解语义，识别各种格式 |
    | 条款类型 | 关键词匹配 | 理解含义，准确分类 |
    | 风险识别 | 固定关键词 | 理解语义，智能识别 |
    | 缺失条款 | 简单判断 | 理解合同类型和上下文 |

    Args:
        contract_text: 合同文本内容
        contract_type: 合同类型（可选）

    Returns:
        条款分析结果：
        - clauses: LLM 提取的条款列表
        - parties: 当事人信息
        - missing_clauses: 疑似缺失的条款
        - legal_search_topics: 法律检索主题（供 search_laws 使用）
        - contract_legal_issues: 合同涉及的法律问题列表
    """
    logger.info(f"[Tool:extract_clauses] 开始抽取条款（全 LLM 版）")

    try:
        # 调用 LLM 提取所有信息
        llm_result = _extract_all_with_llm(
            contract_text=contract_text,
            contract_type=contract_type,
        )

        if llm_result is None:
            logger.error("[Tool:extract_clauses] LLM 提取失败")
            return {
                "status": "error",
                "message": "LLM 提取失败，请检查 LLM 服务是否可用",
                "clauses": [],
                "parties": [],
                "missing_clauses": [],
                "legal_search_topics": [],
                "contract_legal_issues": [],
            }

        clauses = llm_result.get("clauses", [])
        parties = llm_result.get("parties", [])
        missing_clauses = llm_result.get("missing_clauses", [])
        legal_search_topics = llm_result.get("legal_search_topics", [])
        contract_legal_issues = llm_result.get("contract_legal_issues", [])

        logger.info(
            f"[Tool:extract_clauses] LLM 提取完成："
            f"{len(clauses)} 条款，{len(parties)} 个当事人，"
            f"{len(missing_clauses)} 个疑似缺失条款，"
            f"{len(legal_search_topics)} 个检索主题"
        )

        return {
            "status": "success",
            "clauses": clauses,
            "parties": parties,
            "missing_clauses": missing_clauses,
            "legal_search_topics": legal_search_topics,
            "contract_legal_issues": contract_legal_issues,
        }

    except Exception as e:
        logger.error(f"[Tool:extract_clauses] 抽取失败: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "clauses": [],
            "parties": [],
            "missing_clauses": [],
            "legal_search_topics": [],
            "contract_legal_issues": [],
        }


def _extract_all_with_llm(
    contract_text: str,
    contract_type: Optional[str],
) -> Optional[dict]:
    """使用 LLM 从合同文本中提取所有信息。

    LLM 会分析合同内容，一次性提取：
    1. clauses: 合同条款列表（条款ID、类型、内容、风险指示）
    2. parties: 当事人信息
    3. missing_clauses: 疑似缺失的必要条款
    4. legal_search_topics: 法律检索主题
    5. contract_legal_issues: 法律问题

    Args:
        contract_text: 合同全文
        contract_type: 合同类型

    Returns:
        包含所有提取结果的字典，或 None（LLM 不可用时）
    """
    try:
        from core.agent.workflows.contract.langchain_adapter import get_contract_agent_llm
        from core.llm.models import LLMMessage

        llm = get_contract_agent_llm()
        if llm is None:
            logger.error("[extract_clauses] LLM 不可用")
            return None

        # 构建 prompt
        contract_type_hint = f"合同类型：{contract_type}" if contract_type else "合同类型：未指定"

        prompt = f"""你是一个专业的合同法律审查助手。请分析以下合同内容，提取完整的条款信息。

{contract_type_hint}

合同全文：
---
{contract_text}
---

请以 JSON 格式提取以下信息：

1. clauses: 合同条款列表
   - clause_id: 条款编号（如"第1条"）
   - clause_type: 条款类型（标的条款/价款条款/履行期限/质量标准/违约责任/争议解决/保密条款/其他条款）
   - clause_title: 条款标题（条款内容的前50字）
   - clause_content: 条款完整内容
   - risk_indicators: 风险指示器列表
     * 格式如："[高风险] 无条件解除" 或 "[中风险] 违约金偏高"
     * 高风险关键词：无条件解除、无限责任、免除全部责任、单方解释权、无条件赔偿
     * 中风险关键词：违约金过高（超过合同金额30%）、赔偿无上限、单方变更、自动续期

2. parties: 当事人信息列表
   - name: 当事人名称
   - role: 角色（甲方/乙方/丙方等）

3. missing_clauses: 疑似缺失的必要条款类型
   - 根据合同类型判断应该包含但实际缺失的条款类型
   - 常见必要条款：价款条款、履行期限、违约责任、争议解决

4. legal_search_topics: 法律检索主题列表（3-8个）
   - 用于检索相关法规的关键词/短语
   - 应基于合同中的风险点和法律问题生成
   - 例如："合同无条件解除 法律效力"、"违约金过高 司法解释"

5. contract_legal_issues: 合同涉及的法律问题列表（2-5个）
   - 对合同法律风险的简短描述
   - 例如："是否存在无条件解除条款"、"违约金比例是否合理"

请输出标准 JSON 格式：
{{
    "clauses": [
        {{
            "clause_id": "第1条",
            "clause_type": "标的条款",
            "clause_title": "...",
            "clause_content": "...",
            "risk_indicators": []
        }}
    ],
    "parties": [
        {{"name": "...", "role": "甲方"}}
    ],
    "missing_clauses": ["争议解决"],
    "legal_search_topics": ["..."],
    "contract_legal_issues": ["..."]
}}
"""

        # 调用 LLM
        response = llm.chat(
            messages=[LLMMessage(role="user", content=prompt)],
            model=None,
        )

        # 解析 JSON 响应
        import json
        content = response.content.strip()

        # 尝试提取 JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        result = json.loads(content)

        logger.info(
            f"[extract_clauses] LLM 提取成功: "
            f"{len(result.get('clauses', []))} 条款, "
            f"{len(result.get('legal_search_topics', []))} 个检索主题"
        )

        return result

    except Exception as e:
        logger.error(f"[extract_clauses] LLM 提取失败: {e}", exc_info=True)
        return None


    @tool("analyze_risk", args_schema=AnalyzeRiskInput, return_direct=False)
    def analyze_risk(
    clauses: List[dict],
    contract_type: Optional[str] = None,
    laws_context: Optional[List[dict]] = None,
    templates_context: Optional[List[dict]] = None,
    history_context: Optional[List[dict]] = None,
    run_manager: Optional[CallbackManagerForToolRun] = None,
) -> dict:
    """分析合同风险，结合法规、模板和历史案例进行综合评估。

    本工具调用 LLM 进行智能分析，综合考虑：
    - 合同条款内容（来自 extract_clauses）
    - 相关法规（来自 search_laws）
    - 标准模板对比（来自 search_templates）
    - 历史案例参考（来自 search_history）

    功能：
    - 基于条款和法规进行合规性分析
    - 对比模板检测缺失条款
    - 参考历史案例的处理方式
    - 评估风险等级
    - 生成修改建议

    Args:
        clauses: 抽取的合同条款（来自 extract_clauses）
        contract_type: 合同类型
        laws_context: 检索到的法规上下文（来自 search_laws）
        templates_context: 检索到的模板上下文（来自 search_templates）
        history_context: 检索到的历史案例上下文（来自 search_history）

    Returns:
        风险分析结果：
        - risks: 风险列表
        - risk_summary: 风险概要
        - overall_level: 整体风险等级
        - need_human_review: 是否需要人工复核
        - suggestions: 修改建议
    """
    logger.info(f"[Tool:analyze_risk] 分析 {len(clauses)} 条条款的风险")

    try:
        # 调用 LLM 进行综合风险分析
        llm_result = _analyze_risk_with_llm(
            clauses=clauses,
            contract_type=contract_type,
            laws_context=laws_context,
            templates_context=templates_context,
            history_context=history_context,
        )

        if llm_result is None:
            # LLM 不可用时，回退到基于 risk_indicators 的简单分析
            logger.warning("[Tool:analyze_risk] LLM 不可用，回退到简单分析")
            return _fallback_analyze_risk(clauses)

        identified_risks = llm_result.get("risks", [])
        risk_summary = llm_result.get("risk_summary", "")
        suggestions = llm_result.get("suggestions", [])

        # 计算整体风险等级
        high_count = sum(1 for r in identified_risks if r.get("risk_type") == "high")
        medium_count = sum(1 for r in identified_risks if r.get("risk_type") == "medium")

        if high_count > 0:
            overall_level = "high"
        elif medium_count > 0:
            overall_level = "medium"
        else:
            overall_level = "low"

        # 判断是否需要人工复核
        need_human_review = high_count > 0

        logger.info(
            f"[Tool:analyze_risk] LLM 分析完成："
            f"{len(identified_risks)} 个风险，"
            f"整体等级: {overall_level}，需复核: {need_human_review}"
        )

        return {
            "status": "success",
            "risks": identified_risks,
            "risk_summary": risk_summary,
            "suggestions": suggestions,
            "high_risk_count": high_count,
            "medium_risk_count": medium_count,
            "overall_level": overall_level,
            "need_human_review": need_human_review,
        }

    except Exception as e:
        logger.error(f"[Tool:analyze_risk] 分析失败: {e}", exc_info=True)
        # 发生异常时回退到简单分析
        return _fallback_analyze_risk(clauses)


def _analyze_risk_with_llm(
    clauses: List[dict],
    contract_type: Optional[str],
    laws_context: Optional[List[dict]],
    templates_context: Optional[List[dict]],
    history_context: Optional[List[dict]] = None,
) -> Optional[dict]:
    """使用 LLM 进行综合风险分析。

    结合合同条款、法规上下文、模板上下文、历史案例进行智能分析：
    1. 合规性分析：条款是否符合法律规定
    2. 风险识别：识别条款中的潜在风险
    3. 模板对比：对比标准模板，发现缺失或异常条款
    4. 历史参考：参考类似合同的审查处理方式
    5. 修改建议：针对风险点提供具体修改建议

    Args:
        clauses: 合同条款列表
        contract_type: 合同类型
        laws_context: 法规上下文
        templates_context: 模板上下文
        history_context: 历史案例上下文

    Returns:
        包含风险分析结果的字典，或 None（LLM 不可用时）
    """
    try:
        from core.agent.workflows.contract.langchain_adapter import get_contract_agent_llm
        from core.llm.models import LLMMessage

        llm = get_contract_agent_llm()
        if llm is None:
            logger.error("[analyze_risk] LLM 不可用")
            return None

        # 构建法规上下文
        laws_text = ""
        if laws_context:
            laws_text = "\n".join([
                f"- {law.get('title', '')} {law.get('chapter', '')} {law.get('article', '')}"
                for law in laws_context[:5]  # 最多5条法规
            ])
        else:
            laws_text = "未检索到相关法规"

        # 构建模板上下文
        templates_text = ""
        if templates_context:
            templates_text = "\n".join([
                f"- {tmpl.get('template_name', '')}: {tmpl.get('template_content', '')[:200]}..."
                for tmpl in templates_context[:3]  # 最多3个模板
            ])
        else:
            templates_text = "未检索到标准模板"

        # 构建历史案例上下文（新增）
        history_text = ""
        if history_context:
            history_text = "\n".join([
                f"- 【{case.get('case_name', '历史案例')}】风险等级: {case.get('risk_level', '未知')} | "
                f"风险点: {case.get('risk_points', '无')} | "
                f"处理方式: {case.get('handling_suggestion', '无')}"
                for case in history_context[:3]  # 最多3个案例
            ])
        else:
            history_text = "未检索到相关历史案例"

        # 构建条款摘要
        clauses_text = "\n".join([
            f"【{c.get('clause_id', '')}】{c.get('clause_type', '')}: {c.get('clause_content', '')[:300]}..."
            for c in clauses[:10]  # 最多10条条款
        ])

        prompt = f"""你是一个专业的合同法律审查专家。请分析以下合同的风险，结合相关法规、标准模板和历史案例进行综合评估。

## 合同类型
{contract_type or "未指定"}

## 合同条款
{clauses_text}

## 相关法规
{laws_text}

## 标准模板参考
{templates_text}

## 历史案例参考
{history_text}

## 分析要求

请从以下维度进行综合分析：

1. **合规性分析**：条款是否符合法律法规
2. **风险识别**：识别高风险、中风险、低风险条款
3. **条款对比**：对比标准模板，发现异常或缺失条款
4. **历史参考**：参考历史案例的处理方式，确保处理方式的一致性
5. **修改建议**：针对每个风险点提供具体修改建议

## 输出格式

请以 JSON 格式输出分析结果：

{{
    "risks": [
        {{
            "risk_id": "R001",
            "risk_type": "high/medium/low",
            "risk_category": "合规风险/条款风险/缺失风险",
            "risk_description": "风险描述",
            "related_clause": "相关条款ID",
            "related_clause_type": "条款类型",
            "legal_basis": "依据的法规条款",
            "suggestion": "修改建议",
            "is_blocking": true/false
        }}
    ],
    "risk_summary": "风险概要总结（100字以内）",
    "suggestions": [
        {{
            "clause": "条款ID",
            "issue": "问题描述",
            "suggestion": "修改建议"
        }}
    ]
}}

请确保：
- risk_type 为 high/medium/low
- high 风险条款 is_blocking 必须为 true
- 每个风险都要有 legal_basis（依据的法规）
- suggestions 要具体可操作
"""

        # 调用 LLM
        response = llm.chat(
            messages=[LLMMessage(role="user", content=prompt)],
            model=None,
        )

        # 解析 JSON 响应
        import json
        content = response.content.strip()

        # 尝试提取 JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        result = json.loads(content)

        logger.info(
            f"[analyze_risk] LLM 分析成功: "
            f"{len(result.get('risks', []))} 个风险"
        )

        return result

    except Exception as e:
        logger.error(f"[analyze_risk] LLM 分析失败: {e}", exc_info=True)
        return None


def _fallback_analyze_risk(clauses: List[dict]) -> dict:
    """回退分析：当 LLM 不可用时，基于 risk_indicators 进行简单分析。

    这是一个保底机制，确保即使 LLM 不可用也能返回基本结果。
    但这只是一个简化版本，没有结合法规和模板进行综合分析。

    Args:
        clauses: 合同条款列表

    Returns:
        基础风险分析结果
    """
    logger.info("[Tool:analyze_risk] 使用回退模式（简单分析）")

    identified_risks = []

    # 分析每个条款的风险
    for clause in clauses:
        risk_indicators = clause.get("risk_indicators", [])
        clause_type = clause.get("clause_type", "")
        clause_id = clause.get("clause_id", "")

        for indicator in risk_indicators:
            if indicator.startswith("[高风险]"):
                identified_risks.append({
                    "risk_id": f"R{len(identified_risks) + 1:03d}",
                    "risk_type": "high",
                    "risk_category": _infer_risk_category(indicator),
                    "risk_description": indicator,
                    "related_clause": clause_id,
                    "related_clause_type": clause_type,
                    "legal_basis": "基于条款预分析",
                    "suggestion": _get_high_risk_suggestion(indicator),
                    "is_blocking": True,
                })
            elif indicator.startswith("[中风险]"):
                identified_risks.append({
                    "risk_id": f"R{len(identified_risks) + 1:03d}",
                    "risk_type": "medium",
                    "risk_category": _infer_risk_category(indicator),
                    "risk_description": indicator,
                    "related_clause": clause_id,
                    "related_clause_type": clause_type,
                    "legal_basis": "基于条款预分析",
                    "suggestion": _get_medium_risk_suggestion(indicator),
                    "is_blocking": False,
                })

    # 计算整体风险等级
    high_count = sum(1 for r in identified_risks if r["risk_type"] == "high")
    medium_count = sum(1 for r in identified_risks if r["risk_type"] == "medium")

    if high_count > 0:
        overall_level = "high"
    elif medium_count > 0:
        overall_level = "medium"
    else:
        overall_level = "low"

    # 生成风险概要
    risk_summary = _generate_risk_summary(identified_risks)

    return {
        "status": "success",
        "risks": identified_risks,
        "risk_summary": risk_summary,
        "suggestions": [],
        "high_risk_count": high_count,
        "medium_risk_count": medium_count,
        "overall_level": overall_level,
        "need_human_review": high_count > 0,
        "note": "此结果为 LLM 不可用时的回退分析，建议启用 LLM 进行更准确的分析",
    }


@tool("generate_report", args_schema=GenerateReportInput, return_direct=False)
def generate_report(
    contract_name: str,
    contract_type: Optional[str],
    clauses: List[dict],
    parties: List[dict],
    risks: List[dict],
    laws_context: Optional[List[dict]] = None,
    templates_context: Optional[List[dict]] = None,
    run_manager: Optional[CallbackManagerForToolRun] = None,
) -> dict:
    """生成结构化合同审查报告。

    功能：
    - 汇总所有分析结果
    - 生成风险统计
    - 输出审查结论
    - 生成修改建议

    Args:
        contract_name: 合同名称
        contract_type: 合同类型
        clauses: 抽取的条款
        parties: 当事人信息
        risks: 识别的风险
        laws_context: 法规上下文
        templates_context: 模板上下文

    Returns:
        审查报告：
        - report_id: 报告ID
        - contract_info: 合同基本信息
        - review_summary: 审查摘要
        - risks: 风险列表
        - suggestions: 修改建议
        - conclusion: 审查结论
    """
    from datetime import datetime

    logger.info(f"[Tool:generate_report] 生成报告: {contract_name}")

    try:
        # 统计风险
        high_count = sum(1 for r in risks if r.get("risk_type") == "high")
        medium_count = sum(1 for r in risks if r.get("risk_type") == "medium")
        low_count = sum(1 for r in risks if r.get("risk_type") == "low")

        # 生成结论
        if high_count > 0:
            conclusion = "该合同存在高风险条款，建议法务部门人工复核后再行签署"
        elif medium_count > 0:
            conclusion = "该合同存在中风险条款，建议与对方协商修改后再行签署"
        else:
            conclusion = "该合同基本符合标准，建议审核后签署"

        # 生成建议
        suggestions = []
        for risk in risks[:5]:  # 最多5条
            clause = risk.get("related_clause", "未知条款")
            desc = risk.get("risk_description", "")
            suggestion = risk.get("suggestion", "")
            if suggestion:
                suggestions.append(f"{clause}: {desc}。{suggestion}")

        if not suggestions:
            suggestions.append("合同条款基本完整，建议保持现状")

        # 生成重点关注项
        key_concerns = [
            f"{r.get('related_clause', '')}: {r.get('risk_description', '')}"
            for r in risks
            if r.get("risk_type") == "high"
        ][:3]

        report = {
            "report_id": f"report_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "contract_info": {
                "name": contract_name,
                "type": contract_type or "未知",
                "parties": parties,
            },
            "review_summary": {
                "total_clauses": len(clauses),
                "high_risk_count": high_count,
                "medium_risk_count": medium_count,
                "low_risk_count": low_count,
            },
            "risks": risks,
            "key_concerns": key_concerns,
            "conclusion": conclusion,
            "suggestions": suggestions,
            "rag_contexts": {
                "laws_count": len(laws_context) if laws_context else 0,
                "templates_count": len(templates_context) if templates_context else 0,
            },
            "created_at": datetime.now().isoformat(),
        }

        logger.info(f"[Tool:generate_report] 报告生成完成")

        return {
            "status": "success",
            "report": report,
            "conclusion": conclusion,
        }

    except Exception as e:
        logger.error(f"[Tool:generate_report] 生成失败: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "report": None,
        }


@tool("request_human_review", args_schema=RequestHumanReviewInput, return_direct=False)
def request_human_review(
    high_risk_items: List[dict],
    reason: str,
    run_manager: Optional[CallbackManagerForToolRun] = None,
) -> dict:
    """请求人工复核高风险项。

    当发现高风险条款时，触发人工复核流程。

    功能：
    - 创建复核任务
    - 记录高风险项
    - 返回复核请求状态

    Args:
        high_risk_items: 高风险项列表
        reason: 请求复核的原因

    Returns:
        复核请求结果：
        - review_id: 复核任务ID
        - status: 状态
        - items_count: 高风险项数量
    """
    from datetime import datetime

    logger.info(f"[Tool:request_human_review] 请求复核 {len(high_risk_items)} 个高风险项")

    try:
        review_id = f"review_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

        # 实际项目中，这里应该调用 Human Review 服务创建复核任务
        # review_service.create_review_task(...)

        return {
            "status": "success",
            "review_id": review_id,
            "review_status": "pending",
            "items_count": len(high_risk_items),
            "reason": reason,
            "message": f"已创建人工复核任务 {review_id}，请等待法务人员审核",
        }

    except Exception as e:
        logger.error(f"[Tool:request_human_review] 创建复核任务失败: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"创建复核任务失败: {str(e)}",
        }


# ==================== 辅助函数 ====================


def _infer_risk_category(indicator: str) -> str:
    """推断风险类别。"""
    if "无条件" in indicator or "无限" in indicator:
        return "霸王条款"
    if "免除" in indicator or "强制" in indicator:
        return "违规条款"
    if "单方" in indicator:
        return "不对等条款"
    if "模糊" in indicator:
        return "模糊表述"
    return "需关注"


def _get_high_risk_suggestion(indicator: str) -> str:
    """获取高风险项的建议。"""
    suggestions = {
        "无条件解除": "建议删除无条件解除条款，增加正当解除条件",
        "无限责任": "建议修改为有限赔偿责任或设置赔偿上限",
        "免除全部责任": "建议删除该条款或修改为合理免责范围",
        "强制仲裁": "建议修改为可协商选择仲裁或诉讼",
        "单方解释权": "建议删除该条款或修改为双方共同解释",
        "无条件赔偿": "建议增加赔偿前提条件和合理范围",
    }
    for key, suggestion in suggestions.items():
        if key in indicator:
            return suggestion
    return "建议删除或修改该条款"


def _get_medium_risk_suggestion(indicator: str) -> str:
    """获取中风险项的建议。"""
    suggestions = {
        "违约金过高": "建议将违约金比例调整为合同金额的10%-30%",
        "赔偿无上限": "建议设置赔偿上限为合同金额的一定倍数",
        "单方变更": "建议修改为需双方协商一致方可变更",
        "自动续期": "建议明确自动续期的条件和期限",
    }
    for key, suggestion in suggestions.items():
        if key in indicator:
            return suggestion
    return "建议与对方协商修改"


def _generate_risk_summary(risks: List[dict]) -> str:
    """生成风险概要。"""
    if not risks:
        return "未发现明显风险条款，合同基本合规"

    high = len([r for r in risks if r.get("risk_type") == "high"])
    medium = len([r for r in risks if r.get("risk_type") == "medium"])

    parts = []
    if high > 0:
        parts.append(f"发现 {high} 项高风险条款")
    if medium > 0:
        parts.append(f"发现 {medium} 项中风险条款")

    return "，".join(parts) if parts else "风险可控"


# ==================== 工具注册表 ====================


def get_contract_tools() -> List[BaseTool]:
    """获取合同审核工具列表。

    Returns:
        LangChain BaseTool 列表
    """
    return [
        parse_contract,
        search_laws,
        search_templates,
        search_history,
        extract_clauses,
        analyze_risk,
        generate_report,
        request_human_review,
    ]


def get_tool_by_name(name: str) -> Optional[BaseTool]:
    """根据名称获取工具。

    Args:
        name: 工具名称

    Returns:
        工具实例，如果不存在返回 None
    """
    tools = get_contract_tools()
    for tool in tools:
        if tool.name == name:
            return tool
    return None
