"""RAG 检索模块包。

该模块负责混合检索、语义重排序和检索结果处理。

检索链路（正确流程）：
1. FAQ 匹配 - BM25 算法匹配 FAQ 问句（置信度阈值 0.85）
2. RAG 检索（仅当 FAQ 未命中时执行）：
   2.1 Dense Retriever - 基于语义向量的密集检索（BGE-M3 Dense）
   2.2 Sparse Retriever - 基于关键词权重的稀疏检索（BGE-M3 Sparse）
   2.3 Hybrid Search - Dense + Sparse 两路融合
   2.4 Reranker - 语义重排序
"""

from core.rag.retrieval.dense_retriever import DenseRetriever
from core.rag.retrieval.sparse_retriever import SparseRetriever
from core.rag.retrieval.bm25_retriever import BM25Retriever
from core.rag.retrieval.faq_retriever import FAQRetriever, FAQSearchResult
from core.rag.retrieval.hybrid_search import HybridSearch, MilvusHybridSearch
from core.rag.retrieval.reranker import Reranker
from core.rag.retrieval_chain import RetrievalChain
from core.rag.citations.builder import CitationBuilder

__all__ = [
    "DenseRetriever",
    "SparseRetriever",
    "BM25Retriever",
    "FAQRetriever",
    "FAQSearchResult",
    "HybridSearch",
    "MilvusHybridSearch",
    "Reranker",
    "RetrievalChain",
    "CitationBuilder",
]
