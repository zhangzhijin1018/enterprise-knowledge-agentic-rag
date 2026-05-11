"""合同审核 RAG 服务。

专为合同审核 Agent 提供 RAG 检索能力：
1. 法规检索：检索相关法律法规
2. 模板检索：检索标准合同模板
3. 案例检索：检索历史审核案例

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 导入多路检索模块
try:
    from core.rag.multi_query import MultiQueryGenerator, get_multi_query_generator
    MULTI_QUERY_AVAILABLE = True
except ImportError:
    MULTI_QUERY_AVAILABLE = False
    logger.warning("MultiQueryGenerator 不可用，多路检索功能关闭")


class LawRetrievalResult(BaseModel):
    """法规检索结果。"""

    law_id: str = Field(description="法规 ID")
    title: str = Field(description="法规标题")
    chapter: str = Field(description="章节")
    article: str = Field(description="条款")
    relevance: float = Field(description="相关性分数")
    summary: str = Field(description="摘要")
    content: str = Field(description="完整内容")


class TemplateRetrievalResult(BaseModel):
    """模板检索结果。"""

    template_id: str = Field(description="模板 ID")
    name: str = Field(description="模板名称")
    version: str = Field(description="版本")
    relevance: float = Field(description="相关性分数")
    summary: str = Field(description="摘要")
    content: str = Field(description="完整内容")
    contract_type: str = Field(description="适用合同类型")


class HistoryRetrievalResult(BaseModel):
    """历史案例检索结果。"""

    case_id: str = Field(description="案例 ID")
    contract_name: str = Field(description="合同名称")
    risk_level: str = Field(description="风险等级")
    risk_points: list[str] = Field(description="风险点")
    handling_suggestion: str = Field(description="处理建议")
    outcome: str = Field(description="处理结果")
    relevance: float = Field(description="相关性分数")


class ContractRAGService:
    """合同审核 RAG 服务。

    职责：
    - 检索相关法规法条
    - 检索标准合同模板
    - 检索历史审核案例
    - 提供结构化检索结果

    设计原因：
    - 合同审核需要结合法规依据
    - 标准模板用于条款对比
    - 历史案例提供参考
    """

    def __init__(
        self,
        retrieval_chain: Any = None,
        laws_collection: str = "contract_laws",
        templates_collection: str = "contract_templates",
        history_collection: str = "contract_review_history",
    ) -> None:
        """初始化合同 RAG 服务。

        Args:
            retrieval_chain: 检索链路实例
            laws_collection: 法规集合名称
            templates_collection: 模板集合名称
            history_collection: 历史案例集合名称
        """
        self.retrieval_chain = retrieval_chain
        self.laws_collection = laws_collection
        self.templates_collection = templates_collection
        self.history_collection = history_collection

    def search_laws(
        self,
        query: str,
        contract_type: str | None = None,
        business_domain: str = "能源",
        top_k: int = 5,
    ) -> list[LawRetrievalResult]:
        """检索相关法规。

        Args:
            query: 检索 query
            contract_type: 合同类型
            business_domain: 业务域
            top_k: 返回数量

        Returns:
            法规检索结果列表
        """
        logger.info(
            f"[ContractRAG] 检索法规 | query={query[:30]}... | "
            f"contract_type={contract_type} | domain={business_domain}"
        )

        if self.retrieval_chain:
            return self._search_laws_with_rag(query, contract_type, business_domain, top_k)

        return self._search_laws_fallback(query, contract_type, business_domain, top_k)

    def search_laws_multi(
        self,
        query: str,
        contract_type: str | None = None,
        business_domain: str = "能源",
        top_k: int = 5,
        min_relevance: float = 0.4,  # 最低相关性阈值
        max_results: int = 10,        # 最大返回数量
        contract_content: str | None = None,
        extracted_clauses: list[dict] | None = None,
        legal_search_topics: list[str] | None = None,
    ) -> list[LawRetrievalResult]:
        """多路检索法规：从多个法律角度生成检索词并行检索后合并结果。

        多路检索策略：
        1. 原始 query 检索
        2. 合同类型 + 业务域角度检索
        3. 合同内容关键词角度检索
        4. 条款主题角度检索（如果有已抽取条款）
        5. LLM 提取的法律检索主题（最高优先级）

        返回策略：
        - 使用相关性阈值（min_relevance）替代固定数量
        - 同一法规从多路检索中命中可获得奖励分数
        - 最终返回相关性 >= min_relevance 的所有结果，最多不超过 max_results

        Args:
            query: 原始检索 query
            contract_type: 合同类型
            business_domain: 业务域
            top_k: 每路检索的召回数量（用于合并前的初筛）
            min_relevance: 最低相关性阈值（默认 0.4），低于此分数的结果会被过滤
            max_results: 最大返回数量（默认 10），超过此数量的结果会被截断
            contract_content: 合同全文内容（用于提取关键词）
            extracted_clauses: 已抽取的合同条款列表
            legal_search_topics: LLM 提取的法律检索主题（优先级最高）

        Returns:
            合并去重后的法规检索结果列表（已按相关性排序）
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        logger.info(
            f"[ContractRAG] 多路检索法规 | query={query[:30]}... | "
            f"contract_type={contract_type} | domain={business_domain} | "
            f"min_relevance={min_relevance} | max_results={max_results}"
        )

        # 生成多路检索词
        multi_queries = self._generate_multi_queries(
            query=query,
            contract_type=contract_type,
            business_domain=business_domain,
            contract_content=contract_content,
            extracted_clauses=extracted_clauses,
            legal_search_topics=legal_search_topics,
        )

        logger.info(f"[ContractRAG] 生成 {len(multi_queries)} 路检索词: {[q['query'][:20] for q in multi_queries]}")

        if not self.retrieval_chain:
            # 无 RAG 链时使用回退方案
            return self._search_laws_fallback(query, contract_type, business_domain, top_k)

        # 并行执行多路检索
        def search_single(args: tuple) -> list[LawRetrievalResult]:
            """执行单路检索（在线程池中执行）"""
            q_data, top_k_per = args
            return self._search_laws_with_rag(
                query=q_data["query"],
                contract_type=q_data.get("contract_type"),
                business_domain=q_data.get("business_domain", "能源"),
                top_k=top_k_per,
            )

        # 每路检索返回稍多结果，便于合并去重
        # 使用更大的初筛数量，确保不漏掉相关结果
        top_k_per = max(top_k * 4, 20)

        try:
            # 使用线程池并行执行多路检索
            with ThreadPoolExecutor(max_workers=min(len(multi_queries), 5)) as executor:
                futures = [
                    executor.submit(search_single, (q, top_k_per))
                    for q in multi_queries
                ]
                results_list = [f.result() for f in futures]
        except Exception as e:
            logger.warning(f"[ContractRAG] 多路检索并行执行失败: {e}，降级为单路检索")
            return self._search_laws_with_rag(query, contract_type, business_domain, top_k)

        # 合并多路结果（使用相关性阈值过滤）
        merged_results = self._merge_multi_results(
            results_list,
            top_k=top_k,
            min_relevance=min_relevance,
            max_results=max_results,
        )

        logger.info(f"[ContractRAG] 多路检索完成，返回 {len(merged_results)} 条")
        return merged_results

    def _generate_multi_queries(
        self,
        query: str,
        contract_type: str | None,
        business_domain: str,
        contract_content: str | None,
        extracted_clauses: list[dict] | None = None,
        legal_search_topics: list[str] | None = None,
    ) -> list[dict]:
        """生成多路检索词。

        根据合同类型、业务域、内容和 LLM 提取的检索主题，从不同法律角度生成检索词。

        多路检索角度：
        1. 原始 query（保留用户意图）
        2. 合同类型 + 业务域 + 通用法律检索
        3. 合同内容提取关键词
        4. 已抽取条款的主题
        5. LLM 提取的法律检索主题（优先级最高）
        6. 业务域特定法规

        Args:
            query: 原始查询
            contract_type: 合同类型
            business_domain: 业务域
            contract_content: 合同内容
            extracted_clauses: 已抽取条款（字典列表格式）
            legal_search_topics: LLM 提取的法律检索主题（字符串列表，优先级最高）

        Returns:
            多路检索词列表，每项包含 query、角度描述等
        """
        queries = []

        # 角度1：原始 query（保留用户意图）
        queries.append({
            "query": query,
            "angle": "original",
            "description": "用户原始查询",
        })

        # 角度5：LLM 提取的法律检索主题（最高优先级）
        # 这些是由 extract_clauses 中 LLM 从合同内容提取的最相关检索词
        if legal_search_topics:
            for topic in legal_search_topics[:3]:  # 最多使用 3 个主题
                queries.append({
                    "query": topic,
                    "angle": "llm_topics",
                    "description": f"LLM提取: {topic[:20]}",
                })
            logger.info(f"[ContractRAG] 使用 LLM 提取的 {len(legal_search_topics[:3])} 个检索主题")

        # 角度2：合同类型 + 业务域 + 通用法律检索
        if contract_type:
            type_queries = [
                f"{contract_type} 合同 法律规定 效力",
                f"{contract_type} 违约责任 赔偿",
                f"{contract_type} 解除合同 条件",
            ]
            for q in type_queries[:1]:  # 限制数量
                queries.append({
                    "query": q,
                    "angle": "contract_type",
                    "description": f"{contract_type}类型合同",
                })

        # 角度3：从合同内容提取关键词检索
        if contract_content:
            keywords = self._extract_legal_keywords(contract_content)
            if keywords:
                # 取前 3 个关键词组合检索
                keyword_query = " ".join(keywords[:3])
                queries.append({
                    "query": f"{keyword_query} 法律 规定",
                    "angle": "keywords",
                    "description": f"合同关键词: {keywords[:2]}",
                })

        # 角度4：从已抽取条款中提取主题检索
        if extracted_clauses:
            clause_themes = self._extract_clause_themes(extracted_clauses)
            for theme in clause_themes[:2]:  # 限制数量
                queries.append({
                    "query": f"{theme} 法律规定 合同条款",
                    "angle": "clause_theme",
                    "description": f"条款主题: {theme}",
                })

        # 角度6：业务域特定法规
        domain_laws = {
            "能源": ["能源行业 安全生产 法律规定", "电力法 合同 效力"],
            "电力": ["电力行业 合同 监管规定", "电网 设备 采购 法规"],
            "新能源": ["新能源 项目 开发 合同 法规"],
            "建筑": ["建设工程 合同 司法解释"],
        }
        if business_domain in domain_laws:
            for q in domain_laws[business_domain][:1]:
                queries.append({
                    "query": q,
                    "angle": "business_domain",
                    "description": f"{business_domain}行业法规",
                })

        # 去重（基于 query 文本）
        seen = set()
        unique_queries = []
        for q_data in queries:
            q_text = q_data["query"]
            if q_text not in seen:
                seen.add(q_text)
                unique_queries.append(q_data)

        # 限制最大路数
        return unique_queries[:5]

    def _extract_legal_keywords(self, text: str) -> list[str]:
        """从合同文本中提取法律相关关键词。

        基于规则提取常见的法律术语。

        Args:
            text: 合同文本

        Returns:
            法律关键词列表
        """
        import re

        # 常见法律术语词库
        legal_terms = [
            "违约金", "赔偿", "损失", "违约责任", "解除合同", "终止",
            "不可抗力", "免责", "保密", "保密义务", "竞业禁止", "限制竞争",
            "知识产权", "专利", "商标", "著作权", "技术成果",
            "验收", "质量标准", "质量保证", "售后服务",
            "付款", "支付", "结算", "发票", "税费",
            "争议解决", "仲裁", "诉讼", "管辖", "适用法律",
            "转让", "分包", "转包", "变更", "补充协议",
            "安全责任", "安全生产", "保险", "事故",
            "陈述保证", "承诺", "保证", "担保",
        ]

        found_keywords = []
        text_lower = text

        for term in legal_terms:
            # 使用词边界匹配
            pattern = rf"{re.escape(term)}"
            if re.search(pattern, text_lower):
                found_keywords.append(term)

        return found_keywords[:8]  # 限制数量

    def _extract_clause_themes(self, clauses: list[dict]) -> list[str]:
        """从已抽取的合同条款中提取主题。

        Args:
            clauses: 合同条款列表

        Returns:
            条款主题列表
        """
        themes = []

        for clause in clauses[:10]:  # 最多处理 10 个条款
            # 尝试从条款中提取主题词
            clause_type = clause.get("type", "")
            clause_content = clause.get("content", clause.get("text", ""))

            if clause_type:
                themes.append(clause_type)

            # 从内容中提取关键词
            if clause_content:
                # 提取前 50 个字符作为主题标识
                theme = clause_content[:30].strip()
                if theme and len(theme) > 5:
                    themes.append(theme)

        # 去重并返回
        return list(dict.fromkeys(themes))[:5]

    def _merge_multi_results(
        self,
        results_list: list[list[LawRetrievalResult]],
        top_k: int,
        min_relevance: float = 0.4,
        max_results: int = 10,
    ) -> list[LawRetrievalResult]:
        """合并多路检索结果并去重。

        使用加权分数合并，同一法规从多路检索中获得更高的综合分数。
        使用相关性阈值过滤，返回相关性 >= min_relevance 的结果。

        Args:
            results_list: 多路检索结果列表
            top_k: 返回数量上限（保留参数，向下兼容）
            min_relevance: 最低相关性阈值，低于此分数的结果会被过滤
            max_results: 最大返回数量，超过此数量的结果会被截断

        Returns:
            合并去重后的结果（已按相关性排序）
        """
        # 法规 ID → 合并信息
        law_map: dict[str, dict] = {}

        for results in results_list:
            for law in results:
                law_id = law.law_id
                if law_id not in law_map:
                    law_map[law_id] = {
                        "law": law,
                        "max_score": law.relevance,
                        "count": 1,
                        "angles": set(),
                    }
                else:
                    # 更新最高分
                    if law.relevance > law_map[law_id]["max_score"]:
                        law_map[law_id]["max_score"] = law.relevance
                    law_map[law_id]["count"] += 1

        # 计算综合分数：基础分 + 重复命中奖励
        merged = []
        for law_id, data in law_map.items():
            base_score = data["max_score"]
            # 命中多路检索的奖励分数（最多 +0.1）
            bonus = min(data["count"] * 0.02, 0.1)
            final_score = min(base_score + bonus, 1.0)

            # 创建合并后的结果
            merged_law = data["law"].model_copy()
            merged_law.relevance = round(final_score, 4)
            merged_law.summary = f"[多路命中 {data['count']} 次] {data['law'].summary}"
            merged.append(merged_law)

        # 按综合分数排序
        merged.sort(key=lambda x: x.relevance, reverse=True)

        # 过滤低相关性结果
        filtered = [r for r in merged if r.relevance >= min_relevance]

        logger.info(
            f"[ContractRAG] 结果合并完成 | 原始={sum(len(r) for r in results_list)} | "
            f"去重后={len(merged)} | 过滤后(min>={min_relevance})={len(filtered)} | "
            f"最终返回={min(len(filtered), max_results)}"
        )

        # 返回：相关性 >= min_relevance，最多 max_results 条
        return filtered[:max_results]

    def _search_laws_with_rag(
        self,
        query: str,
        contract_type: str | None,
        business_domain: str,
        top_k: int,
    ) -> list[LawRetrievalResult]:
        """使用 RAG 检索法规。"""
        try:
            # 构建过滤条件
            filters = {
                "collection": self.laws_collection,
                "business_domain": business_domain,
            }
            if contract_type:
                filters["contract_type"] = contract_type

            # 执行检索
            result = self.retrieval_chain.retrieve(
                query_text=query,
                filters=filters,
                enable_rerank=True,
            )

            # 转换结果
            laws = []
            for chunk in result.get("chunks", [])[:top_k]:
                laws.append(LawRetrievalResult(
                    law_id=chunk.get("law_id", chunk.get("chunk_uuid", "")),
                    title=chunk.get("title", "未知法规"),
                    chapter=chunk.get("chapter", ""),
                    article=chunk.get("content", ""),
                    relevance=chunk.get("rerank_score", chunk.get("score", 0.5)),
                    summary=chunk.get("summary", chunk.get("content", "")[:200]),
                    content=chunk.get("content", ""),
                ))

            logger.info(f"[ContractRAG] 法规检索完成，返回 {len(laws)} 条")
            return laws

        except Exception as e:
            logger.warning(f"[ContractRAG] RAG 检索法规失败: {e}，使用回退方案")
            return self._search_laws_fallback(query, contract_type, business_domain, top_k)

    def _search_laws_fallback(
        self,
        query: str,
        contract_type: str | None,
        business_domain: str,
        top_k: int,
    ) -> list[LawRetrievalResult]:
        """回退方案：返回预设的法规库。

        实际项目中应该从数据库或知识库加载。
        """
        # 通用法规
        base_laws = [
            LawRetrievalResult(
                law_id="law_civil_code",
                title="中华人民共和国民法典",
                chapter="第三编 合同编",
                article="",
                relevance=0.95,
                summary="规定了合同的订立、效力、履行、变更、转让、终止等基本规则",
                content="《民法典》规定：合同是民事主体之间设立、变更、终止民事法律关系的协议。依法成立的合同，受法律保护。",
            ),
            LawRetrievalResult(
                law_id="law_contract_law",
                title="中华人民共和国合同法",
                chapter="总则",
                article="",
                relevance=0.90,
                summary="合同法的基本原则和一般规定",
                content="当事人依法享有自愿订立合同的权利，任何单位和个人不得非法干预。",
            ),
        ]

        # 采购相关法规
        procurement_laws = [
            LawRetrievalResult(
                law_id="law_tender",
                title="中华人民共和国招标投标法",
                chapter="相关规定",
                article="",
                relevance=0.85,
                summary="规定了招标投标活动的原则、程序和要求",
                content="招标投标活动应当遵循公开、公平、公正和诚实信用的原则。",
            ),
        ]

        # 能源行业法规
        energy_laws = [
            LawRetrievalResult(
                law_id="law_energy",
                title="中华人民共和国电力法",
                chapter="电力设施保护",
                article="",
                relevance=0.80,
                summary="规范电力设施建设和电力供应活动",
                content="电力设施受国家保护，禁止任何单位和个人危害电力设施安全或者非法侵占、使用电能。",
            ),
            LawRetrievalResult(
                law_id="law_state_asset",
                title="企业国有资产交易监督管理办法",
                chapter="产权转让",
                article="",
                relevance=0.75,
                summary="规范企业国有资产交易行为",
                content="国有资产交易应当遵循等价有偿和公开、公平、公正的原则。",
            ),
        ]

        # 根据业务域选择法规
        all_laws = base_laws.copy()

        if business_domain in ["能源", "电力", "新能源", "发电", "电网"]:
            all_laws.extend(energy_laws)

        if contract_type in ["采购合同", "建设工程合同"]:
            all_laws.extend(procurement_laws)

        # 去重并返回
        seen_ids = set()
        unique_laws = []
        for law in all_laws:
            if law.law_id not in seen_ids:
                seen_ids.add(law.law_id)
                unique_laws.append(law)

        return unique_laws[:top_k]

    def search_templates(
        self,
        contract_type: str | None = None,
        business_domain: str = "能源",
        top_k: int = 3,
    ) -> list[TemplateRetrievalResult]:
        """检索标准合同模板。

        Args:
            contract_type: 合同类型
            business_domain: 业务域
            top_k: 返回数量

        Returns:
            模板检索结果列表
        """
        logger.info(
            f"[ContractRAG] 检索模板 | contract_type={contract_type} | domain={business_domain}"
        )

        if self.retrieval_chain:
            return self._search_templates_with_rag(contract_type, business_domain, top_k)

        return self._search_templates_fallback(contract_type, business_domain, top_k)

    def _search_templates_with_rag(
        self,
        contract_type: str | None,
        business_domain: str,
        top_k: int,
    ) -> list[TemplateRetrievalResult]:
        """使用 RAG 检索模板。"""
        try:
            filters = {
                "collection": self.templates_collection,
                "business_domain": business_domain,
            }
            if contract_type:
                filters["contract_type"] = contract_type

            result = self.retrieval_chain.retrieve(
                query_text=f"{contract_type or ''} {business_domain} 合同模板",
                filters=filters,
                enable_rerank=True,
            )

            templates = []
            for chunk in result.get("chunks", [])[:top_k]:
                templates.append(TemplateRetrievalResult(
                    template_id=chunk.get("template_id", chunk.get("chunk_uuid", "")),
                    name=chunk.get("name", "标准模板"),
                    version=chunk.get("version", "v1.0"),
                    relevance=chunk.get("rerank_score", chunk.get("score", 0.5)),
                    summary=chunk.get("summary", ""),
                    content=chunk.get("content", ""),
                    contract_type=chunk.get("contract_type", contract_type or "通用"),
                ))

            return templates

        except Exception as e:
            logger.warning(f"[ContractRAG] RAG 检索模板失败: {e}，使用回退方案")
            return self._search_templates_fallback(contract_type, business_domain, top_k)

    def _search_templates_fallback(
        self,
        contract_type: str | None,
        business_domain: str,
        top_k: int,
    ) -> list[TemplateRetrievalResult]:
        """回退方案：返回预设的模板库。"""
        templates = [
            TemplateRetrievalResult(
                template_id="tpl_general",
                name="一般合同标准模板",
                version="v2.1",
                relevance=0.90,
                summary="集团通用合同模板，包含所有必要条款",
                content="""【合同正文】

第一条 当事人信息
甲方：[甲方名称]
乙方：[乙方名称]

第二条 合同标的
[标的描述]

第三条 合同价款
合同总金额为人民币[金额]元。

第四条 付款方式
[付款方式描述]

第五条 履行期限
自[开始日期]至[结束日期]。

第六条 质量标准
[质量标准描述]

第七条 违约责任
任何一方违反本合同约定，应承担相应的违约责任。

第八条 争议解决
本合同在履行过程中发生的争议，双方应协商解决；协商不成的，提交[仲裁/诉讼]。""",
                contract_type="通用",
            ),
        ]

        if contract_type:
            templates.append(
                TemplateRetrievalResult(
                    template_id=f"tpl_{contract_type}",
                    name=f"{contract_type}标准模板",
                    version="v1.5",
                    relevance=0.85,
                    summary=f"{contract_type}专用条款参考",
                    content=f"""【{contract_type}专用条款】

[根据{contract_type}特点定制的条款内容]

[具体条款内容...]""",
                    contract_type=contract_type,
                )
            )

        if business_domain in ["能源", "电力", "新能源"]:
            templates.append(
                TemplateRetrievalResult(
                    template_id="tpl_energy",
                    name="能源行业专用模板",
                    version="v1.0",
                    relevance=0.80,
                    summary="能源行业专用合同条款",
                    content="""【能源行业专用条款】

安全责任条款
[安全生产相关要求]

环保合规条款
[环境保护相关要求]

能源计量条款
[能源计量和结算相关要求]""",
                    contract_type="行业专用",
                )
            )

        return templates[:top_k]

    def search_history(
        self,
        query: str,
        contract_type: str | None = None,
        risk_level: str | None = None,
        top_k: int = 5,
    ) -> list[HistoryRetrievalResult]:
        """检索历史审核案例。

        Args:
            query: 检索 query
            contract_type: 合同类型
            risk_level: 风险等级
            top_k: 返回数量

        Returns:
            历史案例检索结果列表
        """
        logger.info(
            f"[ContractRAG] 检索历史案例 | query={query[:30]}... | "
            f"contract_type={contract_type} | risk_level={risk_level}"
        )

        if self.retrieval_chain:
            return self._search_history_with_rag(query, contract_type, risk_level, top_k)

        return self._search_history_fallback(query, contract_type, risk_level, top_k)

    def _search_history_with_rag(
        self,
        query: str,
        contract_type: str | None,
        risk_level: str | None,
        top_k: int,
    ) -> list[HistoryRetrievalResult]:
        """使用 RAG 检索历史案例。"""
        try:
            filters = {
                "collection": self.history_collection,
            }
            if contract_type:
                filters["contract_type"] = contract_type
            if risk_level:
                filters["risk_level"] = risk_level

            result = self.retrieval_chain.retrieve(
                query_text=query,
                filters=filters,
                enable_rerank=True,
            )

            cases = []
            for chunk in result.get("chunks", [])[:top_k]:
                cases.append(HistoryRetrievalResult(
                    case_id=chunk.get("case_id", chunk.get("chunk_uuid", "")),
                    contract_name=chunk.get("contract_name", "未知合同"),
                    risk_level=chunk.get("risk_level", "unknown"),
                    risk_points=chunk.get("risk_points", []),
                    handling_suggestion=chunk.get("handling_suggestion", ""),
                    outcome=chunk.get("outcome", ""),
                    relevance=chunk.get("rerank_score", chunk.get("score", 0.5)),
                ))

            return cases

        except Exception as e:
            logger.warning(f"[ContractRAG] RAG 检索历史失败: {e}，使用回退方案")
            return self._search_history_fallback(query, contract_type, risk_level, top_k)

    def _search_history_fallback(
        self,
        query: str,
        contract_type: str | None,
        risk_level: str | None,
        top_k: int,
    ) -> list[HistoryRetrievalResult]:
        """回退方案：返回预设的历史案例。"""
        # 模拟历史案例
        history_cases = [
            HistoryRetrievalResult(
                case_id="case_2024_001",
                contract_name="XX采购合同",
                risk_level="high",
                risk_points=[
                    "无限连带责任条款",
                    "单方解除权条款",
                ],
                handling_suggestion="经法务审核，要求删除无限连带责任条款，修改为按比例承担",
                outcome="修改后通过",
                relevance=0.85,
            ),
            HistoryRetrievalResult(
                case_id="case_2024_002",
                contract_name="YY服务合同",
                risk_level="medium",
                risk_points=[
                    "违约金比例偏高",
                    "保密范围过宽",
                ],
                handling_suggestion="协商将违约金调整为合同金额的10%，明确保密义务的边界",
                outcome="协商后通过",
                relevance=0.75,
            ),
            HistoryRetrievalResult(
                case_id="case_2024_003",
                contract_name="ZZ建设合同",
                risk_level="high",
                risk_points=[
                    "工程款支付条件不明确",
                    "验收标准缺失",
                ],
                handling_suggestion="补充工程款支付节点和验收标准条款",
                outcome="补充条款后通过",
                relevance=0.70,
            ),
        ]

        return history_cases[:top_k]

    def search_all(
        self,
        query: str,
        contract_type: str | None = None,
        business_domain: str = "能源",
    ) -> dict[str, Any]:
        """综合检索：法规 + 模板 + 历史案例。

        Args:
            query: 检索 query
            contract_type: 合同类型
            business_domain: 业务域

        Returns:
            {
                "laws": [...],
                "templates": [...],
                "history": [...],
            }
        """
        logger.info(f"[ContractRAG] 综合检索 | query={query[:30]}...")

        laws = self.search_laws(
            query=query,
            contract_type=contract_type,
            business_domain=business_domain,
            top_k=5,
        )

        templates = self.search_templates(
            contract_type=contract_type,
            business_domain=business_domain,
            top_k=3,
        )

        history = self.search_history(
            query=query,
            contract_type=contract_type,
            top_k=5,
        )

        return {
            "laws": [law.model_dump() for law in laws],
            "templates": [tpl.model_dump() for tpl in templates],
            "history": [case.model_dump() for case in history],
        }


# ==================== 全局实例 ====================

_contract_rag_service: ContractRAGService | None = None


def get_contract_rag_service() -> ContractRAGService:
    """获取合同 RAG 服务全局实例。"""
    global _contract_rag_service

    if _contract_rag_service is None:
        _contract_rag_service = ContractRAGService()

    return _contract_rag_service


def init_contract_rag_service(retrieval_chain: Any) -> ContractRAGService:
    """初始化合同 RAG 服务。"""
    global _contract_rag_service

    _contract_rag_service = ContractRAGService(retrieval_chain=retrieval_chain)

    logger.info("[ContractRAG] 服务初始化完成")

    return _contract_rag_service
