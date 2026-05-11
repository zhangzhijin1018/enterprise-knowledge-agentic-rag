# RAG Agent 学习文档

> 新疆能源集团知识与生产经营智能 Agent 平台 - RAG Agent 模块

---

## 目录

1. [系统架构概述](#1-系统架构概述)
2. [RAG 检索链路详解](#2-rag-检索链路详解)
3. [生产环境优化](#3-生产环境优化)
4. [BGE-M3 选型分析与备选方案](#4-bge-m3-选型分析与备选方案)
5. [Milvus 深度优化](#5-milvus-深度优化)
6. [LLM 意图识别方案](#6-llm-意图识别方案)
7. [高级特性与最佳实践](#7-高级特性与最佳实践)
8. [性能调优清单](#8-性能调优清单)
9. [常见问题与解决方案](#9-常见问题与解决方案)

---

## 1. 系统架构概述

### 1.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              用户请求流程                                     │
└─────────────────────────────────────────────────────────────────────────────┘

                              用户问句
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           API 层 (FastAPI)                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│  │  智能问答   │  │  合同审查   │  │  经营分析   │  │  报告生成   │       │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘       │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Supervisor Agent (路由层)                              │
│  ┌──────────────────────────────────────────────────────────────────┐      │
│  │                    Intent Detector (意图识别)                       │      │
│  │   policy_qa | safety_qa | equipment_qa | contract_review |      │      │
│  │   business_analysis | report_generation | ...                     │      │
│  └──────────────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Business Agent (业务 Agent)                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐   │
│  │ 制度政策 Agent │  │ 安全生产 Agent │  │ 合同审查 Agent │  │ 经营分析... │   │
│  └──────────────┘  └──────────────┘  └──────────────┘  └────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          RAG 检索层                                          │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                      RetrievalChain                                    │   │
│  │                                                                      │   │
│  │   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐          │   │
│  │   │ FAQ 匹配器  │────▶│ 策略选择器  │────▶│ 查询重写器  │          │   │
│  │   │ (BM25)     │     │ Strategy    │     │ Rewriter    │          │   │
│  │   └─────────────┘     └─────────────┘     └─────────────┘          │   │
│  │          │                                           │                │   │
│  │          ▼                                           ▼                │   │
│  │   ┌─────────────────────────────────────────────────────────────┐     │   │
│  │   │                    Hybrid Search                            │     │   │
│  │   │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │     │   │
│  │   │   │ Dense检索   │  │ Sparse检索  │  │ BM25检索    │    │     │   │
│  │   │   │ (BGE-M3)   │  │ (BGE-M3)   │  │ (RANK_BM25) │    │     │   │
│  │   │   └─────────────┘  └─────────────┘  └─────────────┘    │     │   │
│  │   └─────────────────────────────────────────────────────────────┘     │   │
│  │                              │                                      │   │
│  │                              ▼                                      │   │
│  │                    ┌─────────────────┐                              │   │
│  │                    │   Reranker      │                              │   │
│  │                    │ (BGE-Reranker) │                              │   │
│  │                    └─────────────────┘                              │   │
│  │                              │                                      │   │
│  │                              ▼                                      │   │
│  │                    ┌─────────────────┐                              │   │
│  │                    │ Citation Builder│                              │   │
│  │                    └─────────────────┘                              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LLM 生成层                                         │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐          │
│  │ Prompt Registry │────▶│  LLM Gateway   │────▶│  答案生成      │          │
│  └─────────────────┘     └─────────────────┘     └─────────────────┘          │
│                                   │                                          │
│                         ┌─────────┴─────────┐                              │
│                         │  OpenAI Compatible │                              │
│                         │  / vLLM / 私有化   │                              │
│                         └─────────────────────┘                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 核心技术栈

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| **后端框架** | FastAPI | 异步 API + Pydantic 校验 |
| **Agent 编排** | LangGraph | 状态机 + 工作流 |
| **LLM 接入** | OpenAI-compatible Gateway | 支持私有化模型 |
| **Embedding** | BGE-M3 | Dense + Sparse 多向量 |
| **Reranker** | BGE-Reranker | 语义精排 |
| **向量数据库** | Milvus | Hybrid Search |
| **元数据库** | PostgreSQL | 元数据 + Trace |
| **缓存队列** | Redis + Celery | 异步任务 |

### 1.3 目录结构

```
enterprise-knowledge-agentic-rag/
├── apps/
│   ├── api/                    # FastAPI 应用
│   │   ├── main.py
│   │   ├── deps.py            # 依赖注入
│   │   └── routers/           # API 路由
│   │       └── rag.py
│   └── web/                   # React 前端
├── core/
│   ├── agent/                 # Agent 核心
│   │   ├── business_agents/    # 业务 Agent
│   │   ├── workflows/         # LangGraph 工作流
│   │   │   ├── analytics/    # 经营分析
│   │   │   ├── contract/     # 合同审查
│   │   │   └── rag/          # RAG 检索
│   │   └── ...
│   ├── rag/                   # RAG 检索核心
│   │   ├── retrieval/        # 检索器
│   │   │   ├── dense_retriever.py
│   │   │   ├── sparse_retriever.py
│   │   │   ├── bm25_retriever.py
│   │   │   ├── faq_retriever.py
│   │   │   ├── hybrid_search.py
│   │   │   └── reranker.py
│   │   ├── query_rewriter.py # 多路策略
│   │   ├── retrieval_chain.py
│   │   ├── citations/         # 引用生成
│   │   └── factory.py         # 工厂函数
│   ├── llm/                   # LLM 网关
│   ├── embedding/             # Embedding 网关
│   ├── vectorstore/           # 向量存储
│   │   ├── base.py
│   │   └── milvus_store.py
│   └── ...
├── docs/
│   └── RAG_AGENT学习文档.md   # 本文档
└── tests/
```

---

## 2. RAG 检索链路详解

### 2.1 完整检索流程

```text
用户问句
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. FAQ 匹配阶段 (BM25)                                          │
│                                                                 │
│    用户问句 ──▶ BM25 关键词匹配 ──▶ 与 FAQ 问句库对比            │
│                                                │                │
│                           ┌─────────────────────┼───────────────┐│
│                           │                     │               ││
│                           ▼                     ▼               ││
│                    置信度 ≥ 0.85         置信度 < 0.85         ││
│                           │                     │               ││
│                           ▼                     ▼               ││
│                    直接返回 FAQ 答案         进入 RAG 检索       ││
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼ (仅当 FAQ 未命中时)
┌─────────────────────────────────────────────────────────────────┐
│ 2. RAG 检索阶段                                                 │
│                                                                 │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 2.1 策略选择 (Strategy Selector)                             │ │
│ │     ┌────────────────────────────────────────────────────┐ │ │
│ │     │ LLM 驱动：分析查询特征，选择最佳策略                │ │ │
│ │     │ 规则驱动：关键词匹配，自动选择策略                   │ │ │
│ │     │                                                    │ │ │
│ │     │ 策略类型：                                          │ │ │
│ │     │ • Direct (直接检索) - 意图明确                     │ │ │
│ │     │ • HyDE (假设答案) - 抽象查询                        │ │ │
│ │     │ • SubQuery (子查询) - 复杂多主题                    │ │ │
│ │     │ • Backtracking (回溯) - 简化复杂查询                │ │ │
│ │     └────────────────────────────────────────────────────┘ │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                              │                                  │
│                              ▼                                  │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 2.2 查询重写 (Query Rewriter)                               │ │
│ │     根据策略重写查询：                                      │ │
│ │     • HyDE: 生成假设答案 → 用于检索                        │ │
│ │     • SubQuery: 拆分为多个简单查询                         │ │
│ │     • Backtracking: 简化为基础问题                         │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                              │                                  │
│                              ▼                                  │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 2.3 Hybrid Search (多路混合检索)                           │ │
│ │                                                             │ │
│ │     ┌─────────────┐     ┌─────────────┐                   │ │
│ │     │ Dense检索   │     │ Sparse检索  │                   │ │
│ │     │ BGE-M3 Dense│     │ BGE-M3 Sparse│                   │ │
│ │     └──────┬──────┘     └──────┬──────┘                   │ │
│ │            │                    │                          │ │
│ │            └────────┬───────────┘                          │ │
│ │                     ▼                                       │ │
│ │              ┌─────────────┐                                │ │
│ │              │ 分数融合    │                                │ │
│ │              │ Weighted/  │                                │ │
│ │              │ RRF/COFOR  │                                │ │
│ │              └─────────────┘                                │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                              │                                  │
│                              ▼                                  │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 2.4 Reranker (语义精排)                                    │ │
│ │     使用 BGE-Reranker 对候选 chunk 进行精排                  │ │
│ │     输出 top_k 个最相关的 chunk                             │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                              │                                  │
│                              ▼                                  │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 2.5 上下文构造 + 引用生成                                   │ │
│ │     • 构建适合 LLM 理解的上下文                             │ │
│ │     • 生成可溯源的引用信息                                  │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                              │                                  │
│                              ▼                                  │
│                       返回检索结果                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. LLM 答案生成                                                 │
│                                                                 │
│    检索上下文 + 用户问句 ──▶ Prompt Template ──▶ LLM ──▶ 答案  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 核心模块说明

#### 2.2.1 FAQRetriever

```python
class FAQRetriever:
    """FAQ 检索器 - 基于 BM25 的 FAQ 问句匹配。

    职责：
    - 从 MySQL/Redis 加载 FAQ 数据
    - 使用 BM25 算法进行问句匹配
    - 置信度阈值 0.85
    """
```

#### 2.2.2 HybridSearch

```python
class HybridSearch:
    """多路混合检索编排器。

    职责：
    - 并行执行 Dense、Sparse 两路检索
    - 支持 Weighted、RRF、COFOR 三种融合策略
    """
```

#### 2.2.3 QueryRewriter

```python
class QueryRewriter:
    """查询重写器。

    支持策略：
    - Direct: 直接检索
    - HyDE: 生成假设答案增强检索
    - SubQuery: 拆分复杂查询
    - Backtracking: 简化复杂查询
    """
```

---

## 3. 生产环境优化

### 3.1 性能优化方向

#### 3.1.1 检索性能优化

| 优化项 | 当前状态 | 优化目标 | 具体做法 |
|--------|---------|---------|---------|
| **向量索引** | 基础索引 | 最优索引类型 | 根据数据规模选择 HNSW/IVF |
| **检索并行化** | 串行检索 | 并行多路召回 | asyncio 并发执行 Dense/Sparse |
| **缓存机制** | 无缓存 | 多级缓存 | Query Cache + Result Cache |
| **分页检索** | 全量返回 | 游标分页 | offset + limit 优化 |
| **预热机制** | 按需加载 | 启动预热 | 热点数据预加载 |

#### 3.1.2 内存优化

| 优化项 | 当前状态 | 优化目标 | 具体做法 |
|--------|---------|---------|---------|
| **Embedding 缓存** | 无 | LRU 缓存 | 相同文本复用向量 |
| **Chunk 压缩** | 原始存储 | 压缩存储 | gzip/lz4 压缩 |
| **批量处理** | 单条处理 | 批量向量化 | Batch Embedding |
| **内存池** | Python 默认 | 对象池复用 | 减少 GC 压力 |

#### 3.1.3 LLM 调用优化

| 优化项 | 当前状态 | 优化目标 | 具体做法 |
|--------|---------|---------|---------|
| **Token 优化** | 简单拼接 | 智能截断 | 按语义块截断 |
| **Prompt 缓存** | 无 | Prompt Cache | 相同 Prompt 复用 |
| **流式输出** | 非流式 | 流式返回 | Server-Sent Events |
| **模型降级** | 无 | 降级策略 | 大模型失败自动降级 |

### 3.2 准确率优化

#### 3.2.1 检索准确率

| 优化项 | 具体做法 | 预期收益 |
|--------|---------|---------|
| **查询扩展** | 同义词扩展 + 纠错 | +5~10% Recall |
| **意图增强** | 领域知识注入 Prompt | +5~15% Precision |
| **重排序** | 多阶段 Rerank | +10~20% NDCG |
| **多样性召回** | MMR (Maximal Marginal Relevance) | +5~10% 覆盖度 |

#### 3.2.2 答案质量

| 优化项 | 具体做法 | 预期收益 |
|--------|---------|---------|
| **引用准确性** | 强制引用来源 | 降低幻觉 |
| **结构化输出** | JSON Schema 约束 | 提高稳定性 |
| **Chain of Thought** | 思考链提示 | 提高推理准确性 |

### 3.3 可靠性优化

#### 3.3.1 容错机制

```python
# 示例：多级降级策略
class RetrievalChain:
    async def retrieve_with_fallback(self, query: str):
        # 1. 尝试完整 RAG 链路
        try:
            return await self.full_rag_retrieval(query)
        except VectorDBError:
            # 2. 降级：跳过 Reranker
            logger.warning("Reranker 不可用，降级为直接检索")
            return await self.direct_retrieval(query)
        except LLMTimeout:
            # 3. 降级：使用缓存答案
            return await self.cached_answer(query)
        except Exception as e:
            # 4. 最终降级：返回无法回答
            return {"answer": "抱歉，暂时无法回答您的问题"}
```

#### 3.3.2 监控告警

| 监控指标 | 告警阈值 | 处理策略 |
|---------|---------|---------|
| 检索延迟 P99 > 500ms | 立即告警 | 自动扩容 |
| Reranker 失败率 > 5% | 5分钟内告警 | 检查模型服务 |
| LLM 调用超时 > 30s | 立即告警 | 降级或扩容 |
| 向量库连接失败 | 立即告警 | 触发主备切换 |

---

## 4. BGE-M3 选型分析与备选方案

### 4.1 为什么选择 BGE-M3

#### 4.1.1 核心优势

| 优势项 | 说明 | 对本项目价值 |
|--------|------|-------------|
| **多向量支持** | 同时输出 Dense + Sparse + ColBERT | 一模型支持多种检索 |
| **中文优化** | 在 MTEB 中文榜单表现优秀 | 能源文档检索效果好 |
| **多语言** | 支持 100+ 语言 | 预留多语言扩展 |
| **开源免费** | Apache 2.0 协议 | 商业可用 |
| **生态成熟** | HuggingFace 下载量大 | 社区支持好 |

#### 4.1.2 与 Milvus 原生集成

```python
# BGE-M3 同时生成 Dense 和 Sparse 向量
from flag_model import FlagModel

model = FlagModel("BAAI/bge-m3", device="cuda")

# 一次调用生成多种向量
output = model.encode(
    ["文本1", "文本2"],
    return_dense=True,
    return_sparse=True,
    return_colbert=True
)

dense = output["dense_vecs"]      # 用于向量检索
sparse = output["lexical_weights"] # 用于关键词检索
colbert = output["colbert_vecs"]   # 用于 ColBERT 检索
```

#### 4.1.3 性能对比

| 模型 | 中文 MTEB 得分 | 向量维度 | 推理速度 |
|------|---------------|---------|---------|
| **BGE-M3** | 64.2% | 1024 | 中等 |
| text2vec-base | 61.8% | 768 | 快 |
| m3e-base | 63.1% | 768 | 快 |
| Instructor-large | 66.5% | 768 | 慢 |
| GTE-large | 65.8% | 1024 | 慢 |

### 4.2 备选方案

#### 4.2.1 方案对比

| 模型 | 优势 | 劣势 | 适用场景 |
|------|------|------|---------|
| **BGE-M3** (当前) | 多向量 + 中文好 + 开源 | 推理速度中等 | 通用场景 |
| **text2vec-base** | 速度快 + 体积小 | 准确性略低 | 轻量部署 |
| **m3e-base** | 中文优化 + 速度快 | 功能单一 | 简单场景 |
| **Instructor-large** | 准确性最高 | 速度慢 + 体积大 | 高精度场景 |
| **GTE-large** | 准确性高 | 速度慢 | 高精度场景 |
| **Jina-Embeddings** | API 接入简单 | 依赖外部 | 快速验证 |

#### 4.2.2 备选方案详解

##### 方案 A：text2vec-base (轻量替代)

```python
# 适用场景：资源受限环境
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("shibing624/text2vec-base-chinese")

# 优势：体积小(~400MB)，推理快
# 劣势：准确性略低于 BGE-M3
```

##### 方案 B：Instructor-large (高精度)

```python
# 适用场景：高精度要求
from InstructorEmbedding import INSTRUCTOR

model = INSTRUCTOR("hkunlp/instructor-large")

# 优势：任务定制指令，准确性更高
# 劣势：推理慢(~10x)，显存占用大
```

##### 方案 C：多模型融合

```python
# 生产级方案：多模型融合
class MultiModelEnsemble:
    """多模型集成检索。"""

    def __init__(self):
        self.models = {
            "bge_m3": BGEEmbedding(),      # 主力模型
            "text2vec": Text2VecEmbedding(), # 轻量备份
            "instructor": InstructorEmbedding(), # 高精度备用
        }
        self.weights = {"bge_m3": 0.6, "text2vec": 0.2, "instructor": 0.2}

    async def encode(self, texts: list[str]) -> np.ndarray:
        # 并行调用多模型
        results = await asyncio.gather(
            *[self.models[name].encode(texts) for name in self.models]
        )
        # 加权融合
        fused = sum(w * r for w, r in zip(self.weights.values(), results))
        return fused
```

### 4.3 向量维度选择

| 维度 | 存储空间 | 检索精度 | 推荐场景 |
|------|---------|---------|---------|
| 384 | 1x | 基础 | 轻量部署 |
| 768 | 2x | 良好 | 默认推荐 |
| 1024 | 2.7x | 优秀 | 高精度场景 |

**建议**：本项目使用 1024 维 Dense 向量，平衡精度和存储。

---

## 5. Milvus 深度优化

### 5.1 索引类型选择

#### 5.1.1 索引对比

| 索引类型 | 构建速度 | 查询速度 | 内存占用 | 召回率 | 适用场景 |
|---------|---------|---------|---------|--------|---------|
| **FLAT** | 最快 | 慢 | 大 | 100% | 小数据集(<1M) |
| **IVF_FLAT** | 中等 | 中等 | 中 | 95~99% | 中等规模 |
| **IVF_PQ** | 快 | 快 | 小 | 90~95% | 大规模 |
| **HNSW** | 慢 | 最快 | 大 | 95~99% | 高QPS |
| **DISKANN** | 中 | 快 | 小 | 95~99% | 超大规模 |

#### 5.1.2 推荐配置

```yaml
# 生产环境推荐配置
collection:
  name: document_chunks

  # 向量字段配置
  fields:
    - name: dense_vector
      type: FLOAT_VECTOR
      dim: 1024
      index:
        type: HNSW                    # 高QPS场景首选
        params:
          M: 16                       # 构建质量和内存折中
          efConstruction: 128          # 构建时的搜索范围

    - name: sparse_vector
      type: FLOAT_VECTOR
      dim: 250001                    # BGE-M3 sparse 维度
      index:
        type:SPARSE_INVERTED_INDEX    # 稀疏向量专用索引

  # 段配置
  segment:
    maxSize: 512MB                   # 段大小
    growing:
      maxCapacity: 4096              # Growing segment 容量

# 查询参数
search_params:
  hnsw:
    ef: 128                          # 查询时的搜索范围，越大越准越慢
  ivf:
    nprobe: 32                        # 查询探针数
```

### 5.2 Collection 设计

#### 5.2.1 Schema 设计

```python
# Milvus Collection Schema
{
    "fields": [
        # 主键
        {"name": "chunk_uuid", "type": "VARCHAR", "max_length": 128, "is_primary": True},

        # 向量字段
        {"name": "dense_vector", "type": "FLOAT_VECTOR", "dim": 1024},
        {"name": "sparse_vector", "type": "FLOAT_VECTOR", "dim": 250001},

        # 业务字段
        {"name": "document_id", "type": "VARCHAR", "max_length": 128},
        {"name": "knowledge_base_id", "type": "VARCHAR", "max_length": 64},
        {"name": "business_domain", "type": "VARCHAR", "max_length": 32},
        {"name": "chunk_type", "type": "VARCHAR", "max_length": 32},  # child_text, table_summary等
        {"name": "chunk_index", "type": "INT64"},                     # 切片序号

        # 权限字段
        {"name": "access_scope", "type": "VARCHAR", "max_length": 32},
        {"name": "security_level", "type": "INT8"},                     # 1-5级

        # 溯源字段
        {"name": "section_title", "type": "VARCHAR", "max_length": 256},
        {"name": "page_start", "type": "INT32"},
        {"name": "page_end", "type": "INT32"},

        # 元数据
        {"name": "created_at", "type": "DATETIME"},
        {"name": "updated_at", "type": "DATETIME"},
    ],

    # 索引配置
    "indexes": [
        {"field": "dense_vector", "index_type": "HNSW", "metric_type": "IP", "params": {"M": 16, "efConstruction": 128}},
        {"field": "sparse_vector", "index_type": "SPARSE_INVERTED_INDEX", "metric_type": "IP"},
        {"field": "document_id", "index_type": "INVERTED"},
        {"field": "knowledge_base_id", "index_type": "INVERTED"},
        {"field": "business_domain", "index_type": "INVERTED"},
        {"field": "security_level", "index_type": "INVERTED"},
    ]
}
```

#### 5.2.2 分区策略

```python
# 按业务域分区
partitions = [
    "policy",      # 制度政策
    "safety",      # 安全生产
    "equipment",   # 设备检修
    "new_energy",  # 新能源运维
    "contract",    # 合同合规
    "project",     # 项目资料
]

# 分区优势：
# 1. 查询时可以只扫描相关分区
# 2. 不同分区可以设置不同的副本数
# 3. 便于数据管理和清理
```

### 5.3 查询优化

#### 5.3.1 混合查询参数

```python
# 优化后的混合查询
search_params = {
    # Dense 向量搜索参数
    "ANN": {
        "metric_type": "IP",
        "params": {
            "ef": 128,           # HNSW 查询参数，越大越准
            "nprobe": 32,         # IVF 查询参数
        }
    },

    # Sparse 向量搜索参数
    "SPARSE": {
        "metric_type": "IP",
        "params": {
            "rf": 32,            # 稀疏向量召回参数
        }
    },

    # 混合查询权重
    "rerank": {
        "metric_type": "WRAPPER",
        "params": {
            "rrf_k": 60,          # RRF 融合参数
            "weights": [0.6, 0.4] # Dense:Sparse 权重
        }
    }
}
```

#### 5.3.2 分页优化

```python
# 游标分页 (Keyset Pagination) - 比 offset 更高效
def search_with_cursor(
    query_vector: list[float],
    limit: int = 10,
    last_id: str = None,
    last_score: float = None
):
    """使用游标分页，避免大 offset 的性能问题。"""

    # 先获取上一页最后一条的 ID 和分数
    filter_expr = f"chunk_uuid > '{last_id}'" if last_id else None

    results = milvus_client.search(
        collection_name="document_chunks",
        data=[query_vector],
        limit=limit + 1,  # 多查一条用于判断是否有下一页
        offset=0,         # 不使用 offset，使用 filter
        filter=filter_expr,
        output_fields=["chunk_uuid", "score"],
    )

    # 判断是否还有下一页
    has_more = len(results[0]) > limit
    items = results[0][:limit] if has_more else results[0]

    return {
        "items": items,
        "next_cursor": items[-1]["id"] if has_more else None,
        "has_more": has_more
    }
```

### 5.4 性能调优

#### 5.4.1 内存配置

```yaml
# milvus.yaml
storage:
  # 最小加载段大小，大于这个值的段会被加载到内存
  minio:
    preload:
      enabled: true
      collection: "*"
      maxMemoryPerNode: 16GB

queryNode:
  # 查询线程数
  numExecutorThreads: 16

  # LRU 缓存大小
  cache:
    enabled: true
    memoryLimit: 32GB  # 建议设置为机器内存的 50%

indexNode:
  # 索引构建线程数
  numExecutorThreads: 16
```

#### 5.4.2 负载均衡

```python
# 客户端负载均衡配置
milvus_client = MilvusClient(
    uri="milvus://milvus-cluster:19530",
    # 客户端-side 负载均衡
    round_robin=True,  # 轮询各查询节点

    # 连接池配置
    pool_size=10,
    max_pool_size=50,

    # 超时配置
    timeout=30,
)
```

#### 5.4.3 监控指标

```yaml
# Prometheus 监控指标
metrics:
  - name: milvus_query_latency_p99
    type: gauge
    labels: [collection, partition]

  - name: milvus_index_build_duration
    type: histogram
    labels: [index_type, collection]

  - name: milvus_segment_row_count
    type: gauge
    labels: [collection, segment_type]

  - name: milvus_cache_hit_rate
    type: gauge
```

### 5.5 高可用部署

```yaml
# docker-compose.milvus.yml
version: '3.8'

services:
  etcd:
    image: quay.io/coreos/etcd:v3.5.5
    deploy:
      replicas: 3
    environment:
      - ETCD_AUTO_COMPACTION_MODE=revision
      - ETCD_AUTO_COMPACTION_RETENTION=1000

  minio:
    image: minio/minio:latest
    deploy:
      replicas: 2
    volumes:
      - minio_data:/minio_data
    command: minio server /minio_data --multi-site.domain minio

  milvus-meta:
    image: milvusdb/milvus:v2.3.4
    environment:
      - ETCD_ENDPOINTS=etcd:2379
      - MINIO_ADDRESS=minio:9000
    volumes:
      - meta_data:/var/lib/milvus

  querynode:
    image: milvusdb/milvus:v2.3.4
    deploy:
      replicas: 3
    depends_on:
      - milvus-meta
    environment:
      - ETCD_ENDPOINTS=etcd:2379
      - MINIO_ADDRESS=minio:9000
      - QUERY_NODE_ID=query-node-{1,2,3}
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

---

## 6. LLM 意图识别方案

### 6.1 概述

意图识别是 Agent 系统的"大脑"，决定用户问题由哪个 Agent 处理。本项目提供三种意图识别方案：

| 方案 | 准确率 | 延迟 | 成本 | 适用场景 |
|------|--------|------|------|----------|
| **规则模式** | ~75% | <10ms | 免费 | 开发测试、快速验证 |
| **LLM 模式** | ~95% | 200-500ms | API 调用 | 生产环境推荐 |
| **混合模式** | ~92% | 100-300ms | 少量 API | 高可用要求 |

### 6.2 提示词优化方案

#### 6.2.1 为什么需要优化

规则匹配的问题：
- 无法理解语义相似但表述不同的问题
- 难以处理多意图、模糊意图
- 规则维护成本高，无法覆盖所有场景

LLM 提示词优化的核心目标：
1. **Few-shot Learning** - 通过示例让模型理解业务场景
2. **Chain-of-Thought** - 先推理再结论，提高准确率
3. **结构化输出** - JSON 格式，便于程序解析
4. **领域知识注入** - 明确新疆能源集团业务背景

#### 6.2.2 提示词设计原则

```python
# 提示词核心要素

PROMPT_TEMPLATE = """
## 1. System Prompt（系统提示词）
- 明确角色：企业智能问答系统的意图识别专家
- 注入业务背景：新疆能源集团业务域
- 定义意图类型：rag_qa / analytics_query / contract_review / general_chat

## 2. Few-shot Examples（示例）
- 提供 5-7 个典型示例
- 覆盖各意图类型
- 包含边界情况

## 3. Output Format（输出格式）
- JSON Schema 定义
- 明确必填/可选字段
- 包含置信度和推理过程

## 4. Guardrails（安全边界）
- 明确不支持的场景
- 定义降级策略
"""
```

#### 6.2.3 提示词模板详解

**系统提示词结构：**

```python
SYSTEM_PROMPT = """
你是一个企业智能问答系统的意图识别专家，服务于新疆能源集团。

## 业务背景
- 煤炭开采与销售
- 新能源发电（光伏、风电）
- 电力生产与销售
- 设备检修与运维
- 项目建设与管理

## 意图类型定义
1. rag_qa：制度政策、安全规程、设备操作、新能源运维、项目资料
2. analytics_query：发电量、收入、利润、成本等经营数据查询
3. contract_review：合同审查、风险识别、合规检查
4. general_chat：问候、寒暄、无明确业务目的

## 输出要求
请以 JSON 格式输出，包含：intent_type, business_domain, routing_target, confidence, reasoning
"""
```

**Few-shot 示例设计：**

```python
FEW_SHOT_EXAMPLES = """
## 示例 1

用户问题：请问集团差旅费报销标准是多少？

分析：
- 询问集团制度/报销标准
- 属于知识库问答
- 业务域：policy

输出：
{
    "intent_type": "rag_qa",
    "business_domain": "policy",
    "routing_target": "rag_agent",
    "confidence": 0.95,
    "reasoning": "用户询问集团差旅费报销标准，属于集团制度政策类问题"
}

## 示例 2

用户问题：本月光伏电站发电量是多少？

分析：
- 询问发电量数据
- 需要 SQL 查询
- 属于经营分析

输出：
{
    "intent_type": "analytics_query",
    "business_domain": "new_energy",
    "routing_target": "analytics_agent",
    "confidence": 0.92,
    "reasoning": "用户询问发电量数据，涉及经营数据查询"
}
"""
```

### 6.3 生产实现方案

#### 6.3.1 架构设计

```python
# 混合意图检测器
class HybridIntentDetector:
    """
    生产级意图检测器

    特点：
    1. LLM 优先：使用 LLM 进行意图识别
    2. 规则兜底：LLM 不可用或置信度低时降级
    3. 缓存优化：避免重复调用 LLM
    4. 结构化输出：Pydantic 验证
    """

    def __init__(
        self,
        llm_gateway,           # LLM 网关
        cache=None,            # Redis 缓存
        confidence_threshold=0.6,  # 置信度阈值
    ):
        self.llm_detector = LLMIntentDetector(llm_gateway, cache)
        self.rule_detector = RuleBasedIntentDetector()

    async def detect(self, query: str) -> IntentOutput:
        # 1. LLM 检测
        result = await self.llm_detector.detect(query)

        # 2. 置信度检查
        if result.confidence < self.confidence_threshold:
            # 3. 规则兜底
            rule_result = self.rule_detector.detect(query)
            if rule_result.confidence > result.confidence:
                return rule_result

        return result
```

#### 6.3.2 缓存策略

```python
# 多级缓存
class IntentCache:
    """意图识别结果缓存"""

    def __init__(self, redis_client):
        self.redis = redis_client
        self.ttl = 3600  # 1小时
        self.local_cache = LRUCache(max_size=1000)  # 内存缓存

    async def get(self, query: str) -> Optional[IntentOutput]:
        # L1: 内存缓存
        if result := self.local_cache.get(query):
            return result

        # L2: Redis 缓存
        cache_key = f"intent:{hashlib.md5(query.encode()).hexdigest()}"
        if cached := await self.redis.get(cache_key):
            result = IntentOutput.parse_raw(cached)
            self.local_cache.set(query, result)  # 回填 L1
            return result

        return None

    async def set(self, query: str, result: IntentOutput):
        # 写入两级缓存
        self.local_cache.set(query, result)
        cache_key = f"intent:{hashlib.md5(query.encode()).hexdigest()}"
        await self.redis.setex(cache_key, self.ttl, result.json())
```

#### 6.3.3 降级策略

```python
# 降级链路
class FallbackChain:
    """意图识别降级链路"""

    async def detect(self, query: str) -> IntentOutput:
        # Level 1: LLM + 缓存
        try:
            return await self.llm_detector.detect(query)
        except LLMTimeout:
            pass

        # Level 2: 规则引擎
        try:
            return self.rule_detector.detect(query)
        except Exception:
            pass

        # Level 3: 默认意图
        return IntentOutput(
            intent_type=IntentType.RAG_QA,
            routing_target="rag_agent",
            confidence=0.0,
            reasoning="意图识别全部失败，返回默认意图"
        )
```

### 6.4 性能优化

#### 6.4.1 延迟优化

| 优化手段 | 效果 | 实现方式 |
|---------|------|----------|
| 缓存命中 | 延迟降低 90% | Redis + 内存 LRU |
| 轻量模型 | 延迟降低 50% | qwen-turbo 替代 qwen-max |
| 并行处理 | 延迟降低 30% | 异步调用 |
| Prompt 压缩 | Token 减少 20% | 精简示例 |

#### 6.4.2 成本优化

```python
# 成本优化策略
class CostOptimizer:
    """意图识别成本优化"""

    # 缓存命中率目标
    CACHE_HIT_RATE_TARGET = 0.7

    # 模型选择策略
    MODEL_STRATEGY = {
        "high_confidence": "qwen-turbo",    # 缓存命中 / 简单查询
        "medium_confidence": "qwen-plus",    # 中等复杂
        "low_confidence": "qwen-max",        # 复杂 / 边界情况
    }

    def select_model(self, query: str, history: list) -> str:
        # 有缓存 -> 轻量模型
        if self.cache.get(query):
            return self.MODEL_STRATEGY["high_confidence"]

        # 无历史 -> 轻量模型
        if not history:
            return self.MODEL_STRATEGY["high_confidence"]

        # 复杂查询 -> 重模型
        if self._is_complex_query(query):
            return self.MODEL_STRATEGY["low_confidence"]

        return self.MODEL_STRATEGY["medium_confidence"]
```

### 6.5 效果评估

#### 6.5.1 评估指标

| 指标 | 目标值 | 计算方式 |
|------|--------|----------|
| 意图准确率 | > 92% | 正确识别数 / 总数 |
| 业务域准确率 | > 88% | 业务域正确数 / 意图为 rag_qa 的数量 |
| 槽位召回率 | > 85% | 提取槽位数 / 实际槽位数 |
| 延迟 P99 | < 500ms | 99 分位延迟 |
| 缓存命中率 | > 60% | 缓存命中数 / 总请求数 |

#### 6.5.2 持续优化

```python
# 意图识别持续优化闭环
class IntentOptimizer:
    """意图识别效果优化"""

    def record_feedback(self, query: str, result: IntentOutput, correct_intent: str):
        """记录反馈数据"""
        self.feedback_store.append({
            "query": query,
            "predicted": result.intent_type,
            "actual": correct_intent,
            "confidence": result.confidence,
            "is_correct": result.intent_type == correct_intent,
        })

    def analyze_errors(self):
        """分析错误模式"""
        errors = [f for f in self.feedback_store if not f["is_correct"]]
        # 统计错误类型
        error_patterns = defaultdict(list)
        for e in errors:
            key = (e["predicted"], e["actual"])
            error_patterns[key].append(e)

        # 返回高频错误模式
        return sorted(error_patterns.items(), key=lambda x: -len(x[1]))[:10]

    def improve_prompt(self, error_patterns: list):
        """基于错误模式优化提示词"""
        # 1. 提取高频错误
        # 2. 增加针对性示例
        # 3. 调整 prompt 结构
        # 4. 回归测试
        pass
```

### 6.6 最佳实践

#### 6.6.1 Prompt Engineering

```python
# 最佳实践 1: 明确边界
SYSTEM_PROMPT = """
## 意图类型边界

rag_qa（知识库问答）：
- ✅ 询问制度政策
- ✅ 询问安全规程
- ✅ 询问设备操作
- ❌ 不要询问具体数值（这是 analytics_query）
- ❌ 不要询问合同条款（这是 contract_review）

analytics_query（经营分析）：
- ✅ 询问发电量、收入、利润
- ✅ 要求数据对比、同比环比
- ❌ 不要询问定义、流程（这是 rag_qa）
"""

# 最佳实践 2: 包含边界示例
FEW_SHOT_EXAMPLES = """
## 边界示例（重要）

用户问题：集团差旅费报销标准是按什么制度执行的？
✅ intent_type: rag_qa
❌ 不要误判为 analytics_query（这是询问制度，不是数据）

用户问题：本月光伏发电量比上月增长了多少？
✅ intent_type: analytics_query
❌ 不要误判为 rag_qa（这是询问数据，不是制度）
"""
```

#### 6.6.2 监控告警

```python
# 意图识别监控指标
INTENT_METRICS = {
    # 准确率
    "intent_accuracy": {
        "description": "意图识别准确率",
        "alert_threshold": 0.90,  # 低于 90% 告警
    },

    # 置信度分布
    "confidence_distribution": {
        "description": "置信度分布",
        "alert_threshold": {
            "low_confidence_rate": 0.20,  # 低置信度占比超过 20% 告警
        }
    },

    # 性能指标
    "latency_p99": {
        "description": "P99 延迟",
        "alert_threshold": 500,  # ms
    },

    # 缓存命中率
    "cache_hit_rate": {
        "description": "缓存命中率",
        "alert_threshold": 0.50,  # 低于 50% 告警
    },
}
```

#### 6.6.3 快速迭代

```python
# A/B 测试框架
class PromptABTest:
    """提示词 A/B 测试"""

    def run_experiment(
        self,
        queries: list[str],
        prompt_a: str,
        prompt_b: str,
        ground_truth: list[str],
    ):
        # 1. 分别用两个 prompt 测试
        results_a = [self._test(prompt_a, q) for q in queries]
        results_b = [self._test(prompt_b, q) for q in queries]

        # 2. 计算准确率
        accuracy_a = self._calculate_accuracy(results_a, ground_truth)
        accuracy_b = self._calculate_accuracy(results_b, ground_truth)

        # 3. 统计检验
        significance = self._statistical_test(results_a, results_b)

        return {
            "prompt_a_accuracy": accuracy_a,
            "prompt_b_accuracy": accuracy_b,
            "winner": "prompt_b" if accuracy_b > accuracy_a else "prompt_a",
            "improvement": abs(accuracy_b - accuracy_a),
            "statistical_significance": significance,
        }
```

### 6.7 进阶优化

#### 6.7.1 多语言支持

```python
# 多语言意图识别
MULTI_LANG_SYSTEM_PROMPT = """
你是一个多语言企业智能问答系统的意图识别专家。

支持语言：
- 中文（zh）：新疆能源集团主要使用语言
- 英文（en）：国际业务场景
- 维吾尔语（ug）：本地化服务

请根据用户问题语言选择合适的分析策略。
"""

# 语言检测 + 意图识别
async def detect_multilingual(query: str) -> IntentOutput:
    lang = detect_language(query)

    if lang == "zh":
        return await zh_intent_detector.detect(query)
    elif lang == "en":
        return await en_intent_detector.detect(query)
    else:
        # 默认使用中文检测器
        return await zh_intent_detector.detect(query)
```

#### 6.7.2 多轮上下文

```python
# 多轮意图识别
async def detect_with_context(
    query: str,
    history: list[dict],
    max_history: int = 5,
):
    # 1. 截取最近 N 轮
    recent_history = history[-max_history:]

    # 2. 构建上下文
    context = build_conversation_context(recent_history)

    # 3. 意图识别（包含上下文）
    prompt = f"""
用户问题：{query}

对话上下文：
{context}

请根据上下文判断当前问题的意图。
"""

    return await llm_detector.detect_with_prompt(prompt)
```

---

## 7. 高级特性与最佳实践

### 7.1 查询意图增强

```python
class QueryIntentEnhancer:
    """查询意图增强器。

    在检索前增强用户查询，提高检索质量。
    """

    def __init__(self, llm_gateway):
        self.llm = llm_gateway

    ENHANCE_PROMPT = """你是一个企业知识库查询优化助手。

用户原始查询：{query}

请生成优化后的查询，要求：
1. 补充缺失的领域术语
2. 展开缩写和简称
3. 纠正可能的错别字
4. 补充隐含的上下文

直接输出优化后的查询，不要解释。"""

    async def enhance(self, query: str) -> str:
        """增强查询。"""
        response = await self.llm.generate(
            prompt=self.ENHANCE_PROMPT.format(query=query),
            temperature=0.1,
            max_tokens=200
        )
        return response.strip()
```

### 6.2 上下文压缩

```python
class ContextCompressor:
    """上下文压缩器。

    将检索到的 chunks 压缩为更精炼的上下文。
    """

    def __init__(self, llm_gateway):
        self.llm = llm_gateway

    COMPRESS_PROMPT = """你是一个文档压缩助手。

检索到的文档片段：
{docs}

用户问题：{question}

请从文档中提取与问题最相关的片段，并压缩为简洁的摘要。
要求：
1. 保留关键信息
2. 去除冗余
3. 直接面向问题回答
4. 保留来源标注

输出格式：
[来源1] 压缩后的内容
[来源2] 压缩后的内容"""

    async def compress(self, docs: list[str], question: str) -> str:
        """压缩上下文。"""
        docs_text = "\n\n".join([f"[文档{i+1}] {doc}" for i, doc in enumerate(docs)])

        response = await self.llm.generate(
            prompt=self.COMPRESS_PROMPT.format(docs=docs_text, question=question),
            temperature=0.1,
            max_tokens=500
        )
        return response.strip()
```

### 6.3 多跳推理

```python
class MultiHopReasoning:
    """多跳推理检索。

    支持需要多步推理的复杂问题。
    """

    HOP_TEMPLATE = """问题：{question}

已知信息：
{context}

请判断：
1. 当前信息是否足够回答问题？
2. 如果不够，还需要知道什么？
3. 生成下一步需要检索的问题。

输出格式：
- 结论：[是否足够/不够]
- 理由：[简要说明]
- 下一步问题：[如果不够，生成新的检索问题]"""

    async def reason(self, question: str, contexts: list[str]) -> dict:
        """执行多跳推理。"""
        context_text = "\n\n".join(contexts)

        response = await self.llm.structured_output(
            prompt=self.HOP_TEMPLATE.format(
                question=question,
                context=context_text
            ),
            schema={
                "type": "object",
                "properties": {
                    "conclusion": {"type": "string"},
                    "reason": {"type": "string"},
                    "next_question": {"type": "string"}
                }
            }
        )
        return response
```

### 6.4 知识图谱增强 (RAG + KG)

```python
class KnowledgeGraphEnhancer:
    """知识图谱增强器。

    结合知识图谱进行检索，增强实体理解。
    """

    def __init__(self, graph_db):
        self.graph = graph_db  # Neo4j 或其他图数据库

    def extract_entities(self, query: str) -> list[dict]:
        """从查询中提取实体。"""
        # NER 提取实体
        entities = self.ner_model.extract(query)

        # 在知识图谱中查找相关实体
        enriched_entities = []
        for entity in entities:
            kg_results = self.graph.find_neighbors(
                entity["text"],
                depth=2,
                relation_types=["包含", "属于", "关联"]
            )
            enriched_entities.append({
                **entity,
                "kg_neighbors": kg_results
            })

        return enriched_entities

    def build_kg_context(self, entities: list[dict]) -> str:
        """构建知识图谱增强的上下文。"""
        context_parts = []

        for entity in entities:
            context_parts.append(f"实体: {entity['text']} ({entity['type']})")
            if entity.get("kg_neighbors"):
                neighbors = [f"{n['name']}({n['relation']})" for n in entity["kg_neighbors"]]
                context_parts.append(f"  关联: {', '.join(neighbors)}")

        return "\n".join(context_parts)
```

### 6.5 主动学习闭环

```python
class ActiveLearningLoop:
    """主动学习闭环。

    持续优化检索质量。
    """

    def __init__(self, metrics_collector):
        self.metrics = metrics_collector
        self.feedback_store = []

    def record_interaction(
        self,
        query: str,
        retrieved_chunks: list[dict],
        user_rating: int,  # 1-5
        is_helpful: bool,
        corrections: list[str] = None
    ):
        """记录用户交互反馈。"""

        # 计算命中率
        hit_rate = sum(1 for c in retrieved_chunks if c.get("clicked", False)) / len(retrieved_chunks)

        # 存储反馈
        self.feedback_store.append({
            "query": query,
            "chunks": retrieved_chunks,
            "user_rating": user_rating,
            "is_helpful": is_helpful,
            "hit_rate": hit_rate,
            "corrections": corrections,
            "timestamp": datetime.now()
        })

        # 更新指标
        self.metrics.record_feedback(
            query=query,
            rating=user_rating,
            hit_rate=hit_rate
        )

    def generate_training_data(self) -> list[dict]:
        """生成训练数据用于模型微调。"""

        # 筛选高质量反馈
        positive_samples = [
            f for f in self.feedback_store
            if f["user_rating"] >= 4 and f["is_helpful"]
        ]

        negative_samples = [
            f for f in self.feedback_store
            if f["user_rating"] <= 2 or not f["is_helpful"]
        ]

        # 构建训练数据
        training_data = []

        for sample in positive_samples + negative_samples[:len(positive_samples)]:
            label = "relevant" if sample["user_rating"] >= 4 else "irrelevant"
            for chunk in sample["chunks"]:
                training_data.append({
                    "query": sample["query"],
                    "chunk": chunk["content"],
                    "label": label,
                    "score": chunk.get("score", 0)
                })

        return training_data
```

---

## 7. 性能调优清单

### 7.1 Embedding 服务优化

```bash
# 1. 模型量化 (INT8/FP16)
python -c "
from optimum.quanto import quantize
quantize(model, weights='int8')
model.save_pretrained('bge-m3-int8')
"

# 2. ONNX 导出
optimum-cli export onnx \
    --model BAAI/bge-m3 \
    --optimize O3 \
    bge-m3-onnx/

# 3. vLLM 部署 (支持 PagedAttention)
vllm serve BAAI/bge-m3 \
    --task embedding \
    --gpu-memory-utilization 0.9 \
    --max-model-len 8192
```

### 7.2 Milvus 配置优化

```yaml
# /milvus/configs/milvus.yaml
dataCoord:
  segment:
    maxSize: 512MB
    sealProlongWindow: 3600

  # 自动压缩
  compaction:
    enable_auto_compaction: true

queryNode:
  # LRU 缓存
  cache:
    enabled: true
    memoryLimit: 32GB

  # 查询并发
  maxConcurrentRequestsPerNode: 32

indexCoord:
  # 索引构建并发
  maxTaskNum: 16
```

### 7.3 缓存策略

```python
# 多级缓存
class MultiLevelCache:
    """多级缓存。"""

    def __init__(self):
        # L1: 内存缓存 (Query Cache)
        self.l1_cache = LRUCache(max_size=10000)

        # L2: Redis 缓存 (Result Cache)
        self.redis = RedisClient()
        self.redis_ttl = 3600

        # L3: Milvus (持久化)

    async def get(self, key: str) -> Optional[dict]:
        """多级缓存读取。"""

        # L1
        if result := self.l1_cache.get(key):
            return result

        # L2
        if result := self.redis.get(f"cache:{key}"):
            self.l1_cache.set(key, result)  # 回填 L1
            return result

        return None

    async def set(self, key: str, value: dict):
        """多级缓存写入。"""
        self.l1_cache.set(key, value)
        self.redis.setex(f"cache:{key}", self.redis_ttl, value)
```

### 7.4 监控指标

| 指标 | 目标值 | 告警阈值 | 优化方向 |
|------|-------|---------|---------|
| 检索延迟 P50 | < 50ms | > 100ms | 索引优化 |
| 检索延迟 P99 | < 200ms | > 500ms | 资源扩容 |
| 召回准确率 | > 85% | < 75% | 策略调优 |
| 答案满意度 | > 80% | < 60% | Prompt优化 |
| 系统 QPS | > 100 | - | 水平扩容 |

---

## 8. 常见问题与解决方案

### 8.1 检索质量问题

#### Q1: 检索结果与问题不相关

**原因分析：**
- Embedding 模型不够精确
- Chunk 切分不合理
- 查询与文档领域不匹配

**解决方案：**
```python
# 1. 调整 chunk 大小
CHUNK_CONFIG = {
    "chunk_size": 512,        # 减小 chunk
    "chunk_overlap": 64,     # 增加重叠
    "min_chunk_size": 128,   # 过滤过短 chunk
}

# 2. 使用更好的重排序
reranker = BGE_Reranker("BAAI/bge-reranker-large")  # 使用大模型

# 3. 增加查询扩展
enhanced_query = query_enhancer.enhance(query)
```

#### Q2: 召回率低

**原因分析：**
- 关键词匹配不足
- 向量检索召回不足

**解决方案：**
```python
# 增加 BM25 作为第三路召回
hybrid_search = HybridSearch(
    dense_retriever=BGEEmbedding(),
    sparse_retriever=BFEM3SparseEmbedding(),
    bm25_retriever=BM25Retriever(),
    fusion_method="rrf"  # RRF 融合更均衡
)

# 调整召回数
results = hybrid_search.search(
    query,
    top_k=50,  # 召回更多候选
    rerank_top_k=10  # 重排后取 top
)
```

### 8.2 性能问题

#### Q3: 检索延迟高

**原因分析：**
- Milvus 索引配置不当
- 向量维度太高
- 网络延迟

**解决方案：**
```yaml
# 优化 Milvus 索引
index:
  type: HNSW
  params:
    M: 16          # 降低构建参数
    efConstruction: 64

search_params:
  hnsw:
    ef: 64        # 降低查询参数
```

```python
# 降维处理
from sklearn.decomposition import PCA

# 将 1024 维降至 512 维
pca = PCA(n_components=512)
reduced_vectors = pca.fit_transform(original_vectors)
```

#### Q4: 内存占用高

**原因分析：**
- 向量维度太高
- 缓存未清理
- Milvus 段未压缩

**解决方案：**
```python
# 1. 量化向量
quantized_vectors = np.round(vectors * 127).astype(np.int8)

# 2. 定期清理缓存
async def cleanup_cache():
    await redis.execute("FLUSHDB")
    milvus_client.release_collection()

# 3. 触发段合并
milvus_client.compact(collection_name="document_chunks")
```

### 8.3 稳定性问题

#### Q5: Milvus 连接超时

**解决方案：**
```python
# 1. 配置连接池
milvus_client = MilvusClient(
    uri=uri,
    pool_size=10,
    max_pool_size=50,
    wait_timeout=30,
)

# 2. 实现重试机制
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def search_with_retry(query, top_k):
    return await milvus_client.search(query, top_k)

# 3. 降级到备用方案
try:
    return await search_with_retry(query, top_k)
except MilvusException:
    logger.warning("Milvus 不可用，降级到内存检索")
    return in_memory_fallback.search(query, top_k)
```

#### Q6: LLM 调用超时

**解决方案：**
```python
# 1. 配置超时
llm_gateway = LLMGateway(
    timeout=30,  # 30秒超时
    max_retries=2,
)

# 2. 实现降级
async def generate_with_fallback(prompt):
    try:
        return await llm_gateway.generate(prompt, model="qwen-max")
    except TimeoutError:
        logger.warning("主模型超时，降级到轻量模型")
        return await llm_gateway.generate(prompt, model="qwen-turbo")

# 3. 使用缓存答案
cached = await redis.get(f"llm_cache:{hash(prompt)}")
if cached:
    return cached

result = await generate_with_fallback(prompt)
await redis.setex(f"llm_cache:{hash(prompt)}", 3600, result)
return result
```

---

## 附录

### A. 相关文档

| 文档 | 说明 |
|------|------|
| `docs/TECH_SELECTION.md` | 技术选型文档 |
| `docs/ARCHITECTURE.md` | 架构设计文档 |
| `docs/AGENT_WORKFLOW.md` | Agent 工作流设计 |
| `core/rag/` | RAG 核心代码 |

### B. 参考资料

- [Milvus 官方文档](https://milvus.io/docs)
- [BGE-M3 HuggingFace](https://huggingface.co/BAAI/bge-m3)
- [LangGraph 文档](https://langchain-ai.github.io/langgraph/)
- [RAG 最佳实践](https://www.prompteng.ai/rag)

### C. 版本信息

| 版本 | 日期 | 修改内容 |
|------|------|---------|
| v1.0 | 2026-05-08 | 初始版本 |

---

*本文档由 Cursor AI 辅助生成，如有疏漏欢迎指正。*
