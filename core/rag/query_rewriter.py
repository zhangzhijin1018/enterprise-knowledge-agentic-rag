"""多路查询策略模块。

支持多种查询重写和检索策略：
1. 直接检索（Direct）：原始查询直接检索
2. HyDE 检索：使用假设答案增强检索
3. 子查询检索：将复杂查询拆分为多个子查询
4. 回溯问题检索：将复杂查询简化为更基础的查询

参考实现：
- integrated_qa_system/rag_qa/core/strategy_selector.py
- integrated_qa_system/rag_qa/core/new_rag_system.py
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.llm.base import BaseLLMGateway

logger = logging.getLogger(__name__)


class RetrievalStrategy(str, Enum):
    """检索策略枚举。

    Attributes:
        DIRECT: 直接检索，原始查询直接检索
        HYDE: HyDE 检索，使用假设答案增强检索
        SUBQUERY: 子查询检索，将复杂查询拆分为多个子查询
        BACKTRACKING: 回溯问题检索，将复杂查询简化为更基础的查询
    """

    DIRECT = "direct"
    HYDE = "hyde"
    SUBQUERY = "subquery"
    BACKTRACKING = "backtracking"

    @classmethod
    def from_string(cls, value: str) -> "RetrievalStrategy":
        """从字符串转换为枚举值。

        Args:
            value: 策略名称

        Returns:
            对应的检索策略枚举值
        """
        value = value.strip().lower()
        mapping = {
            "直接检索": cls.DIRECT,
            "direct": cls.DIRECT,
            "假设问题检索": cls.HYDE,
            "hyde": cls.HYDE,
            "子查询检索": cls.SUBQUERY,
            "subquery": cls.SUBQUERY,
            "回溯问题检索": cls.BACKTRACKING,
            "backtracking": cls.BACKTRACKING,
        }
        return mapping.get(value, cls.DIRECT)


class StrategySelector:
    """检索策略选择器。

    职责：
    - 分析用户查询特征
    - 选择最适合的检索策略
    - 支持 LLM 驱动和规则驱动两种模式

    策略选择规则：
    - 意图明确、查询具体 → 直接检索
    - 查询抽象、语义模糊 → HyDE 检索
    - 查询复杂、涉及多主题 → 子查询检索
    - 查询复杂但方向不清 → 回溯问题检索

    参考 integrated_qa_system/strategy_selector.py
    """

    # 策略选择提示词模板
    STRATEGY_PROMPT = """你是一个智能助手，负责分析用户查询并选择最适合的检索增强策略。

分析用户查询：{query}

以下是几种检索增强策略及其适用场景：

1. **直接检索（direct）**：
   - 描述：对用户查询直接进行检索，不进行任何增强处理
   - 适用：查询意图明确，需要检索特定信息的问题
   - 示例："AI学科学费是多少？"、"安全生产责任制是什么？"

2. **假设问题检索（hyde）**：
   - 描述：使用 LLM 生成一个假设答案，然后基于假设答案进行检索
   - 适用：查询较为抽象，直接检索效果不佳的问题
   - 示例："人工智能在能源领域的应用有哪些？"、"设备故障如何排查？"

3. **子查询检索（subquery）**：
   - 描述：将复杂查询拆分为多个简单子查询，分别检索并合并结果
   - 适用：查询涉及多个实体或方面，需要分别检索不同信息
   - 示例："比较光伏和风电的优缺点"、"合同审查和合规检查的区别"

4. **回溯问题检索（backtracking）**：
   - 描述：将复杂查询转化为更基础、更易于检索的问题
   - 适用：查询较为复杂，需要简化后才能有效检索
   - 示例："我有一个大型光伏项目，想知道如何进行验收" → "光伏项目验收标准"

