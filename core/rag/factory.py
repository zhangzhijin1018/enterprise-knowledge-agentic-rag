"""RAG 检索服务工厂。

提供便捷的检索服务创建方式，支持多种检索配置。

检索链路流程（正确流程）：
1. FAQ 匹配 - BM25 算法匹配 FAQ 问句（置信度阈值 0.85）
   - 命中（置信度 >= 0.85）：直接返回 FAQ 答案
   - 未命中：进入 RAG 检索
2. RAG 检索（仅当 FAQ 未命中时执行）：
   - Hybrid Search → 多路召回（Dense + Sparse）
   - Rerank → 语义精排序
   - Context Builder → 上下文构造
   - Citation Builder → 引用生成

检索配置选项：
1. 基础配置：FAQ + Dense + Sparse 两路召回
2. 标准配置：FAQ + Dense + Sparse + Rerank
3. Milvus 原生配置：使用 Milvus 原生混合检索
4. 简化配置：不使用 Reranker

注意：
- BM25 不再作为 RAG 检索的一路
- BM25 用于 FAQ 问句匹配，在 RAG 检索之前执行
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.config.settings import Settings
    from core.embedding.gateway import EmbeddingGateway
    from core.vectorstore.base import BaseVectorStore

from core.rag.retrieval.dense_retriever import DenseRetriever
from core.rag.retrieval.sparse_retriever import SparseRetriever
from core.rag.retrieval.faq_retriever import FAQRetriever
from core.rag.retrieval.hybrid_search import HybridSearch, MilvusHybridSearch
from core.rag.retrieval.reranker import Reranker
from core.rag.retrieval_chain import RetrievalChain
from core.rag.citations.builder import CitationBuilder

logger = logging.getLogger(__name__)


def create_retrieval_chain(
    embedding_gateway: EmbeddingGateway,
    vector_store: BaseVectorStore,
    settings: Settings | None = None,
    enable_faq: bool = True,
    enable_milvus_native: bool = False,
    redis_client: Any | None = None,
    mysql_client: Any | None = None,
    llm_gateway: Any | None = None,
    enable_strategy_rewrite: bool = True,
) -> RetrievalChain:
    """创建完整的检索链路。

    支持两种模式：
    1. 标准模式：FAQ + 多路策略检索 + Dense + Sparse 两路召回 + Rerank
    2. Milvus 原生模式：使用 Milvus 原生混合检索

    Args:
        embedding_gateway: Embedding 网关
        vector_store: 向量存储
        settings: 配置对象
        enable_faq: 是否启用 FAQ 匹配
        enable_milvus_native: 是否使用 Milvus 原生混合检索
        redis_client: Redis 客户端（用于 FAQ 缓存）
        mysql_client: MySQL 客户端（用于获取 FAQ 数据）
        llm_gateway: LLM 网关（用于策略选择和查询重写）
        enable_strategy_rewrite: 是否启用策略选择和查询重写

    Returns:
        配置好的检索链路
    """
    if enable_milvus_native:
        return _create_milvus_native_chain(
            embedding_gateway, vector_store, settings, enable_faq, redis_client, mysql_client,
            llm_gateway, enable_strategy_rewrite,
        )
    else:
        return _create_standard_chain(
            embedding_gateway, vector_store, settings, enable_faq, redis_client, mysql_client,
            llm_gateway, enable_strategy_rewrite,
        )


def _create_standard_chain(
    embedding_gateway: EmbeddingGateway,
    vector_store: BaseVectorStore,
    settings: Settings | None = None,
    enable_faq: bool = True,
    redis_client: Any | None = None,
    mysql_client: Any | None = None,
    llm_gateway: Any | None = None,
    enable_strategy_rewrite: bool = True,
) -> RetrievalChain:
    """创建标准检索链路（FAQ + 多路策略检索 + Dense + Sparse + Rerank）。

    Args:
        embedding_gateway: Embedding 网关
        vector_store: 向量存储
        settings: 配置对象
        enable_faq: 是否启用 FAQ 匹配
        redis_client: Redis 客户端（用于 FAQ 缓存）
        mysql_client: MySQL 客户端（用于获取 FAQ 数据）
        llm_gateway: LLM 网关（用于策略选择和查询重写）
        enable_strategy_rewrite: 是否启用策略选择和查询重写

    Returns:
        标准检索链路
    """
    logger.info("[RAGFactory] 创建标准检索链路 (FAQ + 多路策略 + Dense + Sparse)")

    # 1. 创建 FAQ 检索器（可选）
    faq_retriever = None
    if enable_faq:
        faq_retriever = FAQRetriever(
            redis_client=redis_client,
            mysql_client=mysql_client,
            confidence_threshold=0.85,
            cache_ttl=3600,
        )
        if faq_retriever.is_available():
            logger.info("[RAGFactory] FAQ 检索器已初始化")
        else:
            logger.warning("[RAGFactory] FAQ 检索器不可用，将跳过 FAQ 匹配")
            faq_retriever = None

    # 2. 创建 Dense 检索器
    # 主检索使用 child_text 和 table_summary，这些是索引粒度的切片
    dense_retriever = DenseRetriever(
        embedding_gateway=embedding_gateway,
        vector_store=vector_store,
        top_k=20,
        chunk_types=["child_text", "table_summary", "table_child"],
    )

    # 3. 创建 Sparse 检索器
    sparse_retriever = SparseRetriever(
        embedding_gateway=embedding_gateway,
        vector_store=vector_store,
        top_k=30,
        chunk_types=["child_text", "table_summary", "table_child"],
    )

    # 4. 创建混合检索编排器
    # 两路召回权重：Dense 0.6, Sparse 0.4
    hybrid_search = HybridSearch(
        dense_retriever=dense_retriever,
        sparse_retriever=sparse_retriever,
        fusion_method="weighted",
        dense_weight=0.6,
        sparse_weight=0.4,
        enable_auto_fusion=True,  # 启用自动融合策略选择
    )

    # 5. 创建 Reranker
    reranker = Reranker(
        embedding_gateway=embedding_gateway,
        reranker_model="BAAI/bge-reranker-base",
        device="cpu",
        top_n=5,
    )

    # 6. 创建引用构建器
    citation_builder = CitationBuilder(
        citation_format="bracket",
        max_citations=10,
    )

    # 7. 创建检索链路
    retrieval_chain = RetrievalChain(
        hybrid_search=hybrid_search,
        reranker=reranker,
        citation_builder=citation_builder,
        vector_store=vector_store,
        faq_retriever=faq_retriever,
        llm_gateway=llm_gateway,
        retrieve_top_k=20,
        rerank_top_k=5,
        enable_parent_expansion=True,
        enable_faq=enable_faq,
        enable_strategy_rewrite=enable_strategy_rewrite,
    )

    logger.info("[RAGFactory] 标准检索链路创建完成")

    return retrieval_chain


def _create_milvus_native_chain(
    embedding_gateway: EmbeddingGateway,
    vector_store: BaseVectorStore,
    settings: Settings | None = None,
    enable_faq: bool = True,
    redis_client: Any | None = None,
    mysql_client: Any | None = None,
    llm_gateway: Any | None = None,
    enable_strategy_rewrite: bool = True,
) -> RetrievalChain:
    """创建 Milvus 原生混合检索链路。

    使用 Milvus 的原生混合检索能力（Dense + Sparse）。

    Args:
        embedding_gateway: Embedding 网关
        vector_store: 向量存储
        settings: 配置对象
        enable_faq: 是否启用 FAQ 匹配
        redis_client: Redis 客户端（用于 FAQ 缓存）
        mysql_client: MySQL 客户端（用于获取 FAQ 数据）
        llm_gateway: LLM 网关（用于策略选择和查询重写）
        enable_strategy_rewrite: 是否启用策略选择和查询重写

    Returns:
        Milvus 原生检索链路
    """
    logger.info("[RAGFactory] 创建 Milvus 原生混合检索链路")

    # 1. 创建 FAQ 检索器（可选）
    faq_retriever = None
    if enable_faq:
        faq_retriever = FAQRetriever(
            redis_client=redis_client,
            mysql_client=mysql_client,
            confidence_threshold=0.85,
            cache_ttl=3600,
        )
        if faq_retriever.is_available():
            logger.info("[RAGFactory] FAQ 检索器已初始化")
        else:
            logger.warning("[RAGFactory] FAQ 检索器不可用，将跳过 FAQ 匹配")
            faq_retriever = None

    # 获取 Milvus 客户端
    milvus_client = getattr(vector_store, "client", None)
    if not milvus_client:
        logger.warning("[RAGFactory] 无法获取 Milvus 客户端，回退到标准链路")
        return _create_standard_chain(
            embedding_gateway, vector_store, settings, enable_faq, redis_client, mysql_client,
            llm_gateway, enable_strategy_rewrite,
        )

    # 获取 embedding 函数
    embedding_function = getattr(embedding_gateway, "embedding_function", None)
    if not embedding_function:
        logger.warning("[RAGFactory] 无法获取 embedding 函数，回退到标准链路")
        return _create_standard_chain(
            embedding_gateway, vector_store, settings, enable_faq, redis_client, mysql_client,
            llm_gateway, enable_strategy_rewrite,
        )

    # 获取集合名称
    collection_name = getattr(vector_store, "collection_name", "default")

    # 2. 创建 Milvus 原生混合检索器
    milvus_hybrid_search = MilvusHybridSearch(
        milvus_client=milvus_client,
        collection_name=collection_name,
        embedding_function=embedding_function,
        dense_weight=1.0,
        sparse_weight=0.7,
    )

    # 3. 创建包装的混合检索编排器
    hybrid_search = HybridSearch(
        dense_retriever=None,
        sparse_retriever=None,
        fusion_method="weighted",
        dense_weight=0.6,
        sparse_weight=0.4,
    )
    # 将 Milvus 搜索器作为属性存储
    hybrid_search.milvus_hybrid_search = milvus_hybrid_search

    # 4. 创建 Reranker
    reranker = Reranker(
        embedding_gateway=embedding_gateway,
        reranker_model="BAAI/bge-reranker-base",
        device="cpu",
        top_n=5,
    )

    # 5. 创建引用构建器
    citation_builder = CitationBuilder(
        citation_format="bracket",
        max_citations=10,
    )

    # 6. 创建检索链路
    retrieval_chain = RetrievalChain(
        hybrid_search=hybrid_search,
        reranker=reranker,
        citation_builder=citation_builder,
        vector_store=vector_store,
        faq_retriever=faq_retriever,
        llm_gateway=llm_gateway,
        retrieve_top_k=20,
        rerank_top_k=5,
        enable_parent_expansion=True,
        enable_faq=enable_faq,
        enable_strategy_rewrite=enable_strategy_rewrite,
    )

    logger.info("[RAGFactory] Milvus 原生混合检索链路创建完成")

    return retrieval_chain


def create_simple_retrieval_chain(
    embedding_gateway: EmbeddingGateway,
    vector_store: BaseVectorStore,
) -> RetrievalChain:
    """创建简化版检索链路（无 FAQ，无 Rerank）。

    适用于资源受限或快速原型场景。

    Args:
        embedding_gateway: Embedding 网关
        vector_store: 向量存储

    Returns:
        简化版检索链路
    """
    logger.info("[RAGFactory] 创建简化版检索链路（无 FAQ，无 Rerank）")

    # 1. 创建 Dense 检索器
    dense_retriever = DenseRetriever(
        embedding_gateway=embedding_gateway,
        vector_store=vector_store,
        top_k=10,
        chunk_types=["child_text", "table_summary"],
    )

    # 2. 创建 Sparse 检索器
    sparse_retriever = SparseRetriever(
        embedding_gateway=embedding_gateway,
        vector_store=vector_store,
        top_k=15,
        chunk_types=["child_text", "table_summary"],
    )

    # 3. 创建混合检索编排器
    hybrid_search = HybridSearch(
        dense_retriever=dense_retriever,
        sparse_retriever=sparse_retriever,
        fusion_method="weighted",
        dense_weight=0.6,
        sparse_weight=0.4,
    )

    # 4. 创建引用构建器（不使用 Reranker）
    citation_builder = CitationBuilder(
        citation_format="bracket",
        max_citations=10,
    )

    # 5. 创建检索链路（不启用 FAQ 和 Reranker）
    retrieval_chain = RetrievalChain(
        hybrid_search=hybrid_search,
        reranker=Reranker(),  # 空 Reranker
        citation_builder=citation_builder,
        vector_store=vector_store,
        faq_retriever=None,
        retrieve_top_k=10,
        rerank_top_k=5,
        enable_parent_expansion=True,
        enable_faq=False,
    )

    logger.info("[RAGFactory] 简化版检索链路创建完成")

    return retrieval_chain


def create_high_quality_retrieval_chain(
    embedding_gateway: EmbeddingGateway,
    vector_store: BaseVectorStore,
    settings: Settings | None = None,
    redis_client: Any | None = None,
    mysql_client: Any | None = None,
    llm_gateway: Any | None = None,
) -> RetrievalChain:
    """创建高质量检索链路。

    使用更大的召回数和更精细的重排序。

    Args:
        embedding_gateway: Embedding 网关
        vector_store: 向量存储
        settings: 配置对象
        redis_client: Redis 客户端（用于 FAQ 缓存）
        mysql_client: MySQL 客户端（用于获取 FAQ 数据）
        llm_gateway: LLM 网关（用于策略选择和查询重写）

    Returns:
        高质量检索链路
    """
    logger.info("[RAGFactory] 创建高质量检索链路")

    # 1. 创建 FAQ 检索器
    faq_retriever = FAQRetriever(
        redis_client=redis_client,
        mysql_client=mysql_client,
        confidence_threshold=0.85,
        cache_ttl=3600,
    )
    if not faq_retriever.is_available():
        logger.warning("[RAGFactory] FAQ 检索器不可用，将跳过 FAQ 匹配")
        faq_retriever = None

    # 2. 创建 Dense 检索器
    dense_retriever = DenseRetriever(
        embedding_gateway=embedding_gateway,
        vector_store=vector_store,
        top_k=50,
        chunk_types=["child_text", "table_summary", "table_child"],
    )

    # 3. 创建 Sparse 检索器
    sparse_retriever = SparseRetriever(
        embedding_gateway=embedding_gateway,
        vector_store=vector_store,
        top_k=50,
        chunk_types=["child_text", "table_summary", "table_child"],
    )

    # 4. 创建混合检索编排器
    hybrid_search = HybridSearch(
        dense_retriever=dense_retriever,
        sparse_retriever=sparse_retriever,
        fusion_method="rrf",  # 使用 RRF 融合
        enable_auto_fusion=True,
    )

    # 5. 创建高质量 Reranker（使用更大的模型）
    reranker = Reranker(
        embedding_gateway=embedding_gateway,
        reranker_model="BAAI/bge-reranker-large",  # 使用更大的模型
        device="cpu",
        top_n=10,  # 返回更多重排序结果
    )

    # 6. 创建引用构建器
    citation_builder = CitationBuilder(
        citation_format="bracket",
        max_citations=15,
    )

    # 7. 创建检索链路
    retrieval_chain = RetrievalChain(
        hybrid_search=hybrid_search,
        reranker=reranker,
        citation_builder=citation_builder,
        vector_store=vector_store,
        faq_retriever=faq_retriever,
        llm_gateway=llm_gateway,
        retrieve_top_k=50,
        rerank_top_k=10,
        enable_parent_expansion=True,
        enable_faq=True,
        enable_strategy_rewrite=True,
    )

    logger.info("[RAGFactory] 高质量检索链路创建完成")

    return retrieval_chain


def create_rag_only_chain(
    embedding_gateway: EmbeddingGateway,
    vector_store: BaseVectorStore,
    settings: Settings | None = None,
) -> RetrievalChain:
    """创建纯 RAG 检索链路（跳过 FAQ 匹配）。

    适用于不需要 FAQ 匹配，直接使用 RAG 检索的场景。

    Args:
        embedding_gateway: Embedding 网关
        vector_store: 向量存储
        settings: 配置对象

    Returns:
        纯 RAG 检索链路
    """
    logger.info("[RAGFactory] 创建纯 RAG 检索链路（跳过 FAQ）")

    # 1. 创建 Dense 检索器
    dense_retriever = DenseRetriever(
        embedding_gateway=embedding_gateway,
        vector_store=vector_store,
        top_k=20,
        chunk_types=["child_text", "table_summary", "table_child"],
    )

    # 2. 创建 Sparse 检索器
    sparse_retriever = SparseRetriever(
        embedding_gateway=embedding_gateway,
        vector_store=vector_store,
        top_k=30,
        chunk_types=["child_text", "table_summary", "table_child"],
    )

    # 3. 创建混合检索编排器
    hybrid_search = HybridSearch(
        dense_retriever=dense_retriever,
        sparse_retriever=sparse_retriever,
        fusion_method="weighted",
        dense_weight=0.6,
        sparse_weight=0.4,
        enable_auto_fusion=True,
    )

    # 4. 创建 Reranker
    reranker = Reranker(
        embedding_gateway=embedding_gateway,
        reranker_model="BAAI/bge-reranker-base",
        device="cpu",
        top_n=5,
    )

    # 5. 创建引用构建器
    citation_builder = CitationBuilder(
        citation_format="bracket",
        max_citations=10,
    )

    # 6. 创建检索链路（跳过 FAQ）
    retrieval_chain = RetrievalChain(
        hybrid_search=hybrid_search,
        reranker=reranker,
        citation_builder=citation_builder,
        vector_store=vector_store,
        faq_retriever=None,
        retrieve_top_k=20,
        rerank_top_k=5,
        enable_parent_expansion=True,
        enable_faq=False,
    )

    logger.info("[RAGFactory] 纯 RAG 检索链路创建完成")

    return retrieval_chain
