"""Dense 向量检索器。

Dense Retrieval 是 RAG 检索链路的第一路，负责基于语义相似度进行向量搜索。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.vectorstore.base import BaseVectorStore
    from core.embedding.gateway import EmbeddingGateway

logger = logging.getLogger(__name__)


class DenseRetriever:
    """Dense 向量检索器。

    职责：
    - 将查询文本转换为 Dense 向量（语义向量）
    - 在向量库中执行近似最近邻搜索（ANN）
    - 返回检索结果和相似度分数

    设计原因：
    - Dense 向量擅长捕捉语义相似性，例如"安全规程"和"安全生产条例"能召回相似内容
    - 企业知识场景中，用户问题往往不是精确的制度名称，需要语义理解
    - Dense Retrieval 可以弥补关键词匹配的不足，提高召回率
    """

    def __init__(
        self,
        embedding_gateway: EmbeddingGateway,
        vector_store: BaseVectorStore,
        top_k: int = 10,
        chunk_types: list[str] | None = None,
    ) -> None:
        """初始化 Dense 检索器。

        Args:
            embedding_gateway: Embedding 网关，用于生成查询向量
            vector_store: 向量存储，支持 BaseVectorStore 接口
            top_k: 默认返回结果数量
            chunk_types: 可检索的 chunk 类型过滤，例如 ["child_text", "table_summary"]
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
        """执行 Dense 检索。

        Args:
            query_text: 查询文本（用户问题）
            filters: 元数据过滤条件，用于权限控制和业务域过滤
            top_k: 返回结果数量，默认为初始化时的 top_k

        Returns:
            检索结果列表，每项包含：
            - chunk_uuid: 切片唯一标识
            - content: 切片内容
            - score: 相似度分数
            - metadata: 切片元数据
            - chunk_type: 切片类型

        示例返回：
            [
                {
                    "chunk_uuid": "chunk_abc123",
                    "content": "第一条 为了加强安全生产管理...",
                    "score": 0.856,
                    "metadata": {"section_title": "第一章 总则", ...},
                    "chunk_type": "child_text"
                },
                ...
            ]
        """

        logger.debug(f"[DenseRetriever] 检索 query={query_text[:50]}...")

        # 1. 生成 query 向量
        query_embedding = self.embedding_gateway.embed_query(query_text)
        dense_vector = query_embedding.get("dense_vector", [])

        if not dense_vector:
            logger.warning("[DenseRetriever] 生成 Dense 向量失败，返回空结果")
            return []

        # 2. 合并过滤条件
        search_filters = dict(filters) if filters else {}
        search_top_k = top_k or self.top_k

        # 3. 合并 chunk_types 过滤
        search_chunk_types = self.chunk_types

        # 4. 执行向量检索
        try:
            results = self.vector_store.search(
                dense_vector=dense_vector,
                sparse_vector={},  # Dense 检索不使用 sparse
                top_k=search_top_k,
                filters=search_filters,
                chunk_types=search_chunk_types,
            )

            logger.info(
                f"[DenseRetriever] 检索完成，召回 {len(results)} 条结果"
            )

            # 5. 格式化返回结果
            return self._format_results(results)

        except Exception as e:
            logger.error(f"[DenseRetriever] 检索异常: {e}", exc_info=True)
            return []

    def _format_results(self, results: list[dict]) -> list[dict]:
        """格式化检索结果。

        Args:
            results: 向量库原始结果

        Returns:
            格式化后的结果列表
        """

        formatted = []
        for item in results:
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
            })

        return formatted
