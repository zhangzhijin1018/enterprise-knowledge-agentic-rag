# Enterprise Knowledge Agentic RAG Platform

## 新疆能源集团知识与生产经营智能 Agent 平台

> 面向能源行业的生产级 Agentic RAG 平台，支持制度政策问答、安全生产规程、设备运维、合同审查、经营分析、报告生成等核心业务场景。

---

## 项目定位

本项目是一个**生产级 Agentic RAG 平台**，核心能力包括：

| 业务能力 | 说明 |
|---------|------|
| 智能问答 | 基于 RAG 的企业知识库问答 |
| 经营分析 | SQL 驱动的经营数据分析 |
| 合同审查 | 条款抽取 + 风险识别 + 模板比对 |
| 报告生成 | 多格式（Word/Excel/Markdown）报告自动生成 |
| Human Review | 高风险任务人工复核机制 |

---

## 技术架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              用户请求层                                      │
│   ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐      │
│   │ 智能问答 │  │经营分析 │  │合同审查 │  │报告生成 │  │人工复核 │      │
│   └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘      │
└────────┼───────────┼───────────┼───────────┼───────────┼──────────────────┘
         │           │           │           │           │
         ▼           ▼           ▼           ▼           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          API Gateway (FastAPI)                               │
│                    /api/v1/chat, /analytics, /contract...                  │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         │ A2A                │ A2A                 │ A2A
         ▼                    ▼                     ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   RAG Agent     │  │ Analytics Agent │  │ Contract Agent  │
│  (LangGraph)    │  │  (LangGraph)    │  │  (LangGraph)    │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  RAG MCP        │  │   SQL MCP       │  │  Contract MCP   │
│  (检索)         │  │  (查询)         │  │  (条款/风险)    │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│    Milvus       │  │   PostgreSQL    │  │   知识库        │
│  (向量检索)     │  │  (经营数据)     │  │  (合同模板)     │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

---

## 技术栈

| 层级 | 技术选型 |
|------|---------|
| **后端框架** | FastAPI + Pydantic + SQLAlchemy |
| **Agent 编排** | LangGraph + A2A 宏观调度 |
| **LLM 接入** | OpenAI-compatible Gateway / 私有化大模型 |
| **模型微调** | LoRA / QLoRA (LLaMA-Factory) ⭐ |
| **Embedding** | BGE-M3 (Dense + Sparse) |
| **Reranker** | BGE-Reranker |
| **向量数据库** | Milvus (Hybrid Search) |
| **元数据库** | PostgreSQL |
| **缓存与队列** | Redis + Celery |
| **文档解析** | PaddleOCR / PP-Structure / PyMuPDF |

---

## 核心模块

### 1. RAG 检索链路 ✅

**文件**：`core/rag/`

| 模块 | 说明 |
|------|------|
| `retrieval/dense_retriever.py` | Dense 向量检索 |
| `retrieval/sparse_retriever.py` | Sparse 向量检索 |
| `retrieval/hybrid_search.py` | 混合检索编排 |
| `retrieval/reranker.py` | BGE-Reranker 重排序 |
| `retrieval/faq_retriever.py` | FAQ 快速匹配 |
| `citations/builder.py` | 引用生成器 |
| `query_rewriter.py` | 查询改写策略 |

**检索链路**：
```
Query → FAQ匹配 → 策略选择 → Hybrid Search → Rerank → Context Builder → LLM Generate → Citation
```

### 2. Analytics Agent ✅ 完整

**文件**：`core/agent/workflows/analytics/`

| 节点 | 说明 |
|------|------|
| `entry` | 意图理解 + 槽位校验 |
| `slot_validator` | 最小可执行条件判断 |
| `clarification` | 槽位澄清（用户补充） |
| `analytics_planner` | 分析计划生成 |
| `sql_guard` | SQL 安全校验 |
| `sql_executor` | SQL 执行 |
| `report_generator` | 报告生成 |
| `human_review` | 人工复核 |
| `finish` | 结果返回 |

**特性**：
- 支持多指标、多时间范围、多维度分析
- 槽位校验 + 澄清恢复机制
- SQL Guard 安全校验
- 支持异步导出（Word/Excel/Markdown）

### 3. Contract Agent ✅ 完整

**文件**：`core/agent/workflows/contract/`

| 节点 | 说明 |
|------|------|
| `entry` | 合同解析 |
| `react_loop` | ReAct 执行循环（解析→检索→抽取→分析） |
| `reflect` | 风险反思 |
| `generate_report` | 报告生成 |
| `human_review` | 人工复核 |

**特性**：
- 基于 LangGraph ReAct 模式
- 条款抽取 + 风险识别 + 模板比对
- 支持高风险条款 Human Review
- Checkpoint 快照 + 恢复机制

### 4. MCP 服务 ✅

**文件**：`core/tools/mcp/`

| 服务 | 说明 |
|------|------|
| `sql_mcp_server.py` | SQL 查询 MCP |
| `report_mcp_server.py` | 报告生成 MCP |
| `gateway.py` | MCP 统一网关 |

