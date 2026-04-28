"""Milvus Store。

当前实现目标：
- 按 Milvus schema 设计检索对象字段；
- 本地无 Milvus 时使用内存回退，保证 ingestion / retrieval 闭环可跑；
- 保持接口与真实 Milvus 一致，后续替换真实 SDK 实现时不改上层业务服务。

设计原则：
- PostgreSQL 存完整主数据与状态；
- 向量库只存“检索与检索前过滤所需的最小充分字段”；
- 这样才能做到真正的 metadata filter 前置，而不是先召回再在应用层过滤。
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from core.vectorstore.base import BaseVectorStore

_VECTOR_RECORDS: dict[str, dict] = {}


def reset_in_memory_vector_store() -> None:
    """重置内存向量库。"""

    _VECTOR_RECORDS.clear()


class MilvusStore(BaseVectorStore):
    """Milvus 风格向量存储。

    当前阶段主路径：
    - 默认使用 in-memory fallback；
    - 但字段设计、接口语义和 hybrid retrieval 方式都按 Milvus 目标模型实现；
    - 后续接真实 Milvus SDK 时，主要替换这个类的内部实现。
    """

    def __init__(self, collection_name: str = "document_chunks_v1") -> None:
        """初始化 Milvus Store。"""

        self.collection_name = collection_name

    def upsert_chunks(self, chunks: list[dict]) -> list[dict]:
        """批量写入向量记录。"""

        upserted: list[dict] = []
        for chunk in chunks:
            record = {
                **chunk,
                "milvus_primary_key": chunk.get("milvus_primary_key") or chunk["chunk_uuid"],
                "indexed_at": datetime.now(timezone.utc),
            }
            _VECTOR_RECORDS[record["chunk_uuid"]] = record
            upserted.append(record)
        return upserted

    def delete_by_document_id(self, document_id: str) -> int:
        """按文档 ID 删除已有向量。"""

        keys_to_delete = [
            chunk_uuid
            for chunk_uuid, record in _VECTOR_RECORDS.items()
            if record["document_id"] == document_id
        ]
        for chunk_uuid in keys_to_delete:
            _VECTOR_RECORDS.pop(chunk_uuid, None)
        return len(keys_to_delete)

    def search(
        self,
        dense_vector: list[float],
        sparse_vector: dict[str, float],
        top_k: int,
        filters: dict | None = None,
        chunk_types: list[str] | None = None,
    ) -> list[dict]:
        """执行最小 hybrid retrieval。

        当前实现不是最终版召回排序器，而是最小可运行版：
        1. 先基于 metadata filter 过滤候选集；
        2. 分别计算 dense 分数和 sparse 分数；
        3. 分别取 dense/sparse top candidates；
        4. 用简单融合分数做最终排序。

        这样做能先验证：
        - dense + sparse 双路召回已经成立；
        - metadata filter 已经前置生效；
        - 命中结果能稳定回传给上层做父块回扩。
        """

        filters = filters or {}
        candidates = [
            record
            for record in _VECTOR_RECORDS.values()
            if self._match_filters(record, filters, chunk_types)
        ]
        if not candidates:
            return []

        dense_ranked = sorted(
            candidates,
            key=lambda record: self._dense_score(dense_vector, record.get("dense_vector") or []),
            reverse=True,
        )[: max(top_k * 3, top_k)]

        sparse_ranked = sorted(
            candidates,
            key=lambda record: self._sparse_score(sparse_vector, record.get("sparse_vector") or {}),
            reverse=True,
        )[: max(top_k * 3, top_k)]

        dense_rank_map = {item["chunk_uuid"]: index + 1 for index, item in enumerate(dense_ranked)}
        sparse_rank_map = {item["chunk_uuid"]: index + 1 for index, item in enumerate(sparse_ranked)}
        fused_candidates = {
            item["chunk_uuid"]: item
            for item in dense_ranked + sparse_ranked
        }

        fused_results: list[dict] = []
        for chunk_uuid, record in fused_candidates.items():
            dense_score = self._dense_score(dense_vector, record.get("dense_vector") or [])
            sparse_score = self._sparse_score(sparse_vector, record.get("sparse_vector") or {})
            dense_rank = dense_rank_map.get(chunk_uuid, 999999)
            sparse_rank = sparse_rank_map.get(chunk_uuid, 999999)
            fused_score = (
                0.45 * dense_score
                + 0.35 * sparse_score
                + 0.20 * ((1 / dense_rank) + (1 / sparse_rank))
            )
            fused_results.append(
                {
                    **record,
                    "score": round(fused_score, 6),
                    "dense_score": round(dense_score, 6),
                    "sparse_score": round(sparse_score, 6),
                }
            )

        fused_results.sort(key=lambda item: item["score"], reverse=True)
        return fused_results[:top_k]

    def healthcheck(self) -> dict:
        """返回当前向量存储状态。"""

        return {
            "provider": "milvus",
            "mode": "in_memory_fallback",
            "collection_name": self.collection_name,
            "healthy": True,
            "record_count": len(_VECTOR_RECORDS),
        }

    def _match_filters(self, record: dict, filters: dict, chunk_types: list[str] | None) -> bool:
        """执行最小 metadata filter。"""

        if chunk_types and record.get("chunk_type") not in chunk_types:
            return False

        for key, expected_value in filters.items():
            actual_value = record.get(key)

            if isinstance(expected_value, list):
                if isinstance(actual_value, list):
                    if not set(actual_value).intersection(expected_value):
                        return False
                else:
                    if actual_value not in expected_value:
                        return False
                continue

            if expected_value is None:
                continue

            if actual_value != expected_value:
                return False

        return True

    def _dense_score(self, query_vector: list[float], record_vector: list[float]) -> float:
        """计算 dense cosine 分数。"""

        if not query_vector or not record_vector:
            return 0.0

        length = min(len(query_vector), len(record_vector))
        dot_product = sum(query_vector[index] * record_vector[index] for index in range(length))
        query_norm = math.sqrt(sum(value * value for value in query_vector)) or 1.0
        record_norm = math.sqrt(sum(value * value for value in record_vector)) or 1.0
        return dot_product / (query_norm * record_norm)

    def _sparse_score(self, query_sparse: dict[str, float], record_sparse: dict[str, float]) -> float:
        """计算 sparse 重叠分数。"""

        if not query_sparse or not record_sparse:
            return 0.0
        return sum(query_sparse.get(token, 0.0) * record_sparse.get(token, 0.0) for token in query_sparse)
