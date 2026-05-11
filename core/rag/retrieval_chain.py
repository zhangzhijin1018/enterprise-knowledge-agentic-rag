"""RAG 检索链路编排器。

整合 FAQ 匹配 + 多路检索策略 + Rerank + 上下文构造。

检索链路流程（正确流程）：
1. FAQ 匹配 - BM25 算法匹配 FAQ 问句（置信度阈值 0.85）
   1.1 如果命中（置信度 >= 0.85）：直接返回 FAQ 答案
   1.2 如果未命中：进入 RAG 检索
2. RAG 检索（仅当 FAQ 未命中时执行）：
   2.1 策略选择 - LLM/规则驱动的策略选择
   2.2 查询重写 - 根据策略重写查询（HyDE/子查询/回溯）
   2.3 Hybrid Search → 多路召回（Dense + Sparse）
   2.4 Rerank → 语义精排序
   2.5 Parent Expansion → 父块回扩（可选）
   2.6 Context Builder → 上下文构造
   2.7 Citation Builder → 引用生成

设计原因：
- FAQ 优先匹配可以减少不必要的 LLM 调用
- 对于高频、标准化的问答，FAQ 匹配更准确、更快
- 多路策略检索可以应对不同类型的查询：
  * 直接检索：意图明确的查询
  * HyDE：抽象查询
  * 子查询：复杂多主题查询
  * 回溯问题：需要简化的复杂查询
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.rag.retrieval.hybrid_search import HybridSearch
    from core.rag.retrieval.faq_retriever import FAQRetriever, FAQSearchResult
    from core.rag.retrieval.reranker import Reranker
    from core.rag.citations.builder import CitationBuilder
    from core.vectorstore.base import BaseVectorStore
    from core.llm.base import BaseLLMGateway
    from core.rag.query_rewriter import RetrievalStrategy

logger = logging.getLogger(__name__)


class RetrievalChain:
    """RAG 检索链路编排器。

    职责：
    - 执行 FAQ 匹配（BM25 问句匹配）
    - 执行多路混合检索（Hybrid Search）
    - 对结果进行语义重排序（Rerank）
    - 构造检索上下文
    - 生成引用信息
    - 可选：回扩父块获取完整上下文

    处理流程：
    1. FAQ 匹配 → BM25 算法匹配 FAQ 问句
       - 命中（置信度 >= 0.85）：返回 FAQ 答案
       - 未命中：进入 RAG 检索
    2. RAG 检索（仅当 FAQ 未命中时）：
       - 策略选择 → 选择合适的检索策略
       - 查询重写 → 根据策略重写查询
       - Hybrid Search → 多路召回
       - Rerank → 语义精排序
       - Context Builder → 上下文构造
       - Citation Builder → 引用生成

    支持的检索模式：
    - FAQ 优先匹配 + 多路策略检索 + Dense + Sparse 两路召回
    - 仅 RAG 检索（跳过 FAQ）
    - 支持策略选择和查询重写
    """

    def __init__(
        self,
        hybrid_search: HybridSearch,
        reranker: Reranker,
        citation_builder: CitationBuilder,
        vector_store: BaseVectorStore | None = None,
        faq_retriever: FAQRetriever | None = None,
        llm_gateway: BaseLLMGateway | None = None,
        retrieve_top_k: int = 20,
        rerank_top_k: int = 5,
        enable_parent_expansion: bool = True,
        enable_faq: bool = True,
        enable_strategy_rewrite: bool = True,
    ) -> None:
        """初始化检索链路编排器。

        Args:
            hybrid_search: 混合检索器（Dense + Sparse）
            reranker: 重排序器
            citation_builder: 引用构建器
            vector_store: 向量存储（用于父块回扩）
            faq_retriever: FAQ 检索器（BM25 问句匹配）
            llm_gateway: LLM 网关（用于策略选择和查询重写）
            retrieve_top_k: 检索阶段返回的数量
            rerank_top_k: Rerank 阶段返回的数量
            enable_parent_expansion: 是否启用父块回扩
            enable_faq: 是否启用 FAQ 匹配
            enable_strategy_rewrite: 是否启用策略选择和查询重写
        """
        self.hybrid_search = hybrid_search
        self.reranker = reranker
        self.citation_builder = citation_builder
        self.vector_store = vector_store
        self.faq_retriever = faq_retriever
        self.llm_gateway = llm_gateway
        self.retrieve_top_k = retrieve_top_k
        self.rerank_top_k = rerank_top_k
        self.enable_parent_expansion = enable_parent_expansion
        self.enable_faq = enable_faq
        self.enable_strategy_rewrite = enable_strategy_rewrite

        # 初始化策略选择器和查询重写器
        self._init_strategy_components()

    def _init_strategy_components(self) -> None:
        """初始化策略选择和查询重写组件。"""
        if not self.enable_strategy_rewrite or not self.llm_gateway:
            self.strategy_selector = None
            self.query_rewriter = None
            return

        try:
            from core.rag.query_rewriter import StrategySelector, QueryRewriter

            self.strategy_selector = StrategySelector(
                llm_gateway=self.llm_gateway,
                use_llm=True,
            )
            self.query_rewriter = QueryRewriter(
                llm_gateway=self.llm_gateway,
            )
            logger.info("[RetrievalChain] 策略选择器和查询重写器初始化完成")
        except ImportError as e:
            logger.warning(f"[RetrievalChain] 无法导入策略组件: {e}")
            self.strategy_selector = None
            self.query_rewriter = None

    def retrieve(
        self,
        query_text: str,
        filters: dict[str, Any] | None = None,
        user_context: Any | None = None,
        enable_rerank: bool = True,
        skip_faq: bool = False,
        force_strategy: str | None = None,
    ) -> dict:
        """执行完整检索链路。

        流程：
        1. 如果启用 FAQ，先进行 FAQ 匹配
           - 命中（置信度 >= 0.85）：返回 FAQ 答案
           - 未命中：继续 RAG 检索
        2. RAG 检索（仅当 FAQ 未命中时）
           - 策略选择 → 选择合适的检索策略
           - 查询重写 → 根据策略重写查询
           - Hybrid Search → 多路召回
           - Rerank → 语义精排序
           - Context Builder → 上下文构造
           - Citation Builder → 引用生成

        Args:
            query_text: 查询文本（用户问题）
            filters: 元数据过滤条件，用于权限过滤和业务域限制
            user_context: 用户上下文（可选，用于扩展过滤条件）
            enable_rerank: 是否启用 Rerank
            skip_faq: 是否跳过 FAQ 匹配（强制使用 RAG）
            force_strategy: 强制使用的检索策略（direct/hyde/subquery/backtracking）

        Returns:
            {
                "source": "faq" | "rag",  # 答案来源
                "faq_result": {...} | None,  # FAQ 匹配结果（如果命中）
                "chunks": [...],  # 检索到的 chunks（仅 RAG 模式）
                "context": "...",  # 构造的上下文（仅 RAG 模式）
                "citations": [...],  # 引用信息（仅 RAG 模式）
                "query": "...",  # 原始查询
                "rewritten_queries": [...],  # 重写后的查询列表
                "strategy": "...",  # 使用的检索策略
                "total_retrieved": 10,  # 总召回数
                "metadata": {...}  # 检索元数据
            }
        """
        logger.info(f"[RetrievalChain] 开始检索, query={query_text[:50]}...")

        # 1. FAQ 匹配（如果启用）
        if self.enable_faq and not skip_faq and self.faq_retriever:
            faq_result = self._try_faq_match(query_text)
            if faq_result and faq_result.found:
                logger.info(
                    f"[RetrievalChain] FAQ 命中，置信度={faq_result.confidence:.3f}，"
                    f"直接返回 FAQ 答案"
                )
                return {
                    "source": "faq",
                    "faq_result": faq_result.to_dict(),
                    "chunks": [],
                    "context": faq_result.answer or "",
                    "citations": [],
                    "query": query_text,
                    "rewritten_queries": [],
                    "strategy": "faq_match",
                    "total_retrieved": 0,
                    "metadata": {
                        "faq_confidence": faq_result.confidence,
                        "faq_matched_question": faq_result.question,
                        "faq_threshold": 0.85,
                        "rag_triggered": False,
                    },
                }

        # 2. RAG 检索（仅当 FAQ 未命中时）
        logger.info("[RetrievalChain] FAQ 未命中或已跳过，进入 RAG 检索")

        # 2.1 策略选择和查询重写
        retrieval_strategy = "direct"
        rewritten_queries = [query_text]
        rewrite_info = None

        if self.enable_strategy_rewrite and self.strategy_selector and self.query_rewriter:
            from core.rag.query_rewriter import RetrievalStrategy

            # 选择策略
            if force_strategy:
                try:
                    strategy_enum = RetrievalStrategy.from_string(force_strategy)
                except ValueError:
                    strategy_enum = self.strategy_selector.select_strategy(query_text)
            else:
                strategy_enum = self.strategy_selector.select_strategy(query_text)

            retrieval_strategy = strategy_enum.value

            # 重写查询
            rewrite_result = self.query_rewriter.rewrite(query_text, strategy_enum)
            rewritten_queries = rewrite_result.get("rewritten_queries", [query_text])
            rewrite_info = rewrite_result

            logger.info(
                f"[RetrievalChain] 策略: {retrieval_strategy}, "
                f"重写查询数: {len(rewritten_queries)}"
            )

        # 2.2 多路混合检索（支持多查询）
        all_results: list[dict] = []
        for q in rewritten_queries:
            results = self.hybrid_search.search(
                query_text=q,
                filters=filters,
                top_k=self.retrieve_top_k,
            )
            all_results.extend(results)

        # 去重
        hybrid_results = self._deduplicate_results(all_results)

        if not hybrid_results:
            logger.info("[RetrievalChain] 多路检索无结果")
            return self._empty_result(
                query_text,
                faq_confidence=faq_result.confidence if faq_result else 0.0,
                strategy=retrieval_strategy,
                rewritten_queries=rewritten_queries,
                rewrite_info=rewrite_info,
            )

        logger.info(
            f"[RetrievalChain] 多路检索召回 {len(hybrid_results)} 条，"
            f"retrievers={self.hybrid_search.active_retrievers}"
        )

        # 2.3 Rerank
        if enable_rerank and self.reranker.is_available():
            documents = [{"content": item["content"], **item} for item in hybrid_results]
            reranked = self.reranker.rerank(
                query=query_text,
                documents=documents,
                top_n=self.rerank_top_k,
            )

            # 合并 Rerank 结果
            reranked_map = {
                item["chunk_uuid"]: item for item in reranked
            }
            final_chunks = []
            for item in hybrid_results:
                chunk_uuid = item["chunk_uuid"]
                if chunk_uuid in reranked_map:
                    # 合并 Rerank 分数和原始信息
                    merged = {**item, **reranked_map[chunk_uuid]}
                    final_chunks.append(merged)
                else:
                    final_chunks.append(item)

            logger.info(
                f"[RetrievalChain] Rerank 完成，Top-1 score={reranked[0]['rerank_score']:.4f}"
            )
        else:
            # 不启用 Rerank，直接使用混合检索结果
            final_chunks = hybrid_results[:self.rerank_top_k]
            logger.info("[RetrievalChain] 跳过 Rerank")

        # 2.4 父块回扩（可选）
        if self.enable_parent_expansion and self.vector_store:
            final_chunks = self._expand_parent_chunks(final_chunks)

        # 2.5 构造上下文
        context = self._build_context(final_chunks)

        # 2.6 生成引用
        citations = self.citation_builder.build_citations(final_chunks)

        # 2.7 构建返回结果
        result = {
            "source": "rag",
            "faq_result": faq_result.to_dict() if faq_result else None,
            "chunks": final_chunks,
            "context": context,
            "citations": citations,
            "query": query_text,
            "rewritten_queries": rewritten_queries,
            "strategy": retrieval_strategy,
            "total_retrieved": len(final_chunks),
            "metadata": {
                "retrieve_top_k": self.retrieve_top_k,
                "rerank_top_k": self.rerank_top_k,
                "rerank_enabled": enable_rerank and self.reranker.is_available(),
                "parent_expansion_enabled": self.enable_parent_expansion,
                "fusion_method": getattr(
                    self.hybrid_search, "fusion_method", "unknown"
                ),
                "active_retrievers": self.hybrid_search.active_retrievers,
                "faq_confidence": faq_result.confidence if faq_result else 0.0,
                "faq_threshold": 0.85,
                "rag_triggered": True,
                "strategy_rewrite_enabled": self.enable_strategy_rewrite,
                # 各路召回得分统计
                "retrieval_stats": self._compute_retrieval_stats(hybrid_results),
            },
        }

        if rewrite_info:
            result["rewrite_info"] = rewrite_info

        logger.info(
            f"[RetrievalChain] RAG 检索完成，返回 {len(final_chunks)} 条结果"
        )

        return result

    def _try_faq_match(self, query_text: str) -> FAQSearchResult | None:
        """尝试 FAQ 匹配。

        使用 BM25 算法对用户问句与 FAQ 问句进行关键词匹配。

        Args:
            query_text: 用户问句

        Returns:
            FAQSearchResult：如果 FAQ 可用
            None：如果 FAQ 不可用
        """
        if not self.faq_retriever:
            logger.debug("[RetrievalChain] 未配置 FAQ 检索器")
            return None

        if not self.faq_retriever.is_available():
            logger.debug("[RetrievalChain] FAQ 检索器不可用")
            return None

        try:
            return self.faq_retriever.search(query_text)
        except Exception as e:
            logger.warning(f"[RetrievalChain] FAQ 匹配失败: {e}")
            return None

    def _deduplicate_results(self, results: list[dict]) -> list[dict]:
        """去重检索结果。

        Args:
            results: 检索结果列表

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
                # 没有 chunk_uuid 的结果，基于内容去重
                content = item.get("content", "")
                if content and content not in seen_ids:
                    seen_ids.add(content)
                    unique_results.append(item)

        return unique_results

    def _compute_retrieval_stats(self, results: list[dict]) -> dict:
        """计算各路召回的得分统计。

        Args:
            results: 混合检索结果

        Returns:
            各路得分统计
        """
        stats = {
            "dense_recall": 0,
            "sparse_recall": 0,
            "avg_dense_score": 0.0,
            "avg_sparse_score": 0.0,
        }

        if not results:
            return stats

        # 统计各路召回数量
        dense_count = sum(1 for r in results if r.get("dense_score", 0) > 0)
        sparse_count = sum(1 for r in results if r.get("sparse_score", 0) > 0)

        stats["dense_recall"] = dense_count
        stats["sparse_recall"] = sparse_count

        # 计算平均分数
        if dense_count > 0:
            stats["avg_dense_score"] = round(
                sum(r.get("dense_score", 0) for r in results if r.get("dense_score", 0) > 0) / dense_count, 4
            )
        if sparse_count > 0:
            stats["avg_sparse_score"] = round(
                sum(r.get("sparse_score", 0) for r in results if r.get("sparse_score", 0) > 0) / sparse_count, 4
            )

        return stats

    def _expand_parent_chunks(self, chunks: list[dict]) -> list[dict]:
        """回扩父块，获取更完整的上下文。

        对于子块（如 child_text），回扩其对应的父块（parent_text），
        以便在上下文中提供更完整的语义信息。

        Args:
            chunks: 当前检索结果

        Returns:
            回扩后的 chunks
        """
        if not chunks:
            return chunks

        # 找出需要回扩的子块
        need_expansion = []
        for chunk in chunks:
            if chunk.get("parent_chunk_uuid") and chunk.get("level") == 2:
                need_expansion.append(chunk)

        if not need_expansion:
            return chunks

        logger.info(f"[RetrievalChain] 父块回扩 {len(need_expansion)} 个子块")

        # 获取父块
        parent_uuids = list(set(
            chunk["parent_chunk_uuid"]
            for chunk in need_expansion
            if chunk.get("parent_chunk_uuid")
        ))

        # 从向量存储获取父块内容
        # 注意：这里简化了实现，实际需要查询向量库
        # TODO: 实现真实的父块查询
        # parent_chunks = self.vector_store.get_by_chunk_uuids(parent_uuids)

        # 暂时不做实际回扩，保留原逻辑
        # 后续可以通过 vector_store 的接口获取父块内容
        # parent_map = {p["chunk_uuid"]: p for p in parent_chunks}

        # 标记需要回扩的块
        for chunk in chunks:
            if chunk.get("parent_chunk_uuid"):
                chunk["parent_expanded"] = False
                chunk["parent_uuid"] = chunk["parent_chunk_uuid"]

        return chunks

    def _build_context(self, chunks: list[dict]) -> str:
        """构造检索上下文。

        将检索结果组织成适合 LLM 理解的文本格式。

        Args:
            chunks: 检索结果 chunks

        Returns:
            格式化后的上下文文本
        """
        if not chunks:
            return ""

        context_parts = []

        for i, chunk in enumerate(chunks, 1):
            # 构建单个文档块
            section_title = chunk.get("section_title") or chunk.get("metadata", {}).get("section_title", "")
            page_info = ""
            if chunk.get("page_start"):
                page_info = f"，位于第 {chunk['page_start']} 页"
                if chunk.get("page_end") and chunk["page_end"] != chunk["page_start"]:
                    page_info = f"，位于第 {chunk['page_start']}-{chunk['page_end']} 页"

            chunk_type = chunk.get("chunk_type", "")
            type_hint = ""
            if chunk_type == "table_parent" or chunk_type == "table_summary":
                type_hint = "【表格】"
            elif chunk_type == "table_child":
                type_hint = "【表格片段】"

            # 添加召回来源信息
            recall_sources = []
            if chunk.get("dense_score", 0) > 0:
                recall_sources.append("语义")
            if chunk.get("sparse_score", 0) > 0:
                recall_sources.append("稀疏")
            source_hint = f"({','.join(recall_sources)})" if recall_sources else ""

            header = f"{type_hint}【文档 {i}】{source_hint}"
            if section_title:
                header += f" {section_title}{page_info}"
            else:
                header += page_info

            content = chunk.get("content", "")

            context_parts.append(f"{header}\n{content}")

        # 使用双换行分隔不同文档
        context = "\n\n".join(context_parts)

        # 添加分隔提示
        header = "以下是检索到的相关文档：\n\n"

        return header + context

    def _empty_result(
        self,
        query_text: str,
        faq_confidence: float = 0.0,
        strategy: str = "direct",
        rewritten_queries: list[str] | None = None,
        rewrite_info: dict | None = None,
    ) -> dict:
        """返回空结果。"""
        return {
            "source": "rag",
            "faq_result": None,
            "chunks": [],
            "context": "",
            "citations": [],
            "query": query_text,
            "rewritten_queries": rewritten_queries or [query_text],
            "strategy": strategy,
            "total_retrieved": 0,
            "metadata": {
                "retrieve_top_k": self.retrieve_top_k,
                "rerank_top_k": self.rerank_top_k,
                "rerank_enabled": False,
                "parent_expansion_enabled": self.enable_parent_expansion,
                "active_retrievers": self.hybrid_search.active_retrievers,
                "faq_confidence": faq_confidence,
                "faq_threshold": 0.85,
                "rag_triggered": True,
                "strategy_rewrite_enabled": self.enable_strategy_rewrite,
                "retrieval_stats": {
                    "dense_recall": 0,
                    "sparse_recall": 0,
                    "avg_dense_score": 0.0,
                    "avg_sparse_score": 0.0,
                },
            },
            "rewrite_info": rewrite_info,
        }

    def refresh(self) -> None:
        """刷新检索器状态。

        当数据源变化时调用，重新初始化各组件。
        """
        logger.info("[RetrievalChain] 刷新检索器状态")

        # 刷新 FAQ 检索器
        if self.faq_retriever and hasattr(self.faq_retriever, "refresh"):
            self.faq_retriever.refresh()

    def is_faq_available(self) -> bool:
        """检查 FAQ 检索是否可用。"""
        return self.faq_retriever is not None and self.faq_retriever.is_available()

    def is_rag_available(self) -> bool:
        """检查 RAG 检索是否可用。"""
        return self.hybrid_search is not None and self.hybrid_search.is_available

    def is_strategy_rewrite_available(self) -> bool:
        """检查策略重写是否可用。"""
        return (
            self.enable_strategy_rewrite
            and self.strategy_selector is not None
            and self.query_rewriter is not None
        )