### 5. A2A 消息总线 ✅

**文件**：`core/common/a2a/`

| 组件 | 说明 |
|------|------|
| `redis_producer.py` | Redis Streams 生产者 |
| `redis_consumer.py` | Redis Streams 消费者 |

### 6. LoRA 模型微调 ✅

**文件**：`finetune/`

| 文件 | 说明 |
|------|------|
| `peft/train_peft.py` | PEFT LoRA 训练器（513行） |
| `peft/merge_adapter.py` | LoRA Adapter 合并脚本 |
| `dataset/data_generator.py` | 合同数据集生成器（673行） |
| `dataset/dataset_schema.py` | 数据集 Schema 定义 |
| `evaluation/evaluator.py` | 微调效果评估器 |
| `llama_factory/*.yaml` | LLaMA-Factory 配置文件 |

**训练器核心功能**：
```python
class LoRATrainer:
    """LoRA 训练器 - 支持 QLoRA 量化训练"""

    def setup_model()      # 量化配置 + LoRA 应用
    def setup_data()       # 合同数据集加载
    def train()            # 训练 + 回调
    def merge_and_save()   # Adapter 合并
```

**数据集生成器**：
```python
class ContractDatasetGenerator:
    """支持 4 种合同类型模板"""
    # 能源运维合同、设备采购合同、工程建设合同、技术咨询合同

    def generate_synthetic_dataset()  # 合成数据生成
    def validate_dataset()            # 数据质量验证
    def split_dataset()               # 训练/验证/测试拆分
```

**训练链路**：
```
合同模板 → 数据生成 → 质量验证 → 训练集 → LoRA微调 → Adapter合并 → 部署
```

**使用示例**：
```bash
# 1. 生成训练数据
python -m finetune.dataset.data_generator --output ./data --train 1000 --val 100

# 2. PEFT 训练
python -m finetune.peft.train_peft \
    --model Qwen/Qwen3-8B \
    --data ./data/train.jsonl \
    --rank 16 --alpha 32 --epochs 3

# 3. LLaMA-Factory 训练
llamafactory-cli train finetune/llama_factory/contract_lora_qwen8b.yaml
```

---

## 已实现的特性

### 任务状态持久化

- `TaskRunRepository`：任务运行记录持久化
- `SlotSnapshot`：槽位快照（支持澄清恢复）
- `ClarificationEvent`：澄清交互事件
- `CheckpointRunner`：工作流快照 + 恢复

### 审计与可观测性

- `Trace`：链路追踪（run_id, trace_id, conversation_id）
- `Audit`：审计日志（Tool Call, SQL Audit, Human Review）
- `Metrics`：Prometheus 指标

### 评估模块

**文件**：`core/evaluation/`

| 评估器 | 说明 |
|--------|------|
| `contract_evaluator/` | 合同审查评估（RAGAS + 自定义） |
| `rag_evaluator.py` | RAG 链路评估 |

---

## 目录结构

```
enterprise-knowledge-agentic-rag/
├── apps/
│   ├── api/                    # FastAPI 应用
│   │   ├── main.py
│   │   ├── deps.py            # 依赖注入
│   │   └── routers/           # API 路由
│   │       ├── chat.py        # 智能问答
│   │       ├── analytics.py    # 经营分析
│   │       ├── contract_review.py  # 合同审查
│   │       └── ...
│   └── agents/                 # Agent Server
├── core/
│   ├── agent/                  # Agent 核心
│   │   ├── workflows/
│   │   │   ├── analytics/     # 经营分析 Workflow
│   │   │   ├── contract/       # 合同审查 Workflow
│   │   │   └── rag/           # RAG Workflow
│   │   ├── control_plane/     # 控制平面
│   │   │   ├── task_router.py  # 任务路由
│   │   │   ├── slot_validator.py  # 槽位校验
│   │   │   ├── clarification_manager.py  # 澄清管理
│   │   │   └── sql_guard.py    # SQL 安全
│   │   └── business_agents/   # 业务 Agent
│   ├── rag/                    # RAG 检索核心
│   │   ├── retrieval/
│   │   ├── query_rewriter.py
│   │   └── citations/
│   ├── llm/                    # LLM 网关
│   ├── embedding/              # Embedding 网关
│   ├── vectorstore/             # 向量存储
│   ├── database/               # 数据库模型
│   ├── repositories/           # 数据访问层
│   ├── services/               # 业务服务层
│   ├── tools/
│   │   ├── mcp/               # MCP 服务
│   │   ├── sql/               # SQL 工具
│   │   └── local/             # 本地工具
│   ├── observability/          # 可观测性
│   ├── evaluation/             # 评估模块
│   └── analytics/              # 分析引擎
├── docs/                       # 文档
│   ├── PRD.md
│   ├── ARCHITECTURE.md
│   ├── AGENT_WORKFLOW.md
│   ├── RAG_AGENT学习文档.md
│   └── LORA_FINETUNE_GUIDE微调.md
├── finetune/                    # 模型微调 (LLaMA-Factory)
│   ├── scripts/               # 训练脚本
│   └── dataset/               # 微调数据集
└── tests/                      # 测试
```

