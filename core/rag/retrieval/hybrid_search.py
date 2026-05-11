"""多路混合检索编排器。

整合 Dense + Sparse 两路检索，通过分数融合返回最优结果。

融合策略：
- 加权融合：直接对多路分数加权求和
- RRF 融合：基于排名的融合算法，对不同排名位置给予递减权重
- COFOR 融合：基于共现频率的融合方法

注意：
- BM25 不再作为 RAG 检索的一路
- BM25 用于 FAQ 问句匹配，在 RAG 检索之前执行
- 只有当 FAQ 匹配置信度 < 0.85 时，才会进入 RAG 检索
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.rag.retrieval.dense_retriever import DenseRetriever
    from core.rag.retrieval.sparse_retriever import SparseRetriever

logger = logging.getLogger(__name__)


class HybridSearch:
    """多路混合检索编排器。

    职责：
    - 并行执行 Dense、Sparse 两路检索
    - 通过加权融合或 RRF 融合合并结果
    - 去重和分数归一化
    - 返回融合后的最优结果

    设计原因：
    - Dense 擅长语义理解，Sparse 擅长精确关键词匹配
    - 两路召回可以覆盖更多查询场景：
      * 语义问法（"安全注意什么"）→ Dense
      * 精确问法（"第十五条"）→ Sparse
      * 混合问法 → 多路融合
    - 融合可以兼顾语义和精确，提升整体召回质量
    - 企业知识场景中，既有语义问法也有精确问法

    分数融合策略：
    - weighted：加权融合，直接对多路分数加权求和
    - rrf：RRF 融合，基于排名的融合算法
    - cofor：COFOR 融合，基于共现频率
    - auto：自动选择最佳融合策略

    参考实现：
    - integrated_qa_system 项目中的 VectorStore.hybrid_search_with_rerank 实现
    """

    # 默认融合权重（Dense 语义理解更强，给更高权重）
    DEFAULT_DENSE_WEIGHT = 0.6
    DEFAULT_SPARSE_WEIGHT = 0.4

    def __init__(
        self,
        dense_retriever: DenseRetriever | None = None,
        sparse_retriever: SparseRetriever | None = None,
        fusion_method: str = "weighted",
        dense_weight: float = DEFAULT_DENSE_WEIGHT,
        sparse_weight: float = DEFAULT_SPARSE_WEIGHT,
        enable_auto_fusion: bool = False,
    ) -> None:
        """初始化多路混合检索编排器。

        Args:
            dense_retriever: Dense 检索器（BGE-M3 稠密向量）
            sparse_retriever: Sparse 检索器（BGE-M3 稀疏向量）
            fusion_method: 融合方法，weighted=加权融合，rrf=RRF 融合，cofor=COFOR 融合，auto=自动
            dense_weight: Dense 检索的权重
            sparse_weight: Sparse 检索的权重
            enable_auto_fusion: 是否启用自动融合策略选择
        """
        self.dense_retriever = dense_retriever
        self.sparse_retriever = sparse_retriever
        self.fusion_method = fusion_method
        self.dense_weight = dense_weight
        self.sparse_weight = sparse_weight
        self.enable_auto_fusion = enable_auto_fusion

    @property
    def active_retrievers(self) -> list[str]:
        """返回活跃的检索器列表。"""
        active = []
        if self.dense_retriever:
            active.append("dense")
        if self.sparse_retriever:
            active.append("sparse")
        return active

    @property
    def is_available(self) -> bool:
        """检查检索器是否可用。"""
        return self.dense_retriever is not None or self.sparse_retriever is not None

    def search(
        self,
        query_text: str,
        filters: dict[str, Any] | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        """执行多路混合检索。

        Args:
            query_text: 查询文本（用户问题）
            filters: 元数据过滤条件
            top_k: 返回结果数量

        Returns:
            融合后的检索结果列表，每项包含：
            - chunk_uuid: 切片唯一标识
            - content: 切片内容
            - score: 融合分数
            - dense_score: Dense 检索分数
            - sparse_score: Sparse 检索分数
            - metadata: 切片元数据
            - matched_terms: 匹配的关键词
        """
        active = self.active_retrievers
        logger.info(
            f"[HybridSearch] 执行多路检索, query={query_text[:50]}..., "
            f"retrievers={active}, fusion={self.fusion_method}, top_k={top_k}"
        )

        # 1. 并行执行多路检索
        retrieval_multiplier = 3
        results_map: dict[str, list[dict]] = {}

        if self.dense_retriever:
            dense_results = self.dense_retriever.retrieve(
                query_text=query_text,
                filters=filters,
                top_k=top_k * retrieval_multiplier,
            )
            results_map["dense"] = dense_results
            logger.info(f"[HybridSearch] Dense 召回 {len(dense_results)} 条")

        if self.sparse_retriever:
            sparse_results = self.sparse_retriever.retrieve(
                query_text=query_text,
                filters=filters,
                top_k=top_k * retrieval_multiplier,
            )
            results_map["sparse"] = sparse_results
            logger.info(f"[HybridSearch] Sparse 召回 {len(sparse_results)} 条")

        # 2. 如果所有检索结果为空，返回空
        if not results_map:
            logger.warning("[HybridSearch] 所有检索器均无可用结果")
            return []

        # 3. 选择融合策略
        fusion_method = self._select_fusion_method(query_text, results_map)

        # 4. 执行融合
        if fusion_method == "weighted":
            fused_results = self._weighted_fusion(results_map)
        elif fusion_method == "rrf":
            fused_results = self._rrf_fusion(results_map)
        elif fusion_method == "cofor":
            fused_results = self._cofor_fusion(results_map)
        else:
            fused_results = self._weighted_fusion(results_map)

        # 5. 返回 Top-K
        final_results = fused_results[:top_k]

        logger.info(
            f"[HybridSearch] 融合完成，返回 {len(final_results)} 条结果，"
            f"method={fusion_method}"
        )

        return final_results

    def _select_fusion_method(
        self,
        query_text: str,
        results_map: dict[str, list[dict]],
    ) -> str:
        """自动选择最佳融合策略。

        根据查询特征和检索结果分布选择最优融合方法。

        策略选择规则：
        - 如果启用自动融合
        - 根据查询类型判断：
          * 精确查询（包含数字、编号、制度条款等）→ 使用 weighted + 高 Sparse 权重
          * 语义查询（口语化、自然语言）→ 使用 rrf
          * 混合查询 → 使用 weighted 或 cofor

        Args:
            query_text: 查询文本
            results_map: 各检索器结果映射

        Returns:
            选择的融合方法
        """
        if not self.enable_auto_fusion:
            return self.fusion_method

        import re

        # 检测查询类型
        has_exact_terms = bool(
            re.search(r"第[一二三四五六七八九十百千万\d]+条", query_text) or  # 条款号
            re.search(r"《[^》]+》", query_text) or  # 制度名称
            re.search(r"\d{4}-\d{4}-[A-Z0-9]+", query_text)  # 编号格式
        )
        has_semantic_terms = bool(
            re.search(r"[怎如]么|如何|为什么|什么|哪些|为什么", query_text)  # 口语化
        )

        # 分析结果分布
        dense_only = len(results_map.get("dense", []))
        sparse_only = len(results_map.get("sparse", []))
        total_results = dense_only + sparse_only

        # 根据查询类型选择策略
        if has_exact_terms:
            logger.info("[HybridSearch] 检测到精确查询，使用 weighted + 高 Sparse 权重")
            # 精确查询：提高 Sparse 权重
            self.sparse_weight = 0.5
            self.dense_weight = 0.5
            return "weighted"
        elif has_semantic_terms or dense_only > sparse_only * 2:
            logger.info("[HybridSearch] 检测到语义查询，使用 rrf 融合")
            return "rrf"
        else:
            logger.info("[HybridSearch] 使用默认 weighted 融合")
            return "weighted"

    def _weighted_fusion(self, results_map: dict[str, list[dict]]) -> list[dict]:
        """加权分数融合。

        原理：对每个候选文档，计算加权分数 = Σ(score_i * weight_i)
        然后按加权分数排序。

        权重归一化：确保权重之和为1

        Args:
            results_map: 各检索器结果映射

        Returns:
            融合后的结果列表
        """
        # 计算归一化权重
        total_weight = 0.0
        weights = {}
        if self.dense_retriever and "dense" in results_map:
            weights["dense"] = self.dense_weight
            total_weight += self.dense_weight
        if self.sparse_retriever and "sparse" in results_map:
            weights["sparse"] = self.sparse_weight
            total_weight += self.sparse_weight

        # 归一化权重
        if total_weight > 0:
            for k in weights:
                weights[k] /= total_weight

        logger.debug(f"[HybridSearch] 归一化权重: {weights}")

        # 构建 score map
        score_map: dict[str, dict] = {}

        # 处理各检索器结果
        score_fields = {
            "dense": "dense_score",
            "sparse": "sparse_score",
        }

        for retriever_type, results in results_map.items():
            score_field = score_fields.get(retriever_type, f"{retriever_type}_score")
            weight = weights.get(retriever_type, 0.0)

            for item in results:
                chunk_uuid = item["chunk_uuid"]
                raw_score = item.get(score_field, item.get("score", 0.0))

                if chunk_uuid not in score_map:
                    score_map[chunk_uuid] = self._create_fusion_item(item)
                    score_map[chunk_uuid][score_field] = raw_score
                else:
                    score_map[chunk_uuid][score_field] = raw_score

                # 累加加权分数
                if "fused_score" not in score_map[chunk_uuid]:
                    score_map[chunk_uuid]["fused_score"] = 0.0
                score_map[chunk_uuid]["fused_score"] += raw_score * weight

        # 转换为列表并排序
        results = list(score_map.values())
        results.sort(key=lambda x: x["fused_score"], reverse=True)

        # 归一化最终分数到 [0, 1]
        max_score = results[0]["fused_score"] if results else 1.0
        if max_score > 0:
            for item in results:
                item["score"] = round(item["fused_score"] / max_score, 4)

        return results

    def _rrf_fusion(
        self,
        results_map: dict[str, list[dict]],
        k: int = 60,
    ) -> list[dict]:
        """RRF (Reciprocal Rank Fusion) 融合。

        原理：基于排名的融合算法，对不同检索方法的结果按排名位置给分。
        RRF_score = Σ(1 / (k + rank))

        优点：
        - 不依赖具体分数，只依赖排名
        - 对不同尺度的分数更鲁棒
        - 已被证明在多检索器融合中效果良好

        Args:
            results_map: 各检索器结果映射
            k: RRF 平滑参数，默认 60

        Returns:
            融合后的结果列表
        """
        rrf_scores: dict[str, dict] = {}

        for retriever_type, results in results_map.items():
            score_field = f"{retriever_type}_score"

            for rank, item in enumerate(results):
                chunk_uuid = item["chunk_uuid"]

                if chunk_uuid not in rrf_scores:
                    rrf_scores[chunk_uuid] = self._create_fusion_item(item)
                    rrf_scores[chunk_uuid][score_field] = item.get(score_field, item.get("score", 0.0))
                    rrf_scores[chunk_uuid][f"{retriever_type}_rank"] = rank + 1
                    rrf_scores[chunk_uuid]["rrf_score"] = 1.0 / (k + rank + 1)
                else:
                    # 已存在，累加 RRF 分数
                    rrf_scores[chunk_uuid][score_field] = item.get(score_field, item.get("score", 0.0))
                    rrf_scores[chunk_uuid][f"{retriever_type}_rank"] = rank + 1
                    rrf_scores[chunk_uuid]["rrf_score"] += 1.0 / (k + rank + 1)

        # 排序
        results = list(rrf_scores.values())
        results.sort(key=lambda x: x["rrf_score"], reverse=True)

        # 归一化分数到 [0, 1]
        max_rrf = results[0]["rrf_score"] if results else 1.0
        for item in results:
            item["score"] = round(item["rrf_score"] / max_rrf, 4) if max_rrf > 0 else 0.0

        return results

    def _cofor_fusion(self, results_map: dict[str, list[dict]]) -> list[dict]:
        """COFOR (Co-occurrence-based Fusion) 融合。

        原理：基于文档在不同检索器中的共现频率进行融合。
        如果一个文档在多个检索器中都出现，说明它更可能是相关的。

        COFOR_score = Σ(base_score_i * cooccurrence_bonus)
        cooccurrence_bonus = 1 + 0.1 * (num_retrievers - 1)

        优点：
        - 可以捕捉文档在多路检索中的一致性
        - 对跨检索器一致性高的文档给予奖励

        Args:
            results_map: 各检索器结果映射

        Returns:
            融合后的结果列表
        """
        # 构建文档在各检索器中的排名映射
        rank_maps: dict[str, dict[str, int]] = {}
        score_maps: dict[str, dict[str, float]] = {}

        for retriever_type, results in results_map.items():
            rank_maps[retriever_type] = {}
            score_maps[retriever_type] = {}
            score_field = f"{retriever_type}_score"

            for rank, item in enumerate(results):
                chunk_uuid = item["chunk_uuid"]
                rank_maps[retriever_type][chunk_uuid] = rank + 1
                score_maps[retriever_type][chunk_uuid] = item.get(score_field, item.get("score", 0.0))

        # 获取所有文档
        all_chunks = set()
        for rm in rank_maps.values():
            all_chunks.update(rm.keys())

        # 计算 COFOR 分数
        cofor_scores: dict[str, dict] = {}

        for chunk_uuid in all_chunks:
            # 获取在各检索器中的排名和分数
            item = None
            for results in results_map.values():
                for r in results:
                    if r["chunk_uuid"] == chunk_uuid:
                        item = r
                        break
                if item:
                    break

            if not item:
                continue

            cofor_item = self._create_fusion_item(item)

            # 计算共现奖励
            cooccurrence_count = sum(1 for rm in rank_maps if chunk_uuid in rm)
            cooccurrence_bonus = 1.0 + 0.1 * (cooccurrence_count - 1)

            # 计算加权分数
            fused_score = 0.0
            weights = {
                "dense": self.dense_weight,
                "sparse": self.sparse_weight,
            }

            for retriever_type in results_map:
                if chunk_uuid in score_maps.get(retriever_type, {}):
                    base_score = score_maps[retriever_type][chunk_uuid]
                    weight = weights.get(retriever_type, 1.0)
                    fused_score += base_score * weight

            cofor_item["fused_score"] = fused_score * cooccurrence_bonus
            cofor_item["cooccurrence_count"] = cooccurrence_count
            cofor_scores[chunk_uuid] = cofor_item

        # 排序
        results = list(cofor_scores.values())
        results.sort(key=lambda x: x["fused_score"], reverse=True)

        # 归一化
        max_score = results[0]["fused_score"] if results else 1.0
        if max_score > 0:
            for item in results:
                item["score"] = round(item["fused_score"] / max_score, 4)

        return results

    def _create_fusion_item(self, item: dict) -> dict:
        """创建融合结果项的模板。

        Args:
            item: 原始检索结果项

        Returns:
            包含默认值的融合项
        """
        return {
            "chunk_uuid": item.get("chunk_uuid", ""),
            "content": item.get("content", ""),
            "content_preview": item.get("content_preview", ""),
            "metadata": item.get("metadata", {}),
            "chunk_type": item.get("chunk_type", ""),
            "chunk_index": item.get("chunk_index", 0),
            "section_title": item.get("section_title"),
            "page_start": item.get("page_start"),
            "page_end": item.get("page_end"),
            "document_id": item.get("document_id"),
            "parent_chunk_uuid": item.get("parent_chunk_uuid"),
            "dense_score": 0.0,
            "sparse_score": 0.0,
            "matched_terms": item.get("matched_terms", []),
        }

    def set_weights(
        self,
        dense_weight: float | None = None,
        sparse_weight: float | None = None,
    ) -> None:
        """动态设置融合权重。

        Args:
            dense_weight: Dense 检索权重
            sparse_weight: Sparse 检索权重
        """
        if dense_weight is not None:
            self.dense_weight = dense_weight
        if sparse_weight is not None:
            self.sparse_weight = sparse_weight

        logger.info(
            f"[HybridSearch] 权重更新: dense={self.dense_weight}, "
            f"sparse={self.sparse_weight}"
        )


class MilvusHybridSearch(HybridSearch):
    """Milvus 原生混合检索封装。

    复用 Milvus 的原生混合检索能力：
    - 使用 Milvus 的 AnnSearchRequest 构建请求
    - 使用 WeightedRanker 进行融合
    - 支持同时查询 dense 和 sparse 字段

    参考 integrated_qa_system 项目中的 VectorStore.hybrid_search_with_rerank 实现
    """

    def __init__(
        self,
        milvus_client: Any,
        collection_name: str,
        embedding_function: Any,
        dense_weight: float = 1.0,
        sparse_weight: float = 0.7,
        **kwargs,
    ) -> None:
        """初始化 Milvus 混合检索。

        Args:
            milvus_client: Milvus 客户端
            collection_name: 集合名称
            embedding_function: BGE-M3 embedding 函数
            dense_weight: Dense 向量权重
            sparse_weight: Sparse 向量权重
            **kwargs: 其他参数
        """
        self.milvus_client = milvus_client
        self.collection_name = collection_name
        self.embedding_function = embedding_function
        self.dense_weight = dense_weight
        self.sparse_weight = sparse_weight
        super().__init__(**kwargs)

    def search(
        self,
        query_text: str,
        filters: dict[str, Any] | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        """使用 Milvus 原生混合检索。

        Args:
            query_text: 查询文本
            filters: 过滤条件
            top_k: 返回数量

        Returns:
            检索结果
        """
        from pymilvus import AnnSearchRequest, WeightedRanker

        logger.info(f"[MilvusHybridSearch] Milvus 原生混合检索, query={query_text[:50]}...")

        try:
            # 1. 生成查询向量
            query_embeddings = self.embedding_function([query_text])
            dense_query_vector = query_embeddings["dense"][0]

            # 2. 构建 sparse 向量
            sparse_query_vector = {}
            row = query_embeddings["sparse"][0]
            if hasattr(row, 'col'):
                indices = row.col
                values = row.data
            else:
                indices = row.indices
                values = row.data

            for idx, value in zip(indices, values):
                sparse_query_vector[idx] = value

            # 3. 构建过滤表达式
            filter_expr = ""
            if filters:
                filter_parts = []
                for k, v in filters.items():
                    if isinstance(v, str):
                        filter_parts.append(f"{k} == '{v}'")
                    else:
                        filter_parts.append(f"{k} == {v}")
                filter_expr = " and ".join(filter_parts)

            # 4. 创建搜索请求
            dense_request = AnnSearchRequest(
                data=[dense_query_vector],
                anns_field="dense_vector",
                param={"metric_type": "IP", "params": {"nprobe": 10}},
                limit=top_k * 3,
                expr=filter_expr,
            )

            sparse_request = AnnSearchRequest(
                data=[sparse_query_vector],
                anns_field="sparse_vector",
                param={"metric_type": "IP", "params": {}},
                limit=top_k * 3,
                expr=filter_expr,
            )

            # 5. 执行混合搜索
            ranker = WeightedRanker(self.dense_weight, self.sparse_weight)
            results = self.milvus_client.hybrid_search(
                collection_name=self.collection_name,
                reqs=[dense_request, sparse_request],
                ranker=ranker,
                limit=top_k,
                output_fields=["text", "parent_id", "parent_content", "source", "timestamp"],
            )[0]

            # 6. 格式化结果
            formatted = []
            for hit in results:
                entity = hit["entity"]
                formatted.append({
                    "chunk_uuid": entity.get("id", ""),
                    "content": entity.get("text", ""),
                    "content_preview": entity.get("text", "")[:200],
                    "score": hit.get("score", 0.0),
                    "dense_score": hit.get("score", 0.0),
                    "sparse_score": hit.get("score", 0.0),
                    "metadata": {
                        "parent_id": entity.get("parent_id"),
                        "parent_content": entity.get("parent_content"),
                        "source": entity.get("source"),
                        "timestamp": entity.get("timestamp"),
                    },
                    "chunk_type": "",
                    "matched_terms": [],
                })

            logger.info(f"[MilvusHybridSearch] 检索完成，返回 {len(formatted)} 条结果")
            return formatted

        except Exception as e:
            logger.error(f"[MilvusHybridSearch] 检索异常: {e}", exc_info=True)
            return []