根据用户查询，直接返回策略名称（direct/hyde/subquery/backtracking），不要输出任何分析过程。
"""

    def __init__(
        self,
        llm_gateway: BaseLLMGateway | None = None,
        use_llm: bool = True,
    ) -> None:
        """初始化策略选择器。

        Args:
            llm_gateway: LLM 网关（用于 LLM 驱动的策略选择）
            use_llm: 是否使用 LLM 驱动策略选择，False 则使用规则驱动
        """
        self.llm_gateway = llm_gateway
        self.use_llm = use_llm and llm_gateway is not None

    def select_strategy(self, query: str) -> RetrievalStrategy:
        """选择最适合的检索策略。

        Args:
            query: 用户查询

        Returns:
            选择的检索策略
        """
        if self.use_llm:
            return self._select_by_llm(query)
        else:
            return self._select_by_rules(query)

    def _select_by_llm(self, query: str) -> RetrievalStrategy:
        """使用 LLM 选择策略。

        Args:
            query: 用户查询

        Returns:
            选择的检索策略
        """
        if not self.llm_gateway:
            return RetrievalStrategy.DIRECT

        try:
            prompt = self.STRATEGY_PROMPT.format(query=query)
            response = self.llm_gateway.generate(
                prompt=prompt,
                temperature=0.1,
                max_tokens=50,
            )

            # 解析策略名称
            strategy_name = response.strip().lower()
            strategy = RetrievalStrategy.from_string(strategy_name)

            logger.info(f"[StrategySelector] LLM 选择策略: {strategy.value} (query: {query[:30]}...)")
            return strategy

        except Exception as e:
            logger.warning(f"[StrategySelector] LLM 策略选择失败: {e}，使用规则选择")
            return self._select_by_rules(query)

    def _select_by_rules(self, query: str) -> RetrievalStrategy:
        """基于规则选择策略。

        根据查询特征自动选择策略。

        Args:
            query: 用户查询

        Returns:
            选择的检索策略
        """
        import re

        # 检测查询复杂度
        has_comparison = bool(re.search(r"比较|对比|区别|差异|哪个好", query))
        has_multi_topic = query.count("和") >= 2 or query.count("、") >= 2
        has_abstract_terms = bool(re.search(r"有哪些|如何|怎么|什么|为什么|哪些方面", query))
        has_specific = bool(re.search(r"第[一二三四五六七八九十百\d]+条|《[^》]+》|\d{4}[-/年]", query))

        # 策略选择规则
        if has_specific:
            # 精确查询：制度条款、编号等 → 直接检索
            strategy = RetrievalStrategy.DIRECT
        elif has_comparison or has_multi_topic:
            # 多主题/对比查询 → 子查询检索
            strategy = RetrievalStrategy.SUBQUERY
        elif has_abstract_terms:
            # 抽象查询 → HyDE 检索
            strategy = RetrievalStrategy.HYDE
        else:
            # 默认直接检索
            strategy = RetrievalStrategy.DIRECT

        logger.info(f"[StrategySelector] 规则选择策略: {strategy.value} (query: {query[:30]}...)")
        return strategy


class QueryRewriter:
    """查询重写器。

    职责：
    - 根据策略对查询进行重写
    - 支持 HyDE、子查询、回溯问题等多种重写方式

    参考 integrated_qa_system/new_rag_system.py
    """

    # HyDE 提示词：生成假设答案
    HYDE_PROMPT = """你是一个专业的知识库助手。请根据用户问题生成一个假设的标准答案。

这个假设答案将用于从知识库中检索相关文档。请确保：
1. 答案准确、专业
2. 包含可能被检索到的关键词
3. 答案长度适中（100-300字）

用户问题：{query}

假设的标准答案："""

    # 子查询提示词：拆分复杂查询
    SUBQUERY_PROMPT = """你是一个专业的查询分解助手。请将复杂查询拆分为多个简单、独立的子查询。

拆分要求：
1. 每个子查询应独立完整，可以单独检索
2. 子查询数量通常为 2-4 个
3. 使用换行符分隔每个子查询
4. 保持原查询的核心意图

用户问题：{query}

拆分后的子查询（每行一个）："""

    # 回溯问题提示词：简化复杂查询
    BACKTRACKING_PROMPT = """你是一个专业的查询优化助手。请将复杂的用户查询简化为更基础、更易于检索的问题。

简化要求：
1. 保留核心概念和关键词
2. 去除口语化、冗余的描述
3. 将模糊查询具体化
4. 简化后的问题应该能够直接检索到相关文档

用户问题：{query}

