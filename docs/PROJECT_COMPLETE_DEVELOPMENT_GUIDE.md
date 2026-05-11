# 企业知识 Agentic RAG 平台 - 完整项目开发文档

> 本文档记录项目的完整开发计划、代码模式、文件清单和接续开发指南。
> 无论何时阅读本文档，都能快速了解项目现状并继续开发。

## 📋 目录

1. [项目概述](#1-项目概述)
2. [当前实现状态](#2-当前实现状态)
3. [技术架构图](#3-技术架构图)
4. [完整开发计划](#4-完整开发计划)
5. [代码模式与模板](#5-代码模式与模板)
6. [文件清单汇总](#6-文件清单汇总)
7. [参考项目映射](#7-参考项目映射)
8. [接续开发指南](#8-接续开发指南)
9. [验证清单](#9-验证清单)

---

## 1. 项目概述

### 1.1 项目名称

```
新疆能源集团知识与生产经营智能 Agent 平台
Enterprise Knowledge Agentic RAG Platform
```

### 1.2 项目定位

面向新疆能源集团业务场景的**生产级 Agentic RAG 平台**，覆盖：
- 集团制度政策问答
- 安全生产规程问答
- 设备检修与故障排查
- 新能源电站运维辅助
- 合同与合规审查 ⭐ 重点
- 经营数据分析 ⭐ 完整
- 项目建设资料问答
- 报告生成
- Human Review 人工复核
- Trace 审计
- Evaluation 评估

### 1.3 技术栈

| 层级 | 技术选型 |
|------|----------|
| 后端 | FastAPI + LangGraph |
| Agent 编排 | A2A 宏观调度 + LangGraph 微观执行 |
| LLM 接入 | OpenAI-compatible Gateway / 私有化大模型 |
| Embedding | BGE-M3 |
| Reranker | BGE-Reranker |
| 向量数据库 | Milvus |
| 元数据库 | PostgreSQL |
| 缓存与队列 | Redis + Celery |
| 文档解析 | LocalDocumentParser + PaddleOCR/PP-Structure |
| 前端 | React + TypeScript + TailwindCSS |

---

## 2. 当前实现状态

### 2.1 ✅ 已完成的模块

| 模块 | 状态 | 核心文件 |
|------|------|----------|
| **配置管理** | ✅ 完整 | `core/config/settings.py` |
| **文档解析** | ✅ 完整 | `core/tools/local/parser.py` (748行) |
| **OCR 适配** | ✅ 完整 | `core/tools/local/ocr.py` (369行) |
| **文档切片** | ✅ 完整 | `core/services/document_parse_service.py` |
| **向量入库** | ✅ 完整 | `core/services/document_ingestion_service.py` |
| **Analytics Agent** | ✅ 完整 | `core/agent/workflows/analytics/` (9节点 LangGraph) |
| **A2A 契约** | ✅ 基础 | `core/tools/a2a/contracts/models.py` |
| **SQL MCP** | ✅ 基础 | `core/tools/mcp/sql_mcp_server.py` |
| **Report MCP** | ✅ 基础 | `core/tools/mcp/report_mcp_server.py` |
| **数据库模型** | ✅ 基础 | `core/database/models/` |
| **Repository 层** | ✅ 基础 | `core/repositories/` |
| **Service 层** | ✅ 基础 | `core/services/` |

### 2.2 🔲 待完成的模块

| 模块 | 优先级 | 说明 |
|------|--------|------|
| **RAG 检索链路** | P0 | Hybrid Search + Rerank |
| **RAG Agent** | P0 | LangGraph 微工作流 |
| **合同审查 Agent** | P0 | 条款抽取 + 风险识别 |
| **A2A Redis Streams** | P1 | 消息总线 |
| **Human Review** | P1 | 审核管理 |
| **前端页面** | P2 | React SPA |
| **Evaluation** | P3 | 评估模块 |

### 2.3 📊 文档处理能力（已完整）

你的项目文档处理能力**已经超过**参考项目 `integrated_qa_system`：

```
文档解析路线：
├── docx      → python-docx 原生解析（段落 + 表格）
├── PDF 文本  → PyMuPDF + pdfplumber（文本 + 表格）
├── PDF 扫描  → PaddleOCR / PP-Structure OCR
├── 图片      → PaddleOCR / PP-Structure OCR
└── txt/md   → 文本解析

切片策略：
├── 结构优先 + 固定窗口回退
├── 父块 (parent_text) - 上下文完整
├── 子块 (child_text) - 精准检索
├── 表格父块 (table_parent) - 完整表格
├── 表格摘要 (table_summary) - 快速概览
└── 跨页表格合并
```

---

## 3. 技术架构图

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              用户请求层                                      │
│   ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│   │ 智能问答 │  │经营分析 │  │合同审查 │  │报告生成 │  │人工复核 │        │
│   └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘        │
└────────┼───────────┼───────────┼───────────┼───────────┼──────────────────┘
         │           │           │           │           │
         ▼           ▼           ▼           ▼           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          API Gateway (FastAPI)                               │
│                         /api/v1/chat, /analytics, /contract...              │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         │ A2A                 │ A2A                 │ A2A
         ▼                     ▼                     ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   RAG Agent     │  │ Analytics Agent │  │ Contract Agent  │
│  (LangGraph)    │  │  (LangGraph)    │  │  (LangGraph)    │
│   ⭐ 待开发      │  │   ✅ 已完成      │  │   ⭐ 待开发      │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  RAG MCP        │  │   SQL MCP       │  │  Contract MCP   │
│  (检索)         │  │  (查询)         │  │  (条款/风险)    │
│   ⭐ 待开发      │  │   ✅ 基础       │  │   ⭐ 待开发      │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│    Milvus       │  │   PostgreSQL    │  │   知识库        │
│  (向量检索)     │  │  (经营数据)     │  │  (合同模板)     │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

### 3.2 A2A + LangGraph 混合架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    A2A 宏观调度层 (Supervisor)                    │
│  - 意图理解、任务路由                                            │
│  - 跨 Agent 协调                                                │
│  - 状态聚合                                                      │
│  - Redis Streams 消息总线 (待实现)                               │
└─────────────────────────────┬───────────────────────────────────┘
                              │ A2A
┌─────────────────────────────┼───────────────────────────────────┐
│                    LangGraph 微观执行层                          │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  RAG Agent  │  │Analytics Agent│  │Contract Agent│          │
│  │              │  │              │  │              │          │
│  │ START        │  │ START        │  │ START        │          │
│  │   ↓          │  │   ↓          │  │   ↓          │          │
│  │ UNDERSTAND   │  │ ENTRY        │  │ UPLOAD       │          │
│  │   ↓          │  │   ↓          │  │   ↓          │          │
│  │ RETRIEVE     │  │ PLAN         │  │ PARSE        │          │
│  │   ↓          │  │   ↓          │  │   ↓          │          │
│  │ RERANK       │  │ BUILD_SQL    │  │ EXTRACT      │          │
│  │   ↓          │  │   ↓          │  │   ↓          │          │
│  │ GENERATE     │  │ EXECUTE_SQL  │  │ COMPARE      │          │
│  │   ↓          │  │   ↓          │  │   ↓          │          │
│  │ EVALUATE     │  │ GENERATE     │  │ IDENTIFY     │          │
│  │   ↓          │  │   ↓          │  │   ↓          │          │
│  │ FINISH       │  │ FINISH       │  │ CLASSIFY     │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

### 3.3 RAG 检索链路

```
用户查询
    │
    ▼
┌───────────────────┐
│  Query Rewrite    │ ← 可选：查询改写
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐     ┌───────────────────┐
│  Dense Retrieval  │     │  Sparse Retrieval │
│  (BGE-M3)         │     │  (BGE-M3)         │
└─────────┬─────────┘     └─────────┬─────────┘
          │                          │
          ▼                          ▼
┌───────────────────────────────────────────┐
│           Hybrid Search (Milvus)            │
│           分数融合：dense * 0.7 + sparse * 0.3
└───────────────────┬───────────────────────┘
                    │
                    ▼
┌───────────────────┐
│     Rerank       │ ← BGE-Reranker
│  (重排序 Top-K)   │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  Context Builder  │ ← 构造检索上下文
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│   LLM Generate   │ ← 生成答案
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  Citation Builder│ ← 生成引用
└───────────────────┘
```

---

## 4. 完整开发计划

### 4.1 开发阶段总览

| 阶段 | 名称 | 优先级 | 文件数 | 依赖 |
|------|------|--------|--------|------|
| **阶段 1** | RAG 检索链路 | P0 | ~8 | 现有 vectorstore |
| **阶段 2** | RAG Agent | P0 | ~10 | 阶段 1 |
| **阶段 3** | 合同审查 Agent | P0 | ~15 | 现有 parser |
| **阶段 4** | A2A Redis Streams | P1 | ~6 | 现有 A2A |
| **阶段 5** | Human Review | P1 | ~8 | 阶段 2/3 |
| **阶段 6** | 前端页面 | P2 | ~15 | 阶段 1-5 |
| **阶段 7** | Evaluation | P3 | ~5 | 阶段 1-3 |

---

### 阶段 1：RAG 检索链路

#### 目标
完成混合检索 + Rerank 链路，与现有文档解析/入库闭环。

#### 目录结构
```
core/rag/
├── retrieval/
│   ├── __init__.py
│   ├── dense_retriever.py       # [新建] Dense 检索
│   ├── sparse_retriever.py       # [新建] Sparse 检索
│   ├── hybrid_search.py          # [新建] 混合检索编排
│   └── reranker.py              # [新建] BGE-Reranker 封装
│
├── retrieval_chain.py           # [新建] 检索链路编排
│
└── citations/
    └── builder.py               # [新建] 引用构建器
```

#### 核心代码模式

**1. dense_retriever.py**
```python
"""Dense 向量检索器。

基于 BGE-M3 Dense Vector 的精确检索。
"""

from typing import Any

from core.vectorstore.base import BaseVectorStore
from core.vectorstore.milvus_store import MilvusVectorStore


class DenseRetriever:
    """Dense 向量检索器。

    职责：
    - 将查询文本转换为 Dense 向量
    - 在 Milvus 中执行向量相似度搜索
    - 返回检索结果和分数
    """

    def __init__(
        self,
        embedding_gateway: Any,  # EmbeddingGateway
        vector_store: BaseVectorStore,
        top_k: int = 10,
    ) -> None:
        self.embedding_gateway = embedding_gateway
        self.vector_store = vector_store
        self.top_k = top_k

    def retrieve(
        self,
        query_text: str,
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> list[dict]:
        """执行 Dense 检索。

        Args:
            query_text: 查询文本
            filters: 元数据过滤条件
            top_k: 返回数量

        Returns:
            检索结果列表，每项包含 chunk_uuid, content, score 等
        """
        # 1. 生成 query 向量
        query_embedding = self.embedding_gateway.embed_query(query_text)
        dense_vector = query_embedding["dense_vector"]

        # 2. 执行向量检索
        search_top_k = top_k or self.top_k
        results = self.vector_store.search(
            query_vector=dense_vector,
            top_k=search_top_k,
            filters=filters,
        )

        # 3. 格式化结果
        return [
            {
                "chunk_uuid": hit["chunk_uuid"],
                "content": hit["content"],
                "score": hit["score"],
                "metadata": hit.get("metadata", {}),
            }
            for hit in results
        ]
```

**2. sparse_retriever.py**
```python
"""Sparse 向量检索器。

基于 BGE-M3 Sparse Vector 的关键词检索。
"""

from typing import Any

from core.vectorstore.milvus_store import MilvusVectorStore


class SparseRetriever:
    """Sparse 向量检索器。

    职责：
    - 将查询文本转换为 Sparse 向量（词权重）
    - 在 Milvus 中执行稀疏向量搜索
    - 返回检索结果和分数
    """

    def __init__(
        self,
        embedding_gateway: Any,
        vector_store: MilvusVectorStore,
        top_k: int = 20,
    ) -> None:
        self.embedding_gateway = embedding_gateway
        self.vector_store = vector_store
        self.top_k = top_k

    def retrieve(
        self,
        query_text: str,
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> list[dict]:
        """执行 Sparse 检索。

        Args:
            query_text: 查询文本
            filters: 元数据过滤条件
            top_k: 返回数量

        Returns:
            检索结果列表
        """
        # 1. 生成 Sparse 向量
        query_embedding = self.embedding_gateway.embed_query(query_text)
        sparse_vector = query_embedding["sparse_vector"]

        # 2. 执行稀疏向量检索
        search_top_k = top_k or self.top_k
        results = self.vector_store.search_sparse(
            sparse_vector=sparse_vector,
            top_k=search_top_k,
            filters=filters,
        )

        return results
```

**3. hybrid_search.py**
```python
"""混合检索编排器。

整合 Dense + Sparse 检索，通过分数融合返回最优结果。
"""

from typing import Any

from core.rag.retrieval.dense_retriever import DenseRetriever
from core.rag.retrieval.sparse_retriever import SparseRetriever


class HybridSearch:
    """混合检索编排器。

    职责：
    - 并行执行 Dense 和 Sparse 检索
    - 通过 RRF 或加权融合合并结果
    - 去重和分数归一化
    """

    # Dense 和 Sparse 的融合权重
    DENSE_WEIGHT = 0.7
    SPARSE_WEIGHT = 0.3

    def __init__(
        self,
        dense_retriever: DenseRetriever,
        sparse_retriever: SparseRetriever,
        fusion_method: str = "weighted",  # weighted | rrf
    ) -> None:
        self.dense_retriever = dense_retriever
        self.sparse_retriever = sparse_retriever
        self.fusion_method = fusion_method

    def search(
        self,
        query_text: str,
        filters: dict[str, Any] | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        """执行混合检索。

        Args:
            query_text: 查询文本
            filters: 元数据过滤条件
            top_k: 返回数量

        Returns:
            融合后的检索结果
        """
        # 1. 并行执行 Dense 和 Sparse 检索
        dense_results = self.dense_retriever.retrieve(
            query_text=query_text,
            filters=filters,
            top_k=top_k * 2,  # 多检索一些用于融合
        )
        sparse_results = self.sparse_retriever.retrieve(
            query_text=query_text,
            filters=filters,
            top_k=top_k * 2,
        )

        # 2. 分数融合
        if self.fusion_method == "weighted":
            fused_results = self._weighted_fusion(dense_results, sparse_results)
        else:
            fused_results = self._rrf_fusion(dense_results, sparse_results)

        # 3. 返回 Top-K
        return fused_results[:top_k]

    def _weighted_fusion(
        self,
        dense_results: list[dict],
        sparse_results: list[dict],
    ) -> list[dict]:
        """加权分数融合。"""
        # 构建 score map
        score_map: dict[str, dict] = {}

        for item in dense_results:
            chunk_uuid = item["chunk_uuid"]
            score_map[chunk_uuid] = {
                "chunk_uuid": chunk_uuid,
                "content": item["content"],
                "metadata": item.get("metadata", {}),
                "dense_score": item["score"],
                "sparse_score": 0.0,
                "fused_score": item["score"] * self.DENSE_WEIGHT,
            }

        for item in sparse_results:
            chunk_uuid = item["chunk_uuid"]
            if chunk_uuid in score_map:
                score_map[chunk_uuid]["sparse_score"] = item["score"]
                score_map[chunk_uuid]["fused_score"] = (
                    score_map[chunk_uuid]["dense_score"] * self.DENSE_WEIGHT +
                    item["score"] * self.SPARSE_WEIGHT
                )
            else:
                score_map[chunk_uuid] = {
                    "chunk_uuid": chunk_uuid,
                    "content": item["content"],
                    "metadata": item.get("metadata", {}),
                    "dense_score": 0.0,
                    "sparse_score": item["score"],
                    "fused_score": item["score"] * self.SPARSE_WEIGHT,
                }

        # 排序
        sorted_results = sorted(
            score_map.values(),
            key=lambda x: x["fused_score"],
            reverse=True,
        )

        # 归一化分数
        max_score = sorted_results[0]["fused_score"] if sorted_results else 1.0
        for item in sorted_results:
            item["score"] = item["fused_score"] / max_score

        return sorted_results

    def _rrf_fusion(
        self,
        dense_results: list[dict],
        sparse_results: list[dict],
        k: int = 60,
    ) -> list[dict]:
        """RRF (Reciprocal Rank Fusion) 融合。"""
        rrf_scores: dict[str, float] = {}

        for rank, item in enumerate(dense_results):
            chunk_uuid = item["chunk_uuid"]
            rrf_scores[chunk_uuid] = rrf_scores.get(chunk_uuid, 0) + 1 / (k + rank + 1)
            # 补充其他字段
            if "content" not in rrf_scores:
                rrf_scores[f"{chunk_uuid}_content"] = item["content"]
                rrf_scores[f"{chunk_uuid}_metadata"] = item.get("metadata", {})

        for rank, item in enumerate(sparse_results):
            chunk_uuid = item["chunk_uuid"]
            rrf_scores[chunk_uuid] = rrf_scores.get(chunk_uuid, 0) + 1 / (k + rank + 1)

        # 构建结果
        results = []
        for chunk_uuid in rrf_scores:
            if "_content" not in chunk_uuid:
                results.append({
                    "chunk_uuid": chunk_uuid,
                    "content": rrf_scores.get(f"{chunk_uuid}_content", ""),
                    "metadata": rrf_scores.get(f"{chunk_uuid}_metadata", {}),
                    "score": rrf_scores[chunk_uuid],
                })

        return sorted(results, key=lambda x: x["score"], reverse=True)
```

**4. reranker.py**
```python
"""BGE-Reranker 封装。

对初步检索结果进行重排序，提高相关性。
"""

from typing import Any


class Reranker:
    """BGE-Reranker 封装。

    职责：
    - 接收初步检索结果
    - 对 query-document 对进行相关性打分
    - 返回重排序后的结果
    """

    def __init__(
        self,
        reranker_model: str = "BAAI/bge-reranker-base",
        device: str = "cpu",
        top_n: int = 5,
    ) -> None:
        self.reranker_model = reranker_model
        self.device = device
        self.top_n = top_n
        self._model: Any = None

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[dict]:
        """对文档进行重排序。

        Args:
            query: 查询文本
            documents: 文档内容列表
            top_n: 返回数量

        Returns:
            重排序后的结果，包含 chunk_uuid, content, score
        """
        if not documents:
            return []

        top_k = top_n or self.top_n

        # 懒加载模型
        if self._model is None:
            self._model = self._load_model()

        # 构建 query-document pairs
        pairs = [[query, doc] for doc in documents]

        # 执行 rerank
        scores = self._model.compute_score(pairs)

        # 按分数排序
        ranked = sorted(
            zip(documents, scores),
            key=lambda x: x[1],
            reverse=True,
        )

        return [
            {
                "content": doc,
                "score": score,
            }
            for doc, score in ranked[:top_k]
        ]

    def _load_model(self) -> Any:
        """懒加载 Reranker 模型。"""
        try:
            from sentence_transformers import CrossEncoder
            return CrossEncoder(
                self.reranker_model,
                device=self.device,
            )
        except ImportError:
            # 如果没有安装，返回 None
            return None
```

**5. retrieval_chain.py**
```python
"""RAG 检索链路编排器。

整合混合检索 + Rerank + 上下文构造。
"""

from typing import Any

from core.rag.retrieval.hybrid_search import HybridSearch
from core.rag.retrieval.reranker import Reranker
from core.rag.citations.builder import CitationBuilder


class RetrievalChain:
    """RAG 检索链路编排器。

    职责：
    - 执行混合检索
    - 对结果进行 Rerank
    - 构造检索上下文
    - 生成引用信息
    """

    def __init__(
        self,
        hybrid_search: HybridSearch,
        reranker: Reranker,
        citation_builder: CitationBuilder,
        retrieve_top_k: int = 20,
        rerank_top_k: int = 5,
    ) -> None:
        self.hybrid_search = hybrid_search
        self.reranker = reranker
        self.citation_builder = citation_builder
        self.retrieve_top_k = retrieve_top_k
        self.rerank_top_k = rerank_top_k

    def retrieve(
        self,
        query_text: str,
        filters: dict[str, Any] | None = None,
        user_context: Any | None = None,
    ) -> dict:
        """执行完整检索链路。

        Args:
            query_text: 查询文本
            filters: 元数据过滤条件
            user_context: 用户上下文（用于权限过滤）

        Returns:
            {
                "chunks": [...],  # 检索到的 chunks
                "context": "...",  # 构造的上下文
                "citations": [...], # 引用信息
            }
        """
        # 1. 混合检索
        hybrid_results = self.hybrid_search.search(
            query_text=query_text,
            filters=filters,
            top_k=self.retrieve_top_k,
        )

        if not hybrid_results:
            return {
                "chunks": [],
                "context": "",
                "citations": [],
            }

        # 2. Rerank
        documents = [item["content"] for item in hybrid_results]
        reranked = self.reranker.rerank(
            query=query_text,
            documents=documents,
            top_n=self.rerank_top_k,
        )

        # 3. 合并 Rerank 结果
        reranked_map = {item["content"]: item["score"] for item in reranked}
        final_chunks = []
        for item in hybrid_results:
            if item["content"] in reranked_map:
                item["rerank_score"] = reranked_map[item["content"]]
                final_chunks.append(item)

        # 4. 构造上下文
        context = self._build_context(final_chunks)

        # 5. 生成引用
        citations = self.citation_builder.build_citations(final_chunks)

        return {
            "chunks": final_chunks,
            "context": context,
            "citations": citations,
        }

    def _build_context(self, chunks: list[dict]) -> str:
        """构造检索上下文。"""
        if not chunks:
            return ""

        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            section_title = chunk.get("metadata", {}).get("section_title", "")
            if section_title:
                context_parts.append(f"【文档{i}】{section_title}\n{chunk['content']}")
            else:
                context_parts.append(f"【文档{i}】\n{chunk['content']}")

        return "\n\n".join(context_parts)
```

**6. citations/builder.py**
```python
"""引用构建器。

生成答案中的引用标记。
"""

from typing import Any


class CitationBuilder:
    """引用构建器。

    职责：
    - 为每个 chunk 生成唯一引用 ID
    - 构造引用标记格式 [1], [2], ...
    - 生成引用详情列表
    """

    def __init__(self, citation_format: str = "bracket") -> None:
        """
        Args:
            citation_format: 引用格式，bracket= [1], numeric= 1.
        """
        self.citation_format = citation_format

    def build_citations(self, chunks: list[dict]) -> list[dict]:
        """为 chunks 生成引用信息。

        Args:
            chunks: 检索结果 chunks

        Returns:
            引用列表，每项包含 citation_id, chunk_uuid, metadata 等
        """
        citations = []
        for i, chunk in enumerate(chunks, 1):
            citation_id = self._format_citation_id(i)
            citations.append({
                "citation_id": citation_id,
                "chunk_uuid": chunk["chunk_uuid"],
                "content": chunk["content"],
                "score": chunk.get("score", 0),
                "metadata": chunk.get("metadata", {}),
                "section_title": chunk.get("metadata", {}).get("section_title"),
                "page_no": chunk.get("metadata", {}).get("page_start"),
            })
        return citations

    def _format_citation_id(self, index: int) -> str:
        """格式化引用 ID。"""
        if self.citation_format == "bracket":
            return f"[{index}]"
        elif self.citation_format == "numeric":
            return f"{index}."
        else:
            return f"[{index}]"

    def insert_citations(self, answer: str, citations: list[dict]) -> str:
        """在答案中插入引用标记。

        这个方法可以在答案生成后，由 LLM 或后处理调用，
        将引用标记插入到答案的对应位置。
        """
        # 当前实现为简单版本，实际可以更复杂
        # 例如：解析答案中的占位符，替换为具体引用
        return answer
```

---

### 阶段 2：RAG Agent

#### 目标
基于 RAG 检索链路，构建 LangGraph 微工作流，实现智能问答 Agent。

#### 目录结构
```
core/agent/workflows/rag/
├── __init__.py
├── state.py              # [新建] RAG State 定义
├── nodes.py              # [新建] RAG 节点集合
├── graph.py              # [新建] LangGraph StateGraph
└── prompts.py            # [新建] RAG Prompt 模板

core/agent/business_agents/
└── rag_agent.py          # [新建] RAG Agent 服务

apps/api/routers/
└── rag.py                # [新建] RAG API
```

#### 核心代码模式

**1. state.py**
```python
"""RAG Agent State 定义。

定义 RAG 问答流程中的状态结构。
"""

from typing import TypedDict


class RAGState(TypedDict, total=False):
    """RAG Agent 状态定义。

    字段说明：
    - run_id: 本次运行唯一 ID
    - user_id: 用户 ID
    - query: 用户原始问题
    - query_rewritten: 改写后的问题
    - filters: 检索过滤条件
    - retrieved_chunks: 检索结果
    - context: 构造的检索上下文
    - citations: 引用信息
    - answer: 生成的回答
    - need_clarification: 是否需要澄清
    - clarification_message: 澄清消息
    - status: 当前状态
    - error: 错误信息
    """

    # 链路标识
    run_id: str
    trace_id: str

    # 用户信息
    user_id: str
    user_role: str

    # 查询相关
    query: str
    query_rewritten: str | None
    filters: dict | None

    # 检索相关
    retrieved_chunks: list[dict]
    context: str
    citations: list[dict]

    # 生成相关
    answer: str
    answer_with_citations: str

    # 澄清相关
    need_clarification: bool
    clarification_message: str | None

    # 状态
    status: str  # understanding | retrieving | reranking | generating | evaluating | succeeded | failed | clarifying
    error: str | None


def initial_rag_state(
    run_id: str,
    trace_id: str,
    user_id: str,
    query: str,
    user_role: str = "user",
) -> RAGState:
    """初始化 RAG State。"""
    return RAGState(
        run_id=run_id,
        trace_id=trace_id,
        user_id=user_id,
        query=query,
        user_role=user_role,
        query_rewritten=None,
        filters=None,
        retrieved_chunks=[],
        context="",
        citations=[],
        answer="",
        answer_with_citations="",
        need_clarification=False,
        clarification_message=None,
        status="understanding",
        error=None,
    )
```

**2. nodes.py**
```python
"""RAG Agent 节点集合。

每个节点是一个独立的函数或异步函数，接收 state，返回 state 更新。
"""

import logging
from typing import Literal

from core.agent.workflows.rag.state import RAGState
from core.rag.retrieval_chain import RetrievalChain
from core.rag.citations.builder import CitationBuilder
from core.llm.gateway import LLMLiteGateway

logger = logging.getLogger(__name__)


class RAGWorkflowNodes:
    """RAG Agent 工作流节点集合。

    节点设计：
    - 每个节点职责单一
    - 节点之间通过 state 传递数据
    - 错误处理统一在节点内
    """

    def __init__(
        self,
        retrieval_chain: RetrievalChain,
        citation_builder: CitationBuilder,
        llm_gateway: LLMLiteGateway,
    ) -> None:
        self.retrieval_chain = retrieval_chain
        self.citation_builder = citation_builder
        self.llm_gateway = llm_gateway

    # ==================== 节点定义 ====================

    async def understand_query(self, state: RAGState) -> dict:
        """理解查询节点。

        职责：
        - 解析用户查询
        - 确定检索范围和过滤条件
        - 检查是否需要澄清
        """
        logger.info(f"[{state['run_id']}] 理解查询: {state['query']}")

        # 简单实现：直接使用原始 query
        # 后续可以扩展 query rewrite
        query_rewritten = state["query"]

        # TODO: 实现查询理解和澄清逻辑

        return {
            "query_rewritten": query_rewritten,
            "status": "retrieving",
        }

    async def retrieve(self, state: RAGState) -> dict:
        """检索节点。

        职责：
        - 执行混合检索
        - 检查检索结果数量
        """
        logger.info(f"[{state['run_id']}] 执行检索")

        try:
            result = self.retrieval_chain.retrieve(
                query_text=state["query_rewritten"] or state["query"],
                filters=state.get("filters"),
            )

            chunks = result["chunks"]

            if not chunks:
                return {
                    "retrieved_chunks": [],
                    "context": "",
                    "citations": [],
                    "status": "generating",
                    "answer": "知识库中未找到与您问题相关的内容。",
                }

            return {
                "retrieved_chunks": chunks,
                "context": result["context"],
                "citations": result["citations"],
                "status": "generating",
            }

        except Exception as e:
            logger.error(f"[{state['run_id']}] 检索失败: {e}")
            return {
                "status": "failed",
                "error": f"检索失败: {str(e)}",
            }

    async def generate_answer(self, state: RAGState) -> dict:
        """生成答案节点。

        职责：
        - 基于检索上下文生成答案
        - 添加引用标记
        """
        logger.info(f"[{state['run_id']}] 生成答案")

        if not state.get("context"):
            return {
                "answer": "抱歉，知识库中没有找到相关信息。",
                "answer_with_citations": "抱歉，知识库中没有找到相关信息。",
                "status": "succeeded",
            }

        try:
            # 构建 prompt
            prompt = self._build_answer_prompt(
                query=state["query"],
                context=state["context"],
            )

            # 调用 LLM
            response = await self.llm_gateway.agenerate(prompt)
            answer = response.content if hasattr(response, "content") else str(response)

            # 添加引用
            answer_with_citations = self._add_citations(
                answer=answer,
                citations=state.get("citations", []),
            )

            return {
                "answer": answer,
                "answer_with_citations": answer_with_citations,
                "status": "succeeded",
            }

        except Exception as e:
            logger.error(f"[{state['run_id']}] 生成答案失败: {e}")
            return {
                "status": "failed",
                "error": f"生成答案失败: {str(e)}",
            }

    async def evaluate_answer(self, state: RAGState) -> dict:
        """评估答案节点。

        职责：
        - 检查答案质量
        - 检查是否需要补充检索
        """
        logger.info(f"[{state['run_id']}] 评估答案")

        # 简单实现：直接返回成功
        # 后续可以扩展评估逻辑
        return {"status": "succeeded"}

    # ==================== 辅助方法 ====================

    def _build_answer_prompt(self, query: str, context: str) -> str:
        """构建答案生成 Prompt。"""
        return f"""你是一个企业知识问答助手。请根据以下检索到的文档内容，回答用户的问题。

要求：
1. 如果文档中有明确答案，请基于文档内容回答
2. 如果文档中没有相关信息，请明确说明"知识库中未找到相关信息"
3. 在回答时适当引用相关文档

检索到的文档：
---
{context}
---

用户问题：{query}

回答："""

    def _add_citations(self, answer: str, citations: list[dict]) -> str:
        """在答案中添加引用。"""
        if not citations:
            return answer

        citation_lines = []
        for cite in citations:
            section = cite.get("section_title", "")
            page = cite.get("page_no", "")
            source = f"文档"
            if section:
                source += f" - {section}"
            if page:
                source += f" (第{page}页)"

            citation_lines.append(
                f"{cite['citation_id']} {source}"
            )

        if citation_lines:
            return f"{answer}\n\n参考来源：\n" + "\n".join(citation_lines)

        return answer
```

**3. graph.py**
```python
"""RAG Agent LangGraph StateGraph。

定义 RAG 问答流程的状态图结构。
"""

from typing import Annotated
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from core.agent.workflows.rag.state import RAGState
from core.agent.workflows.rag.nodes import RAGWorkflowNodes


def create_rag_graph(
    nodes: RAGWorkflowNodes,
) -> StateGraph:
    """创建 RAG Agent StateGraph。

    状态流转：
    START → understand → retrieve → generate → evaluate → FINISH
                        ↓
                   (clarify if needed)
                        ↓
                        ...
    """
    graph = StateGraph(RAGState)

    # 添加节点
    graph.add_node("understand", nodes.understand_query)
    graph.add_node("retrieve", nodes.retrieve)
    graph.add_node("generate", nodes.generate_answer)
    graph.add_node("evaluate", nodes.evaluate_answer)

    # 设置入口节点
    graph.set_entry_point("understand")

    # 定义边
    graph.add_edge("understand", "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", "evaluate")
    graph.add_edge("evaluate", END)

    # 编译图
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


def run_rag_agent(
    graph: StateGraph,
    initial_state: RAGState,
) -> RAGState:
    """运行 RAG Agent。

    Args:
        graph: 编译后的 StateGraph
        initial_state: 初始状态

    Returns:
        最终状态
    """
    # 使用 thread_id 支持多轮对话
    thread_id = initial_state.get("run_id", "default")

    config = {"configurable": {"thread_id": thread_id}}

    result = graph.invoke(initial_state, config=config)

    return result
```

**4. prompts.py**
```python
"""RAG Agent Prompt 模板。"""

SYSTEM_PROMPT = """你是一个企业知识问答助手，名为"能源小智"。

你的职责是：
1. 基于知识库中的文档回答用户问题
2. 如果知识库中有明确答案，基于文档准确回答
3. 如果知识库中没有相关信息，明确告知用户
4. 在回答中适当引用参考文档

你的能力：
- 理解集团制度政策
- 了解安全生产规程
- 熟悉设备检修流程
- 掌握新能源运维知识

回答要求：
- 语言简洁、专业
- 引用文档时标注来源
- 不确定的内容不编造
"""

QUERY_UNDERSTANDING_PROMPT = """分析用户的问题，确定检索范围：

问题：{query}

请确定：
1. 涉及的业务领域（制度政策/安全生产/设备检修/新能源运维/其他）
2. 需要的过滤条件（部门/安全级别/有效期等）
3. 是否需要澄清

只返回 JSON 格式：{{"domain": "...", "filters": {{}}, "need_clarification": false, "clarification_message": ""}}"""

ANSWER_GENERATION_PROMPT = """基于以下检索到的文档内容，回答用户的问题。

检索到的文档：
---
{context}
---

用户问题：{query}

要求：
1. 如果文档中有明确答案，基于文档内容回答
2. 如果文档中没有相关信息，说明"知识库中未找到相关信息"
3. 在回答末尾列出参考来源

回答："""
```

---

### 阶段 3：合同审查 Agent（重点）

#### 目标
实现完整的合同审查流程：解析 → 条款抽取 → 模板比对 → 风险识别 → 报告生成。

#### 目录结构
```
core/contracts/
├── __init__.py
├── models.py               # [新建] 合同数据模型
├── extractor.py            # [新建] 条款抽取器
├── comparator.py           # [新建] 模板比对器
├── risk_identifier.py      # [新建] 风险识别器
└── report_generator.py      # [新建] 审查报告生成

core/agent/workflows/contract/
├── __init__.py
├── state.py                # [新建] Contract State
├── nodes.py                # [新建] 合同审查节点
├── graph.py                # [新建] LangGraph StateGraph
└── prompts.py              # [新建] 合同审查 Prompt

core/agent/business_agents/
└── contract_agent.py       # [新建] 合同审查 Agent

apps/api/routers/
└── contract.py             # [新建] 合同审查 API
```

#### 核心代码模式

**1. models.py**
```python
"""合同审查数据模型。

定义合同解析、条款抽取和风险识别的数据结构。
"""

from typing import TypedDict, Literal
from pydantic import BaseModel, Field
from datetime import datetime


class ContractParty(BaseModel):
    """合同当事人。"""
    name: str = Field(description="当事人名称")
    role: Literal["甲方", "乙方", "丙方", "丁方", "其他"] = Field(description="角色")
    entity_type: str | None = Field(default=None, description="主体类型（公司/个人）")
    address: str | None = Field(default=None, description="地址")
    contact: str | None = Field(default=None, description="联系方式")


class ContractClause(BaseModel):
    """合同条款。"""
    clause_id: str = Field(description="条款编号")
    clause_type: str = Field(description="条款类型（标的/价款/期限/违约责任等）")
    clause_title: str = Field(description="条款标题")
    clause_content: str = Field(description="条款内容原文")
    key_points: list[str] = Field(default_factory=list, description="关键要点")
    risk_indicators: list[str] = Field(default_factory=list, description="风险指标")


class ContractRisk(BaseModel):
    """合同风险。"""
    risk_id: str = Field(description="风险编号")
    risk_type: Literal["高风险", "中风险", "低风险", "提示"] = Field(description="风险类型")
    risk_category: str = Field(description="风险类别（霸王条款/模糊表述/违规条款/缺失条款）")
    risk_description: str = Field(description="风险描述")
    related_clause: str = Field(description="相关条款编号")
    suggestion: str = Field(description="修改建议")
    legal_basis: str | None = Field(default=None, description="法律依据")


class ContractReviewReport(BaseModel):
    """合同审查报告。"""
    report_id: str = Field(description="报告 ID")
    contract_id: str = Field(description="合同 ID")
    contract_name: str = Field(description="合同名称")
    contract_type: str = Field(description="合同类型")
    review_time: datetime = Field(description="审查时间")

    # 合同基本信息
    parties: list[ContractParty] = Field(description="当事人")
    contract_value: str | None = Field(default=None, description="合同金额")
    contract_period: str | None = Field(default=None, description="合同期限")

    # 审查结果
    overall_risk_level: Literal["高风险", "中风险", "低风险"] = Field(description="整体风险等级")
    risk_summary: str = Field(description="风险概要")
    risks: list[ContractRisk] = Field(default_factory=list, description="风险列表")
    key_concerns: list[str] = Field(default_factory=list, description="重点关注项")

    # 条款分析
    clauses: list[ContractClause] = Field(default_factory=list, description="抽取的条款")
    template_comparison: dict | None = Field(default=None, description="模板对比结果")

    # 建议
    suggestions: list[str] = Field(default_factory=list, description="修改建议")
    conclusion: str = Field(description="审查结论")


class ContractState(TypedDict, total=False):
    """合同审查 Agent 状态。"""

    # 链路标识
    run_id: str
    trace_id: str

    # 用户信息
    user_id: str
    user_role: str

    # 合同信息
    contract_id: str
    contract_file_id: str
    contract_name: str
    contract_type: str

    # 解析结果
    parsed_content: str
    document_blocks: list[dict]

    # 条款抽取
    extracted_clauses: list[dict]

    # 模板比对
    matched_template: dict | None
    template_differences: list[dict]

    # 风险识别
    identified_risks: list[dict]

    # 报告
    review_report: dict | None

    # 状态
    status: str  # upload | parsing | extracting | comparing | identifying | generating | succeeded | failed
    need_human_review: bool
    human_review_status: str | None  # pending | approved | rejected | revised
    error: str | None
```

**2. extractor.py**
```python
"""合同条款抽取器。

使用 LLM 从合同文本中抽取关键条款。
"""

import logging
from typing import Any

from core.llm.gateway import LLMLiteGateway

logger = logging.getLogger(__name__)


class ClauseExtractor:
    """合同条款抽取器。

    职责：
    - 解析合同文本结构
    - 识别合同类型
    - 抽取关键条款（标的、价款、期限、当事人、违约责任等）
    - 返回结构化条款列表
    """

    # 条款类型映射
    CLAUSE_TYPES = [
        "当事人信息",
        "标的条款",
        "价款条款",
        "履行期限",
        "履行地点",
        "履行方式",
        "质量标准",
        "验收标准",
        "保密条款",
        "知识产权",
        "违约责任",
        "争议解决",
        "合同变更",
        "合同解除",
        "其他条款",
    ]

    def __init__(self, llm_gateway: LLMLiteGateway) -> None:
        self.llm_gateway = llm_gateway

    async def extract_clauses(
        self,
        contract_text: str,
        contract_type: str | None = None,
    ) -> list[dict]:
        """从合同文本中抽取条款。

        Args:
            contract_text: 合同文本内容
            contract_type: 合同类型（采购合同/销售合同/服务合同等）

        Returns:
            条款列表
        """
        logger.info(f"开始抽取条款，合同类型: {contract_type}")

        # 构建 Prompt
        prompt = self._build_extraction_prompt(contract_text, contract_type)

        try:
            # 调用 LLM
            response = await self.llm_gateway.agenerate(prompt)

            # 解析响应
            clauses = self._parse_llm_response(response)

            logger.info(f"成功抽取 {len(clauses)} 个条款")
            return clauses

        except Exception as e:
            logger.error(f"条款抽取失败: {e}")
            raise

    def _build_extraction_prompt(
        self,
        contract_text: str,
        contract_type: str | None,
    ) -> str:
        """构建条款抽取 Prompt。"""
        contract_type_hint = f"合同类型：{contract_type}" if contract_type else "合同类型：未知"

        return f"""你是一个专业的合同审查助手。请从以下合同文本中抽取关键条款。

{contract_type_hint}

要求：
1. 识别并抽取所有关键条款
2. 对每个条款，标注条款类型
3. 提取条款的关键要点
4. 识别可能的风险指标

条款类型包括：
{', '.join(self.CLAUSE_TYPES)}

合同文本：
---
{contract_text[:8000]}  # 限制长度
---

请以 JSON 格式返回条款列表，每个条款包含：
- clause_id: 条款编号（如 "第1条"）
- clause_type: 条款类型
- clause_title: 条款标题
- clause_content: 条款原文
- key_points: 关键要点列表
- risk_indicators: 风险指标列表

返回格式：
{{"clauses": [...]}}"""

    def _parse_llm_response(self, response: Any) -> list[dict]:
        """解析 LLM 响应。"""
        content = response.content if hasattr(response, "content") else str(response)

        # 尝试提取 JSON
        import json
        import re

        # 查找 JSON 对象
        json_match = re.search(r'\{[^{}]*"clauses"[^{}]*\}', content, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return data.get("clauses", [])
            except json.JSONDecodeError:
                pass

        # 如果解析失败，返回空列表
        logger.warning(f"无法解析 LLM 响应: {content[:200]}")
        return []
```

**3. risk_identifier.py**
```python
"""合同风险识别器。

识别合同中的风险条款和风险点。
"""

import logging
from typing import Literal

from core.contracts.extractor import ClauseExtractor
from core.contracts.models import ContractRisk

logger = logging.getLogger(__name__)


class RiskIdentifier:
    """合同风险识别器。

    职责：
    - 分析条款中的风险指标
    - 识别风险类型和等级
    - 生成风险描述和修改建议
    """

    # 风险关键词映射
    RISK_KEYWORDS = {
        "高风险": [
            "无条件解除", "无限责任", "免除全部责任", "强制仲裁",
            "不得诉讼", "放弃抗辩", "单方解释权", "无条件赔偿",
        ],
        "中风险": [
            "违约金过高", "赔偿无上限", "单方变更", "限制权利",
            "不得转让", "保密范围过宽", "竞业限制过严",
        ],
        "低风险": [
            "建议明确", "建议补充", "可进一步细化", "建议增加",
        ],
    }

    # 风险类别
    RISK_CATEGORIES = [
        "霸王条款",      # 明显不公平的条款
        "模糊表述",      # 表述不明确可能引发争议
        "违规条款",      # 违反法律法规的条款
        "缺失条款",      # 应该约定但缺失的条款
        "不对等条款",    # 双方权利义务不对等
    ]

    def __init__(self, clause_extractor: ClauseExtractor) -> None:
        self.clause_extractor = clause_extractor

    def identify_risks(
        self,
        clauses: list[dict],
        contract_type: str | None = None,
    ) -> list[dict]:
        """识别合同风险。

        Args:
            clauses: 抽取的条款列表
            contract_type: 合同类型

        Returns:
            风险列表
        """
        logger.info(f"开始识别风险，共 {len(clauses)} 个条款")

        risks = []

        for clause in clauses:
            clause_risks = self._identify_clause_risks(clause, contract_type)
            risks.extend(clause_risks)

        # 排序：先高风险，后中风险，低风险
        risk_level_order = {"高风险": 0, "中风险": 1, "低风险": 2, "提示": 3}
        risks.sort(key=lambda x: (risk_level_order.get(x["risk_type"], 99), x["risk_id"]))

        logger.info(f"识别出 {len(risks)} 个风险点")
        return risks

    def _identify_clause_risks(
        self,
        clause: dict,
        contract_type: str | None,
    ) -> list[dict]:
        """识别单个条款的风险。"""
        risks = []
        clause_content = clause.get("clause_content", "")
        clause_id = clause.get("clause_id", "")
        clause_type = clause.get("clause_type", "")

        # 检查风险关键词
        risk_level, matched_keywords = self._check_risk_keywords(clause_content)

        if risk_level:
            risk = {
                "risk_id": f"R{len(risks) + 1}",
                "risk_type": risk_level,
                "risk_category": self._categorize_risk(matched_keywords),
                "risk_description": self._build_risk_description(
                    clause_content, matched_keywords, risk_level
                ),
                "related_clause": clause_id,
                "clause_type": clause_type,
                "suggestion": self._build_suggestion(matched_keywords, risk_level),
                "legal_basis": self._find_legal_basis(matched_keywords),
            }
            risks.append(risk)

        # 检查缺失条款
        missing = self._check_missing_clauses(clause, contract_type)
        for miss in missing:
            risks.append(miss)

        return risks

    def _check_risk_keywords(
        self,
        clause_content: str,
    ) -> tuple[Literal["高风险", "中风险", "低风险"] | None, list[str]]:
        """检查风险关键词。"""
        matched = []

        for level, keywords in self.RISK_KEYWORDS.items():
            for keyword in keywords:
                if keyword in clause_content:
                    matched.append(f"{keyword}({level})")
                    # 返回最高风险等级
                    if level == "高风险":
                        return "高风险", matched

        if matched:
            # 返回匹配到的最高等级
            if any("中风险" in m for m in matched):
                return "中风险", matched
            return "低风险", matched

        return None, []

    def _categorize_risk(self, matched_keywords: list[str]) -> str:
        """对风险进行分类。"""
        if any("无条件" in k or "单方" in k for k in matched_keywords):
            return "霸王条款"
        if any("模糊" in k or "无上限" in k for k in matched_keywords):
            return "模糊表述"
        if any("违规" in k for k in matched_keywords):
            return "违规条款"
        return "不对等条款"

    def _build_risk_description(
        self,
        clause_content: str,
        matched_keywords: list[str],
        risk_level: str,
    ) -> str:
        """构建风险描述。"""
        desc = f"该条款存在{risk_level}"

        if matched_keywords:
            keywords = [k.split("(")[0] for k in matched_keywords]
            desc += f"，涉及：{', '.join(keywords)}"

        desc += f"。条款内容：{clause_content[:200]}..."

        return desc

    def _build_suggestion(
        self,
        matched_keywords: list[str],
        risk_level: str,
    ) -> str:
        """生成修改建议。"""
        if risk_level == "高风险":
            return "建议删除或修改该条款，如必须保留请经法务部门审批。"
        elif risk_level == "中风险":
            return "建议与对方协商修改，明确责任范围和违约金额。"
        else:
            return "建议进一步明确条款表述，减少争议空间。"

    def _find_legal_basis(self, matched_keywords: list[str]) -> str | None:
        """查找相关法律依据。"""
        # 简化实现
        if any("违约金过高" in k for k in matched_keywords):
            return "《民法典》第五百八十五条：约定的违约金过分高于造成的损失的，法院或仲裁机构可以适当减少"
        if any("无限责任" in k for k in matched_keywords):
            return "《民法典》第三条：民事主体的人身权利、财产权利以及其他合法权益受法律保护"
        return None

    def _check_missing_clauses(
        self,
        clause: dict,
        contract_type: str | None,
    ) -> list[dict]:
        """检查缺失条款。"""
        # 简化实现
        return []
```

**4. nodes.py (Contract Workflow)**
```python
"""合同审查 Agent 节点集合。"""

import logging
from pathlib import Path

from core.contracts.extractor import ClauseExtractor
from core.contracts.risk_identifier import RiskIdentifier
from core.contracts.report_generator import ReportGenerator
from core.tools.local.parser import LocalDocumentParser
from core.agent.workflows.contract.state import ContractState

logger = logging.getLogger(__name__)


class ContractWorkflowNodes:
    """合同审查 Agent 工作流节点集合。"""

    def __init__(
        self,
        parser: LocalDocumentParser,
        clause_extractor: ClauseExtractor,
        risk_identifier: RiskIdentifier,
        report_generator: ReportGenerator,
    ) -> None:
        self.parser = parser
        self.clause_extractor = clause_extractor
        self.risk_identifier = risk_identifier
        self.report_generator = report_generator

    async def parse_contract(self, state: ContractState) -> dict:
        """解析合同文档。"""
        logger.info(f"[{state['run_id']}] 解析合同文档")

        contract_file_id = state.get("contract_file_id")
        if not contract_file_id:
            return {"status": "failed", "error": "缺少合同文件 ID"}

        try:
            # 获取文件路径（简化实现）
            file_path = Path(f"storage/uploads/{contract_file_id}")
            if not file_path.exists():
                return {"status": "failed", "error": "合同文件不存在"}

            # 解析文档
            blocks = self.parser.parse(file_path, file_path.suffix.lstrip("."))
            parsed_content = "\n".join(b.get("text", "") for b in blocks)

            return {
                "parsed_content": parsed_content,
                "document_blocks": blocks,
                "status": "extracting",
            }

        except Exception as e:
            logger.error(f"[{state['run_id']}] 合同解析失败: {e}")
            return {"status": "failed", "error": f"合同解析失败: {str(e)}"}

    async def extract_clauses(self, state: ContractState) -> dict:
        """抽取合同条款。"""
        logger.info(f"[{state['run_id']}] 抽取合同条款")

        try:
            clauses = await self.clause_extractor.extract_clauses(
                contract_text=state["parsed_content"],
                contract_type=state.get("contract_type"),
            )

            if not clauses:
                return {
                    "extracted_clauses": [],
                    "status": "failed",
                    "error": "未抽取到有效条款，请检查合同文件",
                }

            return {
                "extracted_clauses": clauses,
                "status": "comparing",
            }

        except Exception as e:
            logger.error(f"[{state['run_id']}] 条款抽取失败: {e}")
            return {"status": "failed", "error": f"条款抽取失败: {str(e)}"}

    async def compare_template(self, state: ContractState) -> dict:
        """比对合同模板。"""
        logger.info(f"[{state['run_id']}] 比对合同模板")

        # TODO: 实现模板比对逻辑
        # 从知识库检索标准模板
        # 对比差异

        return {
            "matched_template": None,
            "template_differences": [],
            "status": "identifying",
        }

    async def identify_risks(self, state: ContractState) -> dict:
        """识别合同风险。"""
        logger.info(f"[{state['run_id']}] 识别合同风险")

        try:
            risks = self.risk_identifier.identify_risks(
                clauses=state["extracted_clauses"],
                contract_type=state.get("contract_type"),
            )

            # 判断是否需要人工复核
            need_human_review = any(
                r.get("risk_type") == "高风险" for r in risks
            )

            return {
                "identified_risks": risks,
                "need_human_review": need_human_review,
                "status": "generating",
            }

        except Exception as e:
            logger.error(f"[{state['run_id']}] 风险识别失败: {e}")
            return {"status": "failed", "error": f"风险识别失败: {str(e)}"}

    async def generate_report(self, state: ContractState) -> dict:
        """生成审查报告。"""
        logger.info(f"[{state['run_id']}] 生成审查报告")

        try:
            report = self.report_generator.generate(
                contract_name=state.get("contract_name", ""),
                contract_type=state.get("contract_type", ""),
                clauses=state["extracted_clauses"],
                risks=state["identified_risks"],
                matched_template=state.get("matched_template"),
                template_differences=state.get("template_differences", []),
            )

            return {
                "review_report": report,
                "status": "succeeded" if not state.get("need_human_review") else "waiting_review",
            }

        except Exception as e:
            logger.error(f"[{state['run_id']}] 报告生成失败: {e}")
            return {"status": "failed", "error": f"报告生成失败: {str(e)}"}
```

**5. graph.py (Contract Workflow)**
```python
"""合同审查 Agent LangGraph StateGraph。"""

from langgraph.graph import StateGraph, END

from core.agent.workflows.contract.state import ContractState
from core.agent.workflows.contract.nodes import ContractWorkflowNodes


def create_contract_graph(
    nodes: ContractWorkflowNodes,
) -> StateGraph:
    """创建合同审查 Agent StateGraph。

    状态流转：
    START → parse → extract → compare → identify → generate → FINISH
                                                    ↓
                                              need_human_review?
                                                    ↓
                                         ┌─────────┴─────────┐
                                       true                false
                                         ↓                   ↓
                                    waiting_review       succeeded
                                         ↓
                                    human_review
                                         ↓
                                         END
    """
    graph = StateGraph(ContractState)

    # 添加节点
    graph.add_node("parse", nodes.parse_contract)
    graph.add_node("extract", nodes.extract_clauses)
    graph.add_node("compare", nodes.compare_template)
    graph.add_node("identify", nodes.identify_risks)
    graph.add_node("generate", nodes.generate_report)

    # 设置入口
    graph.set_entry_point("parse")

    # 定义条件边
    def should_wait_review(state: ContractState) -> str:
        if state.get("need_human_review"):
            return "waiting_review"
        return "succeeded"

    # 定义边
    graph.add_edge("parse", "extract")
    graph.add_edge("extract", "compare")
    graph.add_edge("compare", "identify")
    graph.add_edge("identify", "generate")

    # 条件边
    graph.add_conditional_edges(
        "generate",
        should_wait_review,
        {
            "waiting_review": END,  # 等待人工复核
            "succeeded": END,
        }
    )

    return graph.compile()
```

**6. prompts.py (Contract Workflow)**
```python
"""合同审查 Agent Prompt 模板。"""

SYSTEM_PROMPT = """你是一个专业的企业合同审查助手，名为"能源法务小助手"。

你的职责是：
1. 解析合同文本结构
2. 抽取关键条款（当事人、标的、价款、期限、违约责任等）
3. 识别合同风险点
4. 与标准模板进行比对
5. 生成审查报告

你的能力：
- 熟悉《民法典》合同编相关规定
- 了解企业合同管理规范
- 擅长识别不公平条款和风险点

审查要求：
- 严格按照法律法规和集团制度进行审查
- 对高风险条款必须标注并给出修改建议
- 保持客观公正，不偏袒任何一方

风险等级定义：
- 高风险：违反法律法规或存在明显不公平的条款
- 中风险：表述模糊或可能引发争议的条款
- 低风险：建议进一步明确或优化的条款
"""

CLAUSE_EXTRACTION_PROMPT = """从以下合同文本中抽取关键条款：

{contract_text}

要求：
1. 识别合同类型
2. 抽取所有条款，包括：
   - 当事人信息（名称、地址、联系方式）
   - 标的条款（合同标的、数量、质量）
   - 价款条款（金额、支付方式、支付时间）
   - 履行条款（期限、地点、方式）
   - 违约责任（违约金、赔偿范围）
   - 争议解决（仲裁、诉讼）
   - 其他重要条款
3. 对每个条款提取关键要点

返回 JSON 格式：{{"contract_type": "...", "clauses": [...]}}"""

RISK_IDENTIFICATION_PROMPT = """分析以下合同条款，识别风险点：

条款内容：
{clause_content}

条款类型：{clause_type}

风险关键词：
- 高风险：无条件解除、无限责任、免除全部责任、单方解释权
- 中风险：违约金过高、赔偿无上限、单方变更、限制权利
- 低风险：表述模糊、建议明确

请识别：
1. 是否存在上述风险关键词
2. 风险类型和等级
3. 风险描述
4. 修改建议
5. 相关法律依据（如有）"""
```

---

### 阶段 4：A2A Redis Streams

#### 目标
将 A2A 消息放到 Redis Streams，实现多 Worker 部署。

#### 目录结构
```
core/common/a2a/
├── __init__.py
├── redis_producer.py       # [新建] Redis Streams 生产者
└── redis_consumer.py       # [新建] Redis Streams 消费者

core/agent/supervisor/
├── intent_router.py         # [增强] 意图路由
├── delegation_controller.py # [增强] A2A 委托控制
└── result_aggregator.py    # [新建] 结果聚合
```

#### 核心代码模式

```python
"""Redis Streams A2A 消息生产者。"""

import json
import logging
from datetime import datetime
from typing import Any

import redis

from core.config.settings import get_settings

logger = logging.getLogger(__name__)


class A2ARedisProducer:
    """A2A Redis Streams 消息生产者。

    职责：
    - 将 TaskEnvelope 发送到 Redis Streams
    - 管理消息的生命周期
    - 提供消息状态查询
    """

    def __init__(self, redis_url: str | None = None) -> None:
        settings = get_settings()
        self.redis_url = redis_url or settings.redis_url
        self.stream_key_prefix = settings.redis_sse_stream_prefix

        self._client: redis.Redis | None = None

    @property
    def client(self) -> redis.Redis:
        """懒加载 Redis 客户端。"""
        if self._client is None:
            self._client = redis.from_url(
                self.redis_url,
                decode_responses=True,
            )
        return self._client

    def send_task(
        self,
        task_envelope: dict,
        target_agent: str,
    ) -> str:
        """发送任务到 Redis Streams。

        Args:
            task_envelope: 任务信封
            target_agent: 目标 Agent

        Returns:
            消息 ID
        """
        stream_key = f"{self.stream_key_prefix}:{target_agent}"

        message = {
            "task_envelope": json.dumps(task_envelope),
            "created_at": datetime.utcnow().isoformat(),
            "status": "pending",
        }

        message_id = self.client.xadd(stream_key, message)

        logger.info(f"任务已发送到 {stream_key}，消息 ID: {message_id}")

        return message_id

    def get_task_status(self, target_agent: str, message_id: str) -> dict | None:
        """查询任务状态。"""
        stream_key = f"{self.stream_key_prefix}:{target_agent}"

        result = self.client.xrange(stream_key, min=message_id, max=message_id)

        if result:
            _, data = result[0]
            return {
                "message_id": message_id,
                "status": data.get("status"),
                "created_at": data.get("created_at"),
            }

        return None


class A2ARedisConsumer:
    """A2A Redis Streams 消息消费者。

    职责：
    - 从 Redis Streams 消费任务
    - 调用目标 Agent 处理
    - 更新任务状态
    """

    def __init__(self, redis_url: str | None = None) -> None:
        settings = get_settings()
        self.redis_url = redis_url or settings.redis_url
        self.stream_key_prefix = settings.redis_sse_stream_prefix

        self._client: redis.Redis | None = None

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(
                self.redis_url,
                decode_responses=True,
            )
        return self._client

    def consume(
        self,
        agent_name: str,
        handler: callable,
        block_ms: int = 5000,
    ) -> None:
        """消费任务。

        Args:
            agent_name: Agent 名称
            handler: 处理函数，接收 task_envelope，返回 result
            block_ms: 阻塞等待时间
        """
        stream_key = f"{self.stream_key_prefix}:{agent_name}"
        consumer_group = f"{agent_name}_cg"
        consumer_name = f"{agent_name}_consumer_{os.getpid()}"

        # 确保消费者组存在
        try:
            self.client.xgroup_create(stream_key, consumer_group, id="0", mkstream=True)
        except redis.ResponseError:
            # 组已存在
            pass

        while True:
            try:
                # 阻塞读取新消息
                messages = self.client.xreadgroup(
                    consumer_group,
                    consumer_name,
                    {stream_key: ">"},  # 只读新消息
                    count=1,
                    block=block_ms,
                )

                if not messages:
                    continue

                for stream, msg_list in messages:
                    for message_id, data in msg_list:
                        task_envelope = json.loads(data["task_envelope"])

                        logger.info(f"收到任务: {message_id}")

                        try:
                            # 处理任务
                            result = handler(task_envelope)

                            # 更新状态
                            self.client.xadd(
                                stream_key,
                                {
                                    "status": "completed",
                                    "result": json.dumps(result),
                                    "completed_at": datetime.utcnow().isoformat(),
                                },
                            )

                            # 确认消息
                            self.client.xack(stream_key, consumer_group, message_id)

                        except Exception as e:
                            logger.error(f"任务处理失败: {e}")
                            self.client.xadd(
                                stream_key,
                                {
                                    "status": "failed",
                                    "error": str(e),
                                    "failed_at": datetime.utcnow().isoformat(),
                                },
                            )
                            self.client.xack(stream_key, consumer_group, message_id)

            except Exception as e:
                logger.error(f"消费循环异常: {e}")
                time.sleep(5)  # 等待后重试
```

---

### 阶段 5：Human Review

#### 目录结构
```
core/review/
├── __init__.py
├── review_manager.py       # [新建] 审核管理器
├── risk_classifier.py      # [新建] 风险分类器
└── models.py               # [新建] 审核数据模型

apps/api/routers/
└── review.py                # [新建] 审核 API
```

#### 核心代码模式

```python
"""审核管理器。"""

from typing import Literal
from datetime import datetime
from pydantic import BaseModel, Field


class ReviewTask(BaseModel):
    """审核任务。"""
    review_id: str
    run_id: str
    task_type: Literal["contract_review", "business_analysis", "report_generation"]
    risk_level: Literal["low", "medium", "high", "critical"]
    content: dict  # 待审核内容
    created_at: datetime
    reviewer_id: str | None = None
    review_status: Literal["pending", "approved", "rejected", "revised"] = "pending"
    review_comment: str | None = None
    reviewed_at: datetime | None = None


class ReviewManager:
    """审核管理器。

    职责：
    - 创建审核任务
    - 分配审核人
    - 管理审核流程
    - 记录审核结果
    """

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def create_review_task(
        self,
        run_id: str,
        task_type: str,
        risk_level: str,
        content: dict,
    ) -> ReviewTask:
        """创建审核任务。"""
        review_id = f"review_{uuid.uuid4().hex[:12]}"

        task = ReviewTask(
            review_id=review_id,
            run_id=run_id,
            task_type=task_type,
            risk_level=risk_level,
            content=content,
            created_at=datetime.utcnow(),
        )

        self.repository.save_review_task(task)

        return task

    def submit_review(
        self,
        review_id: str,
        reviewer_id: str,
        decision: Literal["approved", "rejected", "revised"],
        comment: str | None = None,
    ) -> ReviewTask:
        """提交审核结果。"""
        task = self.repository.get_review_task(review_id)

        if task is None:
            raise ValueError(f"审核任务不存在: {review_id}")

        if task.review_status != "pending":
            raise ValueError(f"审核任务已处理: {review_id}")

        task.reviewer_id = reviewer_id
        task.review_status = decision
        task.review_comment = comment
        task.reviewed_at = datetime.utcnow()

        self.repository.update_review_task(task)

        return task

    def get_pending_reviews(
        self,
        reviewer_id: str | None = None,
    ) -> list[ReviewTask]:
        """获取待审核任务。"""
        return self.repository.list_pending_reviews(reviewer_id)
```

---

### 阶段 6：前端页面

#### 目录结构
```
apps/web/
├── src/
│   ├── components/
│   │   ├── ChatWindow.tsx      # 对话窗口
│   │   ├── AgentCard.tsx      # Agent 卡片
│   │   ├── ReviewPanel.tsx    # 审核面板
│   │   └── CitationBox.tsx    # 引用框
│   │
│   ├── pages/
│   │   ├── Home.tsx           # 首页
│   │   ├── Chat.tsx           # 智能问答
│   │   ├── Analytics.tsx      # 经营分析
│   │   ├── Contract.tsx        # 合同审查
│   │   └── Review.tsx         # 人工复核
│   │
│   └── services/
│       └── api.ts              # API 服务
│
└── package.json
```

---

### 阶段 7：Evaluation

#### 目录结构
```
core/evaluation/
├── __init__.py
├── rag_evaluator.py           # RAG 评估器
├── agent_evaluator.py         # Agent 评估器
└── report_generator.py          # 评估报告生成
```

---

## 5. 代码模式与模板

### 5.1 LangGraph 节点函数模板

```python
async def node_function(state: YourState) -> dict:
    """节点函数模板。

    职责：描述节点做什么

    Args:
        state: 当前状态

    Returns:
        状态更新字典
    """
    logger.info(f"[{state['run_id']}] 节点名称")

    try:
        # 业务逻辑
        result = await some_service.do_something(state["input"])

        return {
            "status": "next_status",
            "output_field": result,
        }
    except Exception as e:
        logger.error(f"[{state['run_id']}] 节点失败: {e}")
        return {
            "status": "failed",
            "error": str(e),
        }
```

### 5.2 Service 层模板

```python
class YourService:
    """服务类模板。

    职责：描述服务职责
    """

    def __init__(
        self,
        dependency1: DependencyType,
        dependency2: DependencyType,
    ) -> None:
        self.dependency1 = dependency1
        self.dependency2 = dependency2

    def do_something(self, input_data: dict) -> dict:
        """业务方法。

        Args:
            input_data: 输入数据

        Returns:
            处理结果
        """
        # 1. 参数校验
        self._validate_input(input_data)

        # 2. 业务处理
        result = self._process(input_data)

        # 3. 返回结果
        return result
```

### 5.3 API Router 模板

```python
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

router = APIRouter(prefix="/your_module", tags=["your_module"])


class YourRequest(BaseModel):
    """请求模型。"""
    field1: str
    field2: int | None = None


@router.post("/action")
async def your_action(
    request: Request,
    body: YourRequest,
    service: YourService = Depends(get_your_service),
) -> dict:
    """接口描述。

    Args:
        request: FastAPI Request
        body: 请求体
        service: 注入的服务

    Returns:
        统一响应
    """
    result = service.do_something(body.model_dump())
    return build_success_response(request=request, data=result)
```

---

## 6. 文件清单汇总

### 6.1 阶段 1：RAG 检索链路 (~8 个文件)

| 文件路径 | 说明 | 复用 |
|----------|------|------|
| `core/rag/retrieval/__init__.py` | 模块初始化 | - |
| `core/rag/retrieval/dense_retriever.py` | Dense 检索 | vectorstore |
| `core/rag/retrieval/sparse_retriever.py` | Sparse 检索 | vectorstore |
| `core/rag/retrieval/hybrid_search.py` | 混合检索 | - |
| `core/rag/retrieval/reranker.py` | 重排序 | - |
| `core/rag/retrieval_chain.py` | 检索链路编排 | retrieval_service |
| `core/rag/citations/builder.py` | 引用构建器 | - |

### 6.2 阶段 2：RAG Agent (~10 个文件)

| 文件路径 | 说明 | 复用 |
|----------|------|------|
| `core/agent/workflows/rag/__init__.py` | 模块初始化 | - |
| `core/agent/workflows/rag/state.py` | State 定义 | analytics/state |
| `core/agent/workflows/rag/nodes.py` | 节点集合 | analytics/nodes |
| `core/agent/workflows/rag/graph.py` | StateGraph | analytics/graph |
| `core/agent/workflows/rag/prompts.py` | Prompt 模板 | - |
| `core/agent/business_agents/rag_agent.py` | RAG Agent | - |
| `apps/api/routers/rag.py` | RAG API | analytics.py |

### 6.3 阶段 3：合同审查 Agent (~15 个文件)

| 文件路径 | 说明 | 复用 |
|----------|------|------|
| `core/contracts/__init__.py` | 模块初始化 | - |
| `core/contracts/models.py` | 数据模型 | - |
| `core/contracts/extractor.py` | 条款抽取器 | - |
| `core/contracts/comparator.py` | 模板比对器 | - |
| `core/contracts/risk_identifier.py` | 风险识别器 | - |
| `core/contracts/report_generator.py` | 报告生成 | analytics/report |
| `core/agent/workflows/contract/__init__.py` | 模块初始化 | - |
| `core/agent/workflows/contract/state.py` | State 定义 | rag/state |
| `core/agent/workflows/contract/nodes.py` | 节点集合 | rag/nodes |
| `core/agent/workflows/contract/graph.py` | StateGraph | rag/graph |
| `core/agent/workflows/contract/prompts.py` | Prompt 模板 | - |
| `core/agent/business_agents/contract_agent.py` | 合同 Agent | rag_agent |
| `apps/api/routers/contract.py` | 合同 API | rag.py |

### 6.4 阶段 4：A2A Redis Streams (~6 个文件)

| 文件路径 | 说明 | 复用 |
|----------|------|------|
| `core/common/a2a/__init__.py` | 模块初始化 | - |
| `core/common/a2a/redis_producer.py` | 生产者 | sse_progress |
| `core/common/a2a/redis_consumer.py` | 消费者 | - |
| `core/agent/supervisor/result_aggregator.py` | 结果聚合 | - |

### 6.5 阶段 5：Human Review (~8 个文件)

| 文件路径 | 说明 | 复用 |
|----------|------|------|
| `core/review/__init__.py` | 模块初始化 | - |
| `core/review/models.py` | 数据模型 | - |
| `core/review/review_manager.py` | 审核管理器 | - |
| `core/review/risk_classifier.py` | 风险分类器 | - |
| `apps/api/routers/review.py` | 审核 API | - |

### 6.6 阶段 6：前端页面 (~15 个文件)

| 文件路径 | 说明 |
|----------|------|
| `apps/web/src/components/*.tsx` | React 组件 |
| `apps/web/src/pages/*.tsx` | 页面组件 |
| `apps/web/src/services/api.ts` | API 服务 |
| `apps/web/package.json` | 依赖配置 |

### 6.7 阶段 7：Evaluation (~5 个文件)

| 文件路径 | 说明 |
|----------|------|
| `core/evaluation/__init__.py` | 模块初始化 |
| `core/evaluation/rag_evaluator.py` | RAG 评估器 |
| `core/evaluation/agent_evaluator.py` | Agent 评估器 |
| `core/evaluation/report_generator.py` | 评估报告生成 |

---

## 7. 参考项目映射

### 7.1 SmartVoyage (A2A + MCP)

| 原项目实现 | 你的项目落地 |
|-----------|-------------|
| `python-a2a` A2AServer | 可复用模式，简化当前实现 |
| `FastMCP` MCP Server | 可迁移当前 MCP |
| 意图识别 Prompt | 复用模式 |
| Agent Card 定义 | 复用模式 |

### 7.2 integrated_qa_system (RAG)

| 原项目实现 | 你的项目落地 |
|-----------|-------------|
| `document_processor.py` | 参考，适配你的 parser |
| `vector_store.py` | 参考，适配你的 milvus_store |
| `strategy_selector.py` | 参考，适配你的 hybrid_search |

### 7.3 当前项目 (Analytics Agent)

| 已完成实现 | 复用方式 |
|-----------|----------|
| `analytics/state.py` | RAG/Contract Agent State 模板 |
| `analytics/nodes.py` | 节点函数模板 |
| `analytics/graph.py` | StateGraph 模板 |
| `llm_content_generator.py` | 答案生成模板 |

---

## 8. 接续开发指南

### 8.1 如何继续开发

如果开发过程中断，重新开始时按以下步骤：

1. **阅读本文档**：了解项目现状和待完成内容
2. **查看 SKILL.md**：了解代码规范和模式
3. **查看 AGENTS.md**：了解项目约束
4. **查看现有代码**：特别是 `core/agent/workflows/analytics/`（最完整的参考）
5. **按阶段继续**：按本文档的阶段顺序继续开发

### 8.2 当前进度

根据最近的对话，以下工作已完成：

| 阶段 | 状态 | 完成时间 |
|------|------|----------|
| 项目规划 | ✅ 完成 | 2026-05-03 |
| SKILL.md 更新 | ✅ 完成 | 2026-05-03 |
| 本文档创建 | ✅ 完成 | 2026-05-03 |

### 8.3 待开始的工作

| 阶段 | 下一步 | 起始文件 |
|------|--------|----------|
| 阶段 1 | 创建 `core/rag/retrieval/` | dense_retriever.py |
| 阶段 2 | 创建 `core/agent/workflows/rag/` | state.py |
| 阶段 3 | 创建 `core/contracts/` | models.py |
| 阶段 4 | 创建 `core/common/a2a/` | redis_producer.py |
| 阶段 5 | 创建 `core/review/` | models.py |
| 阶段 6 | 创建 `apps/web/` | package.json |
| 阶段 7 | 创建 `core/evaluation/` | rag_evaluator.py |

### 8.4 代码复用检查清单

开发新模块时，先检查：

- [ ] 是否有现成的 Service 可以复用？
- [ ] 是否有现成的 Repository 可以复用？
- [ ] 是否有现成的 LLM Gateway 可以复用？
- [ ] 是否有现成的 Parser 可以复用？
- [ ] Analytics 工作流是否可以参考？

---

## 9. 验证清单

### 9.1 代码可导入

```bash
# 验证所有新模块可导入
python -c "
from core.rag.retrieval.dense_retriever import DenseRetriever
from core.rag.retrieval.sparse_retriever import SparseRetriever
from core.rag.retrieval.hybrid_search import HybridSearch
from core.rag.retrieval.reranker import Reranker
from core.rag.retrieval_chain import RetrievalChain
from core.contracts.extractor import ClauseExtractor
from core.contracts.risk_identifier import RiskIdentifier
from core.agent.workflows.rag.state import RAGState
from core.agent.workflows.contract.state import ContractState
print('All imports successful!')
"
```

### 9.2 FastAPI 可启动

```bash
uvicorn apps.api.main:app --reload --port 8000
```

### 9.3 单元测试

```bash
# RAG 检索链路测试
pytest tests/rag/ -v

# 合同审查测试
pytest tests/contracts/ -v

# Agent 工作流测试
pytest tests/agent/ -v
```

### 9.4 集成测试

```bash
# RAG 问答链路测试
pytest tests/integration/test_rag_flow.py -v

# 合同审查链路测试
pytest tests/integration/test_contract_flow.py -v
```

---

## 附录：常用命令

```bash
# 启动后端服务
uvicorn apps.api.main:app --reload --port 8000

# 启动 Celery Worker
celery -A apps.worker.celery_app worker --loglevel=info

# 启动前端（开发）
cd apps/web && npm run dev

# 运行测试
pytest tests/ -v

# 代码格式化
black .
isort .

# 类型检查
mypy core/
```

---

*本文档最后更新：2026-05-03*
