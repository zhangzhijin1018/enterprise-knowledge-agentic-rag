"""向量存储抽象。

为什么需要向量存储抽象层：
- Service 层不应该直接依赖某个具体向量库 SDK；
- 后续从本地内存回退切到真实 Milvus，不应影响 ingestion / retrieval 业务代码；
- 向量库 schema、upsert、search、healthcheck 都应通过统一能力边界访问。

为什么本项目是 dense + sparse hybrid retrieval：
- dense 路负责语义召回；
- sparse 路负责关键词和编号精确匹配；
- 企业知识场景不能只做单路向量召回，否则制度条款号、表头关键词和设备编号容易丢失。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseVectorStore(ABC):
    """向量存储抽象基类。"""

    @abstractmethod
    def upsert_chunks(self, chunks: list[dict]) -> list[dict]:
        """批量写入向量库。"""

    @abstractmethod
    def delete_by_document_id(self, document_id: str) -> int:
        """按文档 ID 删除旧向量。"""

    @abstractmethod
    def search(
        self,
        dense_vector: list[float],
        sparse_vector: dict[str, float],
        top_k: int,
        filters: dict | None = None,
        chunk_types: list[str] | None = None,
    ) -> list[dict]:
        """执行最小 hybrid retrieval。"""

    @abstractmethod
    def healthcheck(self) -> dict:
        """返回向量存储健康信息。"""