简化后的基础查询："""

    def __init__(
        self,
        llm_gateway: BaseLLMGateway | None = None,
    ) -> None:
        """初始化查询重写器。

        Args:
            llm_gateway: LLM 网关（用于生成重写后的查询）
        """
        self.llm_gateway = llm_gateway

    def rewrite(
        self,
        query: str,
        strategy: RetrievalStrategy,
    ) -> dict[str, Any]:
        """根据策略重写查询。

        Args:
            query: 原始查询
            strategy: 检索策略

        Returns:
            重写结果，包含：
            - rewritten_queries: 重写后的查询列表
            - strategy: 使用的策略
            - original_query: 原始查询
        """
        if strategy == RetrievalStrategy.DIRECT:
            return self._rewrite_direct(query)
        elif strategy == RetrievalStrategy.HYDE:
            return self._rewrite_hyde(query)
        elif strategy == RetrievalStrategy.SUBQUERY:
            return self._rewrite_subquery(query)
        elif strategy == RetrievalStrategy.BACKTRACKING:
            return self._rewrite_backtracking(query)
        else:
            return self._rewrite_direct(query)

    def _rewrite_direct(self, query: str) -> dict[str, Any]:
        """直接检索策略。

        Args:
            query: 原始查询

        Returns:
            重写结果
        """
        return {
            "rewritten_queries": [query],
            "strategy": RetrievalStrategy.DIRECT.value,
            "original_query": query,
            "strategy_description": "直接检索，原始查询不做修改",
        }

    def _rewrite_hyde(self, query: str) -> dict[str, Any]:
        """HyDE 检索策略。

        生成假设答案，用于增强检索。

        Args:
            query: 原始查询

        Returns:
            重写结果，包含原始查询和假设答案
        """
        if not self.llm_gateway:
            logger.warning("[QueryRewriter] 未配置 LLM，回退到直接检索")
            return self._rewrite_direct(query)

        try:
            prompt = self.HYDE_PROMPT.format(query=query)
            hypo_answer = self.llm_gateway.generate(
                prompt=prompt,
                temperature=0.7,
                max_tokens=500,
            )

            # 清理假设答案
            hypo_answer = hypo_answer.strip()

            logger.info(f"[QueryRewriter] HyDE 生成假设答案: {hypo_answer[:100]}...")

            return {
                "rewritten_queries": [query, hypo_answer],
                "strategy": RetrievalStrategy.HYDE.value,
                "original_query": query,
                "hyde_answer": hypo_answer,
                "strategy_description": "HyDE 检索，使用假设答案增强检索",
            }

        except Exception as e:
            logger.error(f"[QueryRewriter] HyDE 重写失败: {e}")
            return self._rewrite_direct(query)

    def _rewrite_subquery(self, query: str) -> dict[str, Any]:
        """子查询检索策略。

        将复杂查询拆分为多个简单子查询。

        Args:
            query: 原始查询

        Returns:
            重写结果，包含拆分后的子查询列表
        """
        if not self.llm_gateway:
            logger.warning("[QueryRewriter] 未配置 LLM，回退到直接检索")
            return self._rewrite_direct(query)

        try:
            prompt = self.SUBQUERY_PROMPT.format(query=query)
            response = self.llm_gateway.generate(
                prompt=prompt,
                temperature=0.3,
                max_tokens=500,
            )

            # 解析子查询列表
            lines = response.strip().split("\n")
            subqueries = []
            for line in lines:
                line = line.strip()
                # 过滤空行和编号
                if line and not line.startswith("#") and not line.startswith("-") and len(line) > 5:
                    # 移除可能的编号前缀
                    line = line.lstrip("0123456789.、、)")
                    line = line.strip()
                    if line:
                        subqueries.append(line)

            if not subqueries:
                logger.warning("[QueryRewriter] 未能生成有效子查询，回退到直接检索")
                return self._rewrite_direct(query)

            logger.info(f"[QueryRewriter] 拆分出 {len(subqueries)} 个子查询: {subqueries}")

            return {
                "rewritten_queries": subqueries,
                "strategy": RetrievalStrategy.SUBQUERY.value,
                "original_query": query,
                "strategy_description": f"子查询检索，拆分为 {len(subqueries)} 个子查询",
            }

        except Exception as e:
            logger.error(f"[QueryRewriter] 子查询拆分失败: {e}")
            return self._rewrite_direct(query)

    def _rewrite_backtracking(self, query: str) -> dict[str, Any]:
        """回溯问题检索策略。

        将复杂查询简化为更基础的问题。

        Args:
            query: 原始查询

        Returns:
            重写结果，包含简化后的查询
        """
        if not self.llm_gateway:
            logger.warning("[QueryRewriter] 未配置 LLM，回退到直接检索")
            return self._rewrite_direct(query)

        try:
            prompt = self.BACKTRACKING_PROMPT.format(query=query)
            simplified_query = self.llm_gateway.generate(
                prompt=prompt,
                temperature=0.3,
                max_tokens=200,
            )

            # 清理简化后的查询
            simplified_query = simplified_query.strip()

            logger.info(f"[QueryRewriter] 回溯简化: '{query}' → '{simplified_query}'")

            return {
                "rewritten_queries": [simplified_query],
                "strategy": RetrievalStrategy.BACKTRACKING.value,
                "original_query": query,
                "simplified_query": simplified_query,
                "strategy_description": "回溯问题检索，将复杂查询简化为基础查询",
            }

        except Exception as e:
            logger.error(f"[QueryRewriter] 回溯问题重写失败: {e}")
            return self._rewrite_direct(query)


class MultiQueryRetrieval:
    """多查询检索编排器。

    职责：
    - 执行多种策略的检索
    - 合并多个检索策略的结果
    - 支持去重和分数融合

    使用场景：
    - 需要组合多种检索策略的结果
    - 希望提高召回率
    """

    def __init__(
        self,
        hybrid_search: Any,
        reranker: Any | None = None,
        llm_gateway: BaseLLMGateway | None = None,
    ) -> None:
        """初始化多查询检索编排器。

        Args:
            hybrid_search: 混合检索器
            reranker: 重排序器（可选）
            llm_gateway: LLM 网关（用于查询重写）
        """
        self.hybrid_search = hybrid_search
        self.reranker = reranker
        self.llm_gateway = llm_gateway

        self.strategy_selector = StrategySelector(
            llm_gateway=llm_gateway,
            use_llm=llm_gateway is not None,
        )
        self.query_rewriter = QueryRewriter(llm_gateway=llm_gateway)

    def retrieve(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        top_k: int = 10,
        force_strategy: RetrievalStrategy | None = None,
    ) -> dict[str, Any]:
        """执行多查询检索。

        Args:
            query: 用户查询
            filters: 过滤条件
            top_k: 返回结果数量
            force_strategy: 强制使用的策略（可选）

        Returns:
            检索结果
        """
        # 1. 选择策略
        if force_strategy:
            strategy = force_strategy
        else:
            strategy = self.strategy_selector.select_strategy(query)

        logger.info(f"[MultiQueryRetrieval] 使用策略: {strategy.value}, 查询: {query[:30]}...")

        # 2. 重写查询
        rewrite_result = self.query_rewriter.rewrite(query, strategy)
        rewritten_queries = rewrite_result["rewritten_queries"]

        # 3. 执行检索
        all_results: list[dict] = []
        for q in rewritten_queries:
            results = self.hybrid_search.search(
                query_text=q,
                filters=filters,
                top_k=top_k * 2,  # 每个查询多召回一些，后续去重
            )
            all_results.extend(results)

        # 4. 去重
        unique_results = self._deduplicate_results(all_results)

        # 5. Rerank
        if self.reranker and self.reranker.is_available():
            documents = [{"content": item["content"], **item} for item in unique_results]
            reranked = self.reranker.rerank(
                query=query,
                documents=documents,
                top_n=top_k,
            )
            final_results = reranked[:top_k]
        else:
            final_results = unique_results[:top_k]

        # 6. 构建返回结果
        return {
            "results": final_results,
            "strategy": strategy.value,
            "rewritten_queries": rewritten_queries,
            "original_query": query,
            "total_retrieved": len(final_results),
            "rewrite_info": rewrite_result,
        }

    def _deduplicate_results(self, results: list[dict]) -> list[dict]:
        """去重检索结果。

        Args:
            results: 所有检索结果

        Returns:
            去重后的结果
        """
        seen_ids = set()
        unique_results = []

        for item in results:
            chunk_uuid = item.get("chunk_uuid", "")
            if chunk_uuid and chunk_uuid not in seen_ids:
                seen_ids.add(chunk_uuid)
                unique_results.append(item)
            elif not chunk_uuid:
                # 没有 chunk_uuid 的结果，直接保留
                content = item.get("content", "")
                if content and content not in seen_ids:
                    seen_ids.add(content)
                    unique_results.append(item)

        return unique_results
