"""RAG 模块包。

该目录负责文档检索、引用构造和问答上下文拼装。

检索链路架构（正确流程）：
1. FAQ 匹配 - BM25 算法匹配 FAQ 问句（置信度阈值 0.85）
   - 命中（置信度 >= 0.85）：直接返回 FAQ 答案
   - 未命中：进入 RAG 检索
2. RAG 检索（仅当 FAQ 未命中时执行）：
   2.1 策略选择 - LLM/规则驱动的策略选择
   2.2 查询重写 - 根据策略重写查询（HyDE/子查询/回溯）
   2.3 Dense Retriever - 基于语义向量的密集检索（BGE-M3 Dense）
   2.4 Sparse Retriever - 基于关键词的稀疏检索（BGE-M3 Sparse）
   2.5 Hybrid Search - Dense + Sparse 两路融合（Weighted / RRF / COFOR）
   2.6 Reranker - 语义重排序（BGE-Reranker）
   2.7 Citation Builder - 引用生成

多路检索策略：
- 直接检索（Direct）：原始查询直接检索
- HyDE 检索：使用假设答案增强检索
- 子查询检索：将复杂查询拆分为多个子查询
- 回溯问题检索：将复杂查询简化为更基础的查询

检索配置选项：
- 基础配置：Dense + Sparse 两路召回
- 标准配置：FAQ + Dense + Sparse + Rerank（推荐）
- 高质量配置：FAQ + 大召回 + 大模型 Reranker
- Milvus 原生配置：使用 Milvus 原生混合检索
"""

from core.rag.retrieval.dense_retriever import DenseRetriever
from core.rag.retrieval.sparse_retriever import SparseRetriever
from core.rag.retrieval.bm25_retriever import BM25Retriever
from core.rag.retrieval.faq_retriever import FAQRetriever, FAQSearchResult
from core.rag.retrieval.hybrid_search import HybridSearch, MilvusHybridSearch
from core.rag.retrieval.reranker import Reranker
from core.rag.retrieval_chain import RetrievalChain
from core.rag.citations.builder import CitationBuilder
from core.rag.query_rewriter import (
    RetrievalStrategy,
    StrategySelector,
    QueryRewriter,
    MultiQueryRetrieval,
)
from core.rag.factory import (
    create_retrieval_chain,
    create_simple_retrieval_chain,
    create_high_quality_retrieval_chain,
    create_rag_only_chain,
)

__all__ = [
    # 检索器
    "DenseRetriever",
    "SparseRetriever",
    "BM25Retriever",
    "FAQRetriever",
    "FAQSearchResult",
    "HybridSearch",
    "MilvusHybridSearch",
    "Reranker",
    # 链路
    "RetrievalChain",
    # 引用
    "CitationBuilder",
    # 策略和查询重写
    "RetrievalStrategy",
    "StrategySelector",
    "QueryRewriter",
    "MultiQueryRetrieval",
    # 工厂函数
    "create_retrieval_chain",
    "create_simple_retrieval_chain",
    "create_high_quality_retrieval_chain",
    "create_rag_only_chain",
]
