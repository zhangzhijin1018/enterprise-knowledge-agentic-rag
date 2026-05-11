"""BGE-Reranker 封装。

Reranker 对初步检索结果进行语义重排序，提高相关性。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.embedding.gateway import EmbeddingGateway

logger = logging.getLogger(__name__)


class Reranker:
    """BGE-Reranker 封装。

    职责：
    - 接收初步检索结果（候选文档）
    - 对 query-document 对进行相关性打分
    - 返回重排序后的结果

    设计原因：
    - 两阶段检索：先粗召回（Retrieval），再精排序（Rerank）
    - Dense/Sparse 检索追求召回率，使用 ANN 近似搜索
    - Reranker 追求精度，使用精确的语义匹配模型
    - 企业知识场景对答案准确性要求高，需要 Rerank 提升质量

    为什么用 Cross-Encoder 而不是 Bi-Encoder：
    - Bi-Encoder：query 和 doc 分别编码，预先计算 doc 向量，适合粗召回
    - Cross-Encoder：query 和 doc 一起编码，直接计算相关性分数，适合精排序
    - Rerank 需要精确相关性分数，所以使用 Cross-Encoder

    模型选择：
    - BAAI/bge-reranker-base：中文效果好的基础模型
    - BAAI/bge-reranker-large：更大更强的模型
    """

    def __init__(
        self,
        embedding_gateway: EmbeddingGateway | None = None,
        reranker_model: str = "BAAI/bge-reranker-base",
        device: str = "cpu",
        top_n: int = 5,
    ) -> None:
        """初始化 Reranker。

        Args:
            embedding_gateway: Embedding 网关（用于获取模型）
            reranker_model: Reranker 模型名称
            device: 运行设备，cpu 或 cuda
            top_n: 默认返回结果数量
        """

        self.reranker_model = reranker_model
        self.device = device
        self.top_n = top_n
        self.embedding_gateway = embedding_gateway

        # 模型懒加载
        self._model: Any = None
        self._model_loaded: bool = False

    @property
    def model(self) -> Any:
        """懒加载 Reranker 模型。"""

        if self._model is None and not self._model_loaded:
            self._load_model()

        return self._model

    def _load_model(self) -> None:
        """加载 Reranker 模型。"""

        if self._model_loaded:
            return

        logger.info(f"[Reranker] 加载模型: {self.reranker_model}, device: {self.device}")

        try:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(
                self.reranker_model,
                device=self.device,
                max_length=512,
            )
            self._model_loaded = True

            logger.info("[Reranker] 模型加载成功")

        except ImportError:
            logger.warning(
                "[Reranker] sentence-transformers 未安装，无法使用真实 Reranker。"
                "将返回原始顺序。"
            )
            self._model = None
            self._model_loaded = True

    def rerank(
        self,
        query: str,
        documents: list[dict],
        top_n: int | None = None,
    ) -> list[dict]:
        """对文档进行重排序。

        Args:
            query: 查询文本
            documents: 候选文档列表，每项需包含 content 字段
            top_n: 返回数量，默认为初始化时的 top_n

        Returns:
            重排序后的文档列表，每项包含：
            - chunk_uuid: 切片唯一标识
            - content: 切片内容
            - original_score: 原始检索分数
            - rerank_score: Reranker 相关性分数
            - metadata: 元数据

        示例：
            [
                {
                    "chunk_uuid": "chunk_abc123",
                    "content": "第一条 为了加强安全生产管理...",
                    "original_score": 0.856,
                    "rerank_score": 0.95,
                    "metadata": {...}
                },
                ...
            ]
        """

        if not documents:
            logger.warning("[Reranker] 候选文档为空，跳过重排序")
            return []

        top_k = top_n or self.top_n

        # 如果模型未加载，直接返回原始顺序（带警告）
        if self._model is None:
            logger.warning("[Reranker] Reranker 模型不可用，返回原始顺序")
            return documents[:top_k]

        logger.info(f"[Reranker] 对 {len(documents)} 个候选文档进行重排序")

        try:
            # 1. 构建 query-document pairs
            pairs = self._build_pairs(query, documents)

            # 2. 执行 rerank
            scores = self._model.predict(pairs, show_progress_bar=False)

            # 3. 转换为列表
            if hasattr(scores, "tolist"):
                scores = scores.tolist()
            elif not isinstance(scores, list):
                scores = [float(s) for s in scores]

            # 4. 附加分数到文档
            ranked_docs = []
            for i, doc in enumerate(documents):
                rerank_score = float(scores[i]) if i < len(scores) else 0.0
                doc_with_score = {
                    "chunk_uuid": doc.get("chunk_uuid", ""),
                    "content": doc.get("content", ""),
                    "content_preview": doc.get("content_preview", ""),
                    "original_score": doc.get("score", 0.0),
                    "rerank_score": rerank_score,
                    "dense_score": doc.get("dense_score", 0.0),
                    "sparse_score": doc.get("sparse_score", 0.0),
                    "metadata": doc.get("metadata", {}),
                    "chunk_type": doc.get("chunk_type", ""),
                    "chunk_index": doc.get("chunk_index", 0),
                    "section_title": doc.get("section_title"),
                    "page_start": doc.get("page_start"),
                    "page_end": doc.get("page_end"),
                    "document_id": doc.get("document_id"),
                    "parent_chunk_uuid": doc.get("parent_chunk_uuid"),
                    "matched_terms": doc.get("matched_terms", []),
                }
                ranked_docs.append(doc_with_score)

            # 5. 按 Rerank 分数排序
            ranked_docs.sort(key=lambda x: x["rerank_score"], reverse=True)

            # 6. 归一化分数到 [0, 1]
            max_score = ranked_docs[0]["rerank_score"] if ranked_docs else 1.0
            if max_score > 0:
                for doc in ranked_docs:
                    doc["rerank_score"] = round(doc["rerank_score"] / max_score, 4)

            # 7. 返回 Top-K
            result = ranked_docs[:top_k]

            logger.info(
                f"[Reranker] 重排序完成，返回 {len(result)} 个结果，"
                f"Top-1 score={result[0]['rerank_score']:.4f}"
            )

            return result

        except Exception as e:
            logger.error(f"[Reranker] 重排序异常: {e}", exc_info=True)
            # 失败时返回原始顺序
            return documents[:top_k]

    def _build_pairs(self, query: str, documents: list[dict]) -> list[tuple[str, str]]:
        """构建 query-document pairs。

        Args:
            query: 查询文本
            documents: 文档列表

        Returns:
            (query, document_content) 元组列表
        """

        pairs = []
        for doc in documents:
            content = doc.get("content", "")
            # 截断过长的文档，避免超出模型 max_length
            if len(content) > 1000:
                content = content[:1000] + "..."
            pairs.append((query, content))

        return pairs

    def is_available(self) -> bool:
        """检查 Reranker 是否可用。

        Returns:
            True 如果模型已加载且可用
        """

        if not self._model_loaded:
            self._load_model()

        return self._model is not None