---

## 快速开始

### 1. 环境要求

- Python 3.10+
- Conda 环境：`conda activate tmf_project`

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 启动服务

```bash
# 启动 API 服务
uvicorn apps.api.main:app --reload --port 8000

# 启动 Celery Worker
celery -A apps.worker.celery_app worker --loglevel=info
```

### 4. API 文档

启动后访问：http://localhost:8000/docs

---

## 主要 API

| 接口 | 说明 |
|------|------|
| `POST /api/v1/chat` | 智能问答 |
| `POST /api/v1/analytics/query` | 经营分析查询 |
| `POST /api/v1/analytics/clarification/reply` | 澄清回复（恢复执行） |
| `POST /api/v1/contract/review` | 合同审查 |
| `POST /api/v1/contract/{run_id}/resume` | 合同审查恢复 |
| `GET /api/v1/human-reviews` | 待复核任务列表 |
| `POST /api/v1/human-reviews/{id}/approve` | 复核通过 |
| `POST /api/v1/human-reviews/{id}/reject` | 复核拒绝 |

---

## 相关文档

### 核心开发文档

| 文档 | 说明 |
|------|------|
| `AGENTS.md` | 项目编码约束与目录边界 |
| `docs/PRD.md` | 产品需求文档 |
| `docs/ARCHITECTURE.md` | 系统架构设计 |
| `docs/AGENT_WORKFLOW.md` | Agent 工作流设计 |
| `docs/TECH_SELECTION.md` | 技术选型文档 |
| `docs/SKILL.md` | 代码模式参考 |
| `docs/PROJECT_COMPLETE_DEVELOPMENT_GUIDE.md` | 完整开发指南 |
| `docs/LORA_FINETUNE_GUIDE微调.md` | Qwen3-8B LoRA 微调指南 |

### 专题学习文档

| 文档 | 说明 |
|------|------|
| `docs/RAG_AGENT学习文档.md` | RAG Agent 完整学习文档，涵盖检索链路、BGE-M3/Milvus 优化、意图识别、Query Rewrite 等核心模块 |
| `docs/合同审查项目学习指南.md` | 合同审查 Agent 完整学习指南，包含业务功能、架构设计、ReAct 模式、条款抽取、风险识别、Human Review 等 |
| `docs/经营分析Agent完整链路文档.md` | 经营分析 Agent 完整链路文档，包含 LangGraph 状态机、SQL 构建、槽位校验、澄清恢复、SSE 推送等 |
| `docs/PROMPT_提示词优化完整指南.md` | 提示词优化完整指南，以意图分类为例，详解 Few-shot、Chain-of-Thought、JSON Schema 约束等技巧 |
| `docs/redis_streams_sse_technical_doc.md` | Redis Streams SSE 进度推送技术文档，包含底层原理、XADD/XREAD、Consumer Group、断线重连等 |
| `docs/agent_event_bus_architecture.md` | 分布式 Agent 事件总线架构，基于 Redis Streams 实现多 Agent 并行推送、统一 SSE 订阅 |
| `docs/可观测性主流框架实战指南.md` | 可观测性建设指南，详解 OpenTelemetry + structlog + prometheus_client 四大支柱（日志/追踪/指标/审计） |
| `docs/llm_content_generator_design.md` | LLM 驱动内容生成器设计，详解并行 LLM 调用、JSON Schema 约束、SSE 渐进推送、大小判断策略 |

### 学习路径建议

```
1. 新人入门：AGENTS.md → SKILL.md → PROJECT_COMPLETE_DEVELOPMENT_GUIDE.md
2. RAG 开发：RAG_AGENT学习文档.md
3. 经营分析：经营分析Agent完整链路文档.md → redis_streams_sse_technical_doc.md
4. 合同审查：合同审查项目学习指南.md
5. 提示词工程：PROMPT_提示词优化完整指南.md
6. 可观测性：可观测性主流框架实战指南.md
7. 事件总线：agent_event_bus_architecture.md → redis_streams_sse_technical_doc.md
8. 模型微调：LORA_FINETUNE_GUIDE微调.md → llm_content_generator_design.md
```

---

## 开发指南

### 添加新的 Agent

1. 在 `core/agent/workflows/` 下创建新模块
2. 定义 State + Nodes + Graph
3. 注册到 `core/agent/business_agents/`
4. 添加 API Router
5. 补充测试

### 添加新的 Tool

1. 在 `core/tools/` 下实现 Tool
2. 注册到 `core/tools/registry.py`
3. 添加 MCP 封装（如需）
4. 补充审计日志

### 添加新的评估指标

1. 在 `core/evaluation/` 下实现 Evaluator
2. 定义数据集加载器
3. 添加评估任务

---

## License

Private - 新疆能源集团内部项目
