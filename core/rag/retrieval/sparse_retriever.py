"""Sparse 向量检索器。

Sparse Retrieval 是 RAG 检索链路的一路，负责基于关键词权重进行稀疏向量搜索。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.vectorstore.base import BaseVectorStore
    from core.embedding.gateway import EmbeddingGateway

logger = logging.getLogger(__name__)


class SparseRetriever:
    """Sparse 向量检索器。

    职责：
    - 将查询文本转换为 Sparse 向量（词权重）
    - 在向量库中执行稀疏向量搜索
    - 返回检索结果和关键词匹配分数

    设计原因：
    - Sparse 向量擅长精确匹配，例如制度条款号、设备编号、表头关键词
    - 企业文档场景中，用户经常使用精确的制度名称或编号进行查询
    - Sparse Retrieval 可以弥补 Dense 向量在精确匹配上的不足
    - 典型场景："《安全生产管理制度》第十五条"、"设备编号 EQ-2024-001"
    """

    def __init__(
        self,
        embedding_gateway: EmbeddingGateway,
        vector_store: BaseVectorStore,
        top_k: int = 20,
        chunk_types: list[str] | None = None,
    ) -> None:
        """初始化 Sparse 检索器。

        Args:
            embedding_gateway: Embedding 网关，用于生成查询向量
            vector_store: 向量存储，支持 BaseVectorStore 接口
            top_k: 默认返回结果数量
            chunk_types: 可检索的 chunk 类型过滤
        """

        self.embedding_gateway = embedding_gateway
        self.vector_store = vector_store
        self.top_k = top_k
        self.chunk_types = chunk_types

    def retrieve(
        self,
        query_text: str,
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> list[dict]:
        """执行 Sparse 检索。

        Args:
            query_text: 查询文本（用户问题）
            filters: 元数据过滤条件，用于权限控制和业务域过滤
            top_k: 返回结果数量，默认为初始化时的 top_k

        Returns:
            检索结果列表，每项包含：
            - chunk_uuid: 切片唯一标识
            - content: 切片内容
            - score: 关键词匹配分数
            - metadata: 切片元数据
            - chunk_type: 切片类型
            - matched_terms: 匹配的关键词列表

        示例返回：
            [
                {
                    "chunk_uuid": "chunk_xyz789",
                    "content": "第十五条 安全生产责任...",
                    "score": 0.723,
                    "metadata": {"section_title": "安全责任", ...},
                    "chunk_type": "child_text",
                    "matched_terms": ["安全生产", "责任", "第十五条"]
                },
                ...
            ]
        """

        logger.debug(f"[SparseRetriever] 检索 query={query_text[:50]}...")

        # 1. 生成 query sparse 向量
        query_embedding = self.embedding_gateway.embed_query(query_text)
        sparse_vector = query_embedding.get("sparse_vector", {})

        if not sparse_vector:
            logger.warning("[SparseRetriever] 生成 Sparse 向量失败，返回空结果")
            return []

        # 2. 合并过滤条件
        search_filters = dict(filters) if filters else {}
        search_top_k = top_k or self.top_k

        # 3. 合并 chunk_types 过滤
        search_chunk_types = self.chunk_types

        # 4. 执行稀疏向量检索
        try:
            results = self.vector_store.search(
                dense_vector=[],  # Sparse 检索不使用 dense
                sparse_vector=sparse_vector,
                top_k=search_top_k,
                filters=search_filters,
                chunk_types=search_chunk_types,
            )

            logger.info(
                f"[SparseRetriever] 检索完成，召回 {len(results)} 条结果"
            )

            # 5. 提取匹配的关键词
            matched_terms = list(sparse_vector.keys())

            # 6. 格式化返回结果
            return self._format_results(results, matched_terms)

        except Exception as e:
            logger.error(f"[SparseRetriever] 检索异常: {e}", exc_info=True)
            return []

    def _format_results(self, results: list[dict], matched_terms: list[str]) -> list[dict]:
        """格式化检索结果。

        Args:
            results: 向量库原始结果
            matched_terms: 匹配的关键词列表

        Returns:
            格式化后的结果列表
        """

        formatted = []
        for item in results:
            # 提取该结果匹配的关键词
            result_matched = self._extract_matched_terms(item, matched_terms)

            formatted.append({
                "chunk_uuid": item.get("chunk_uuid", ""),
                "content": item.get("content", ""),
                "content_preview": item.get("content_preview", "")[:200],
                "score": item.get("score", 0.0),
                "dense_score": item.get("dense_score", 0.0),
                "sparse_score": item.get("sparse_score", 0.0),
                "metadata": item.get("metadata", {}),
                "chunk_type": item.get("chunk_type", ""),
                "chunk_index": item.get("chunk_index", 0),
                "section_title": item.get("section_title"),
                "page_start": item.get("page_start"),
                "page_end": item.get("page_end"),
                "document_id": item.get("document_id"),
                "parent_chunk_uuid": item.get("parent_chunk_uuid"),
                "matched_terms": result_matched,
            })

        return formatted

    def _extract_matched_terms(self, item: dict, all_matched_terms: list[str]) -> list[str]:
        """提取结果中匹配的关键词。

        Args:
            item: 检索结果项
            all_matched_terms: 查询中所有匹配的关键词

        Returns:
            该结果中匹配的关键词列表
        """

        content = item.get("content", "").lower()
        matched = []

        for term in all_matched_terms:
            if term.lower() in content:
                matched.append(term)

        return matched[:10]  # 最多返回 10 个匹配词
