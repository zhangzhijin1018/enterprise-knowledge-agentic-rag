# 新疆能源集团知识与生产经营智能 Agent 平台 技术选型文档

## 1. 文档说明

本文档为 **新疆能源集团知识与生产经营智能 Agent 平台** 的技术选型文档。

本文档基于以下文档编写：

- `docs/PRD.md`
- `docs/ARCHITECTURE.md`

本项目采用生产级完整建设模式，技术选型需要兼顾：

- 企业级生产可用性
- 本地开发可落地性
- Agent / RAG 生态成熟度
- 私有化部署能力
- 权限、安全、审计能力
- 后续扩展能力
- 面试和项目展示价值

---

## 2. 最终推荐技术栈

| 模块 | 技术选型 |
|---|---|
| 后端框架 | FastAPI |
| Agent 编排 | LangGraph |
| LLM 接入 | OpenAI-compatible Gateway / 私有化大模型 |
| Embedding 模型 | BGE-M3 |
| Reranker 模型 | BGE-Reranker |
| 向量数据库 / 检索引擎 | Milvus |
| 混合检索 | Milvus Dense + Sparse Hybrid Search |
| 元数据库 | PostgreSQL |
| 缓存与任务队列 | Redis + Celery |
| 前端 | React + TypeScript + TailwindCSS |
| 部署 | Docker Compose，预留 Kubernetes |
| 评估 | RAGAS + 自定义 Evaluation |
| 可观测性 | OpenTelemetry + Prometheus + Grafana |
| 全文检索 / 搜索增强 | OpenSearch 暂不作为首期必选，作为后续可选扩展 |
| 事件流平台 | Kafka 暂不作为首期必选，作为后续实时事件流扩展 |

---

## 3. 技术选型总原则

### 3.1 优先选择 AI 工程生态成熟的技术

本项目核心是 Agentic RAG，因此主语言和主框架优先选择 Python 生态。

Python 在以下方向生态最成熟：

- LLM 接入
- Agent 编排
- RAG 检索
- Embedding
- Reranker
- 文档解析
- 模型评估
- 数据处理
- FastAPI 服务开发

### 3.2 优先保证架构可扩展

系统不应将具体模型、向量库、任务队列、外部工具写死在业务逻辑中。

所有关键能力都需要通过抽象层隔离：

- LLM Gateway
- Embedding Gateway
- Reranker Gateway
- VectorStore Provider
- Tool Registry
- Permission Service
- Trace Service
- Evaluation Runner

### 3.3 优先减少不必要组件复杂度

生产级系统不是组件越多越好。

本项目首期不引入 OpenSearch 和 Kafka 作为必选组件，是为了避免过度复杂化：

- Milvus 已经可以承载 RAG 主链路中的 dense、sparse、hybrid search。
- Redis + Celery 已经可以满足文档解析、Embedding、索引构建、报告生成、评估任务等异步任务需求。
- OpenSearch 和 Kafka 保留为后续扩展项。

### 3.4 技术选型要能解释业务价值

每个技术组件都必须能讲清楚：

1. 它解决什么问题；
2. 为什么当前阶段需要它；
3. 它和 Agent / RAG 主链路是什么关系；
4. 未来如何扩展。

---

## 4. 后端框架：FastAPI

### 4.1 选型结论

后端框架选择：

```text
FastAPI
```

### 4.2 选择原因

FastAPI 适合本项目，原因包括：

1. Python AI 生态友好；
2. 与 Pydantic 配合紧密，适合 API 参数校验；
3. 自动生成 Swagger / OpenAPI 文档；
4. 支持异步接口；
5. 适合构建微服务风格 API；
6. 代码结构轻量，适合 Agent / RAG 项目；
7. 本地开发和 Docker 部署都较简单。

### 4.3 在项目中的职责

FastAPI 负责：

- API 接入；
- 参数校验；
- 身份上下文注入；
- 权限入口校验；
- 调用应用服务层；
- 返回统一响应；
- 暴露 Swagger 文档。

FastAPI 不负责：

- 直接实现 Agent 工作流；
- 直接操作向量库；
- 直接调用 LLM；
- 直接写复杂业务逻辑。

### 4.4 替代方案

| 方案 | 说明 | 不选原因 |
|---|---|---|
| Django | 传统 Web 后台强 | 对 Agent / RAG 项目偏重 |
| Flask | 轻量 | 类型校验和工程规范不如 FastAPI |
| Spring Boot | 企业后端强 | AI 工程生态不如 Python 直接 |

---

## 5. Agent 编排：LangGraph

### 5.1 选型结论

Agent 编排框架选择：

```text
LangGraph
```

### 5.2 选择原因

本项目不是简单问答，而是多步骤、可中断、可恢复、可审计的 Agent 工作流。

LangGraph 适合处理：

- 多节点工作流；
- 条件分支；
- Agent 状态管理；
- 工具调用；
- Human-in-the-loop；
- 长流程任务；
- 错误重试；
- 执行轨迹追踪；
- 多业务 Agent 路由。

### 5.3 在项目中的典型场景

#### 安全生产问答

```text
用户问题
  ↓
安全生产 Agent 路由
  ↓
RAG 检索安全规程
  ↓
风险等级判断
  ↓
高风险则进入人工复核
  ↓
审核后返回答案
```

#### 合同审查

```text
上传合同
  ↓
合同解析
  ↓
条款抽取
  ↓
制度和模板检索
  ↓
风险识别
  ↓
高风险进入法务复核
  ↓
生成审查报告
```

#### 经营分析

```text
用户提出经营分析问题
  ↓
Schema 理解
  ↓
SQL 生成
  ↓
SQL 安全校验
  ↓
执行查询
  ↓
结果分析
  ↓
生成报告
```

### 5.4 替代方案

| 方案 | 说明 | 适用场景 |
|---|---|---|
| OpenAI Agents SDK | 工具调用、handoff、tracing 方便 | 快速构建工具型 Agent |
| CrewAI | 多角色协作简单 | 研究报告、多角色任务 |
| AutoGen | 多 Agent 对话能力强 | 实验性多 Agent 协作 |
| 自研状态机 | 可控性强 | 开发成本高 |

### 5.5 选型判断

本项目更强调：

- 状态机；
- 中断恢复；
- 人工复核；
- 企业工作流；
- 可追踪执行链路。

因此选择 LangGraph 作为主编排框架。

### 5.6 当前阶段的正式落地方式

从当前这一轮开始，LangGraph 不再只是“未来预留”或“本地样板”：

- `Analytics Workflow` 已经正式以 `StateGraph` 作为长期执行路径；
- `langgraph>=0.2,<1.0` 已进入正式依赖，而不是仅放在开发环境；
- 本地 fallback runner 不再作为生产主路径。

这样做的原因是：

1. 经营分析已经进入 workflow-first 微观执行阶段，需要测试环境和生产环境保持一致；
2. 如果长期保留 fallback 作为默认正常路径，容易出现“测试跑的是一套、生产跑的是另一套”；
3. `StateGraph` 的显式节点、条件分支和状态流转，正好匹配当前经营分析的微观状态机设计。

### 5.7 为什么本轮暂不接 LangGraph checkpoint

本轮明确 **不接 LangGraph checkpoint**，原因不是能力不足，而是当前边界更适合由业务状态机承担恢复：

- `task_run` 负责权威运行态；
- `slot_snapshot / clarification_event` 负责 clarification 恢复态；
- `review_task / export_task` 负责审核和导出中断恢复。

当前经营分析的恢复点仍然比较固定，直接引入 checkpoint 会带来两个问题：

1. 容易把 `plan / sql_bundle / execution_result` 这类微观大对象一起序列化；
2. 会重新放大状态持久化体积，与前面已经完成的 snapshot 边界收紧目标冲突。

因此当前策略是：

- `StateGraph` 负责单次 workflow 的显式流转；
- 业务状态机负责跨请求中断恢复；
- 等后续合同审查、复杂报告生成等出现更多动态恢复点时，再引入 `thread_id / checkpoint_id / checkpointer / resume command`。

---

## 6. LLM 接入：OpenAI-compatible Gateway / 私有化大模型

### 6.1 选型结论

LLM 接入采用：

```text
OpenAI-compatible Gateway
```

底层模型可以是：

- 私有化大模型；
- vLLM 部署的大模型；
- 阿里百炼兼容接口；
- DeepSeek 兼容接口；
- OpenAI 兼容接口；
- 其他企业内部模型服务。

### 6.2 选择原因

不在业务代码中绑定具体模型，而是封装统一 LLM Gateway。

这样可以支持：

- 模型替换；
- 私有化部署；
- 多模型路由；
- 不同任务使用不同模型；
- 统一日志；
- 统一超时重试；
- 统一 Token 统计；
- 统一成本统计。

### 6.3 在项目中的职责

LLM Gateway 负责：

- Chat Completion；
- Structured Output；
- Prompt 模板调用；
- JSON 格式输出；
- 模型超时处理；
- 失败重试；
- Token 统计；
- LLM Call Trace。

### 6.3.1 经营分析局部 ReAct Planner 的模型选型

经营分析复杂 planning 场景使用统一 `LLMGateway` 接入模型，推荐：

- 私有化优先：`Qwen2.5-14B-Instruct`；
- 更强复杂拆解：`Qwen2.5-32B-Instruct`；
- 部署方式：优先通过 vLLM 暴露 OpenAI-compatible API；
- 测试环境：使用 `MockLLMGateway`，不要求真实 API Key。

默认配置：

```text
LLM_PROVIDER=openai_compatible
LLM_MODEL_NAME=qwen2.5-14b-instruct
LLM_TIMEOUT_SECONDS=30
ANALYTICS_REACT_PLANNER_ENABLED=false
ANALYTICS_REACT_MAX_STEPS=3
```

默认关闭 ReAct planner 的原因是：

1. 简单经营分析问题由确定性 Planner 更稳、更快、更可解释；
2. ReAct 只服务复杂问题拆解，不能成为 SQL 执行链路；
3. 企业环境需要先可控，再增强智能。

### 6.3.2 Prompt Registry 与结构化输出

Prompt 工程采用：

- `core/prompts/registry.py`：按 `prompt_name` 加载模板；
- `core/prompts/renderer.py`：渲染模板变量；
- `core/prompts/templates/analytics/`：管理经营分析 ReAct planner 模板；
- Pydantic Structured Output：强制 LLM 输出结构化对象。

Prompt 不散落在业务节点中，原因是 prompt 需要版本化、审查、替换和模型适配。经营分析 ReAct prompt 明确约束：只能做规划，不能生成 SQL，不能绕过权限、SQL Guard 和数据范围治理。

### 6.4 设计建议

代码中不允许业务模块直接调用具体模型 SDK。

业务模块只能调用：

```python
llm_gateway.chat(...)
llm_gateway.generate(...)
llm_gateway.structured_output(...)
```

---

## 7. Embedding：BGE-M3

### 7.1 选型结论

Embedding 模型选择：

```text
BGE-M3
```

### 7.2 选择原因

BGE-M3 适合本项目，原因包括：

1. 对中文文档支持较好；
2. 支持多语言；
3. 适合企业知识库检索；
4. 支持 dense 向量；
5. 支持 sparse 表示；
6. 适合和 Milvus 做 hybrid search；
7. 适合制度、规程、合同、设备手册等复杂文本检索。

### 7.3 在项目中的职责

BGE-M3 用于：

- 文档 chunk 向量化；
- 用户 query 向量化；
- dense retrieval；
- sparse retrieval；
- hybrid search。

### 7.4 设计建议

Embedding 调用必须封装为：

```text
Embedding Gateway
```

业务代码不直接依赖具体模型实现。

---

## 8. Reranker：BGE-Reranker

### 8.1 选型结论

Reranker 模型选择：

```text
BGE-Reranker
```

### 8.2 选择原因

能源集团文档对准确性要求高，尤其是：

- 安全规程；
- 合同条款；
- 制度政策；
- 设备检修步骤；
- 项目审批资料。

仅靠向量召回可能召回语义相关但并非准确依据的 chunk。

Reranker 用于对召回候选进行精排，提高最终上下文质量。

### 8.3 检索链路位置

```text
用户问题
  ↓
Milvus dense + sparse hybrid search
  ↓
候选 chunk 合并
  ↓
BGE-Reranker 精排
  ↓
选取 top_k
  ↓
构造上下文
  ↓
LLM 生成答案
```

---

## 9. 向量数据库与检索引擎：Milvus

### 9.1 选型结论

向量数据库选择：

```text
Milvus
```

OpenSearch 不作为首期 RAG 主链路必选组件。

### 9.2 选择原因

Milvus 适合本项目，原因包括：

1. 面向大规模向量检索；
2. 支持 dense vector；
3. 支持 sparse vector；
4. 支持 hybrid search；
5. 可以和 BGE-M3 结合；
6. 支持 metadata filter；
7. 更适合企业级 RAG 架构展示；
8. 可以统一承载 RAG 主检索链路。

### 9.3 Collection 设计方向

Milvus Collection 可以包含：

```text
chunk_id
document_id
knowledge_base_id
business_domain
content
dense_vector
sparse_vector
metadata
access_scope
security_level
page
section
created_at
```

### 9.4 检索方式

系统检索支持：

- Dense Retrieval；
- Sparse Retrieval；
- Hybrid Search；
- Metadata Filter；
- 权限过滤；
- Rerank；
- Citation 返回。

### 9.5 为什么暂不引入 OpenSearch

本项目 RAG 主链路已经可以通过：

```text
BGE-M3 + Milvus dense/sparse hybrid search
```

实现语义召回与关键词召回结合。

因此首期不引入 OpenSearch，减少系统复杂度。

OpenSearch 保留为后续可选扩展，用于：

- 管理后台全文搜索；
- 审计日志搜索；
- Agent 日志搜索；
- 复杂聚合分析；
- 企业搜索门户。

### 9.6 架构表述

最终架构中，Milvus 是 RAG 主检索引擎。

OpenSearch 是可选增强组件，不进入首期必选技术栈。

---

## 10. 元数据库：PostgreSQL

### 10.1 选型结论

元数据库选择：

```text
PostgreSQL
```

### 10.2 存储内容

PostgreSQL 用于存储：

- 用户；
- 部门；
- 角色；
- 权限；
- 知识库；
- 文档元数据；
- chunk 元数据；
- 文档处理任务；
- Agent Run；
- Tool Call；
- Retrieval Log；
- LLM Call；
- SQL Audit；
- Human Review；
- Evaluation Dataset；
- Evaluation Result。

### 10.3 选择原因

选择 PostgreSQL 的原因：

1. 稳定成熟；
2. 支持事务；
3. 支持复杂查询；
4. 支持 JSONB；
5. 适合存储半结构化 Trace 数据；
6. 适合权限、审计、评估等系统数据；
7. 适合和 SQLAlchemy / Alembic 配合。

### 10.4 需要重点学习内容

项目开发过程中需要学习：

- 表设计；
- 主键和外键；
- 索引；
- JSONB；
- 事务；
- SQLAlchemy；
- Alembic；
- 连接池；
- 慢查询优化。

---

## 11. 缓存与任务队列：Redis + Celery

### 11.1 选型结论

异步任务和缓存选择：

```text
Redis + Celery
```

Kafka 不作为首期必选组件。

### 11.2 Redis 的职责

Redis 用于：

- Celery Broker；
- 任务状态缓存；
- 会话状态缓存；
- 临时上下文缓存；
- 频率限制；
- 短期缓存；
- Human Review 临时状态辅助。

### 11.3 Celery 的职责

Celery 用于执行异步任务，例如：

- 文档解析；
- 文档切分；
- Embedding 生成；
- Milvus 索引写入；
- 合同审查长任务；
- 报告生成；
- Evaluation 评估任务；
- 批量重建索引；
- 失败任务重试。

### 11.4 典型异步任务流程

```text
用户上传 PDF
  ↓
FastAPI 保存文件和文档元数据
  ↓
创建 Celery 任务
  ↓
立即返回 document_id
  ↓
Celery Worker 后台解析文档
  ↓
切分 chunk
  ↓
生成 embedding
  ↓
写入 Milvus
  ↓
更新 PostgreSQL 文档状态
```

### 11.5 为什么不选 Kafka 作为首期队列

Kafka 更适合：

- 实时事件流；
- 设备 IoT 数据；
- 电站告警流；
- 大规模日志流；
- 事件总线；
- 多消费者订阅；
- 消息回放。

本项目当前主要是：

- 后台任务；
- 文档处理；
- 报告生成；
- 评估任务；
- Agent 长任务。

这些更适合 Celery。

### 11.6 Kafka 的未来定位

Kafka 作为后续扩展项。

当系统需要接入以下场景时再引入 Kafka：

- 新能源电站实时告警流；
- 煤矿设备传感器数据流；
- 安全监控实时事件；
- 调度系统实时事件；
- 集团统一事件总线；
- 多系统事件订阅与回放。

---

## 12. 前端：React + TypeScript + TailwindCSS

### 12.1 选型结论

前端选择：

```text
React + TypeScript + TailwindCSS
```

### 12.2 选择原因

选择该组合的原因：

1. 适合构建复杂管理后台；
2. TypeScript 提高类型安全；
3. TailwindCSS 开发效率高；
4. 适合实现聊天页、文档页、Trace 页、评估页；
5. 生态成熟；
6. 展示效果好。

### 12.3 前端页面

前端需要包含：

- 登录页面；
- 智能问答页面；
- 知识库管理页面；
- 文档管理页面；
- 合同审查页面；
- 经营分析页面；
- Human Review 页面；
- Trace 页面；
- Evaluation 页面；
- 系统配置页面。

### 12.4 可选 UI 组件库

后续可选择：

- shadcn/ui；
- Ant Design；
- Material UI。

建议优先考虑 shadcn/ui 或 Ant Design。

---

## 13. 部署：Docker Compose + Kubernetes 预留

### 13.1 选型结论

部署方式选择：

```text
Docker Compose + Kubernetes 预留
```

### 13.2 本地开发环境

Docker Compose 用于本地开发和演示，包含：

- API 服务；
- Worker 服务；
- PostgreSQL；
- Redis；
- Milvus；
- Prometheus；
- Grafana；
- 前端服务。

### 13.3 生产环境预留

生产环境预留 Kubernetes 支持，用于：

- 服务弹性扩展；
- Worker 横向扩展；
- 模型服务独立部署；
- 监控系统部署；
- 配置和密钥管理；
- 滚动发布；
- 健康检查。

### 13.4 部署原则

1. 本地开发优先 Docker Compose。
2. 生产架构预留 Kubernetes。
3. 所有配置走环境变量。
4. 密钥不进入 Git。
5. 模型服务和应用服务解耦。

---

## 14. 评估：RAGAS + 自定义 Evaluation

### 14.1 选型结论

评估体系选择：

```text
RAGAS + 自定义 Evaluation
```

### 14.2 RAGAS 用途

RAGAS 用于评估：

- faithfulness；
- answer relevancy；
- context precision；
- context recall；
- answer correctness，若有标准答案。

### 14.3 自定义 Evaluation 用途

由于本项目有大量业务 Agent，必须自定义评估指标：

#### Agent 评估

- Route Accuracy；
- Tool Call Accuracy；
- Task Success Rate；
- Human Review Trigger Accuracy。

#### SQL 评估

- SQL Validity；
- SQL Safety；
- Execution Accuracy；
- Result Explanation Accuracy。

#### 合同审查评估

- Clause Extraction Accuracy；
- Risk Identification Recall；
- Risk Classification Accuracy；
- Human Reviewer Agreement Rate。

#### 安全生产问答评估

- Citation Accuracy；
- Risk Warning Accuracy；
- Unsafe Suggestion Rate；
- No-evidence Refusal Accuracy。

### 14.4 设计原则

评估模块必须独立于业务接口，可以通过脚本、API 或后台任务运行。

---

## 15. 可观测性：OpenTelemetry + Prometheus + Grafana

### 15.1 选型结论

可观测性选择：

```text
OpenTelemetry + Prometheus + Grafana
```

### 15.2 OpenTelemetry 的职责

OpenTelemetry 用于统一采集：

- Trace；
- Metrics；
- Logs，后续可选。

在本项目中，重点采集：

- API 请求链路；
- Agent 执行链路；
- RAG 检索耗时；
- LLM 调用耗时；
- Tool Call 耗时；
- SQL 执行耗时；
- Celery 任务耗时。

### 15.3 Prometheus 的职责

Prometheus 用于采集和存储指标，例如：

- 请求数量；
- 请求延迟；
- 错误率；
- Worker 任务数量；
- RAG 检索耗时；
- LLM 调用耗时；
- SQL 查询耗时；
- 系统资源指标。

### 15.4 Grafana 的职责

Grafana 用于展示监控面板，例如：

- API 延迟看板；
- Agent 成功率看板；
- RAG 检索耗时看板；
- LLM Token 使用看板；
- Celery 任务看板；
- SQL 查询看板；
- 错误率看板。

### 15.5 接入阶段

虽然技术选型确定，但可观测性可以在系统具备基础链路后接入。

推荐顺序：

1. 先实现数据库 Trace 表；
2. 再实现结构化日志；
3. 再接入 OpenTelemetry；
4. 再接入 Prometheus；
5. 最后配置 Grafana Dashboard。

---

## 16. OpenSearch 的定位

### 16.1 选型结论

OpenSearch：

```text
不作为首期必选组件
```

### 16.2 不首期引入的原因

原因包括：

1. BGE-M3 + Milvus 已经可以支持 dense + sparse hybrid search；
2. Milvus 可以作为 RAG 主检索引擎；
3. 引入 OpenSearch 会增加部署和维护复杂度；
4. 当前核心目标是 Agentic RAG，而不是企业全文搜索门户；
5. 管理后台全文搜索和日志搜索可后续扩展。

### 16.3 后续适合引入 OpenSearch 的场景

当系统需要以下能力时，可以引入 OpenSearch：

- 管理后台全文检索；
- 审计日志全文检索；
- Agent 执行日志搜索；
- 复杂聚合统计；
- 企业级搜索门户；
- 非向量化文档搜索；
- 大规模日志分析。

---

## 17. Kafka 的定位

### 17.1 选型结论

Kafka：

```text
不作为首期必选组件
```

### 17.2 不首期引入的原因

原因包括：

1. 当前任务主要是后台任务，不是实时事件流；
2. Redis + Celery 已经满足文档处理和异步任务需求；
3. Kafka 运维复杂度较高；
4. Kafka 原生不是任务队列，不负责任务状态；
5. 引入 Kafka 会增加系统理解和部署成本。

### 17.3 后续适合引入 Kafka 的场景

当系统需要以下能力时，可以引入 Kafka：

- 新能源电站实时告警流；
- 煤矿设备传感器数据流；
- 安全监控实时事件；
- 调度系统事件流；
- 设备状态实时采集；
- 集团统一事件总线；
- 多消费者订阅同一事件；
- 消息长期保存和回放。

### 17.4 Kafka 与 Celery 的区别

| 对比项 | Redis + Celery | Kafka |
|---|---|---|
| 核心定位 | 异步任务队列 | 分布式事件流平台 |
| 适合场景 | 文档解析、Embedding、报告生成 | 实时告警、日志流、IoT 数据 |
| 任务状态 | 支持 | 需要自行设计 |
| 重试机制 | Celery 原生支持 | 需要自行设计 |
| 消息回放 | 弱 | 强 |
| 多消费者订阅 | 一般 | 强 |
| 运维复杂度 | 较低 | 较高 |

---

## 18. 技术学习路线

由于项目包含多个生产级组件，学习不应一次性铺开，而应按项目用到的顺序逐步深入。

### 18.1 当前阶段需要重点学习

当前阶段重点学习：

1. FastAPI 项目结构；
2. PostgreSQL 基础；
3. SQLAlchemy；
4. Alembic；
5. Redis 基础；
6. Celery 基础；
7. Milvus 基础概念；
8. LangGraph 基础概念。

### 18.2 PostgreSQL 学习重点

需要掌握：

- 表设计；
- 主键 / 外键；
- 索引；
- JSONB；
- 事务；
- SQLAlchemy ORM；
- Alembic 迁移；
- 连接池；
- 慢查询分析。

### 18.3 Redis + Celery 学习重点

需要掌握：

- Redis 基础数据结构；
- Redis 作为 Celery Broker；
- Celery task；
- worker；
- result backend；
- 失败重试；
- 任务状态；
- 异步任务与 API 解耦。

### 18.4 Milvus 学习重点

需要掌握：

- Collection；
- Schema；
- dense vector；
- sparse vector；
- hybrid search；
- metadata filter；
- index；
- search params；
- BGE-M3 接入；
- WeightedRanker / RRF。

### 18.5 LangGraph 学习重点

需要掌握：

- State；
- Node；
- Edge；
- Conditional Edge；
- Checkpoint；
- Human-in-the-loop；
- Tool Calling；
- Error Retry；
- Workflow Trace。

### 18.6 可观测性学习重点

可观测性可以后置学习。

需要掌握：

- Trace；
- Span；
- Metrics；
- Logs；
- OpenTelemetry SDK；
- Prometheus scrape；
- Grafana dashboard；
- P95 / P99；
- Agent 链路监控。

---

## 19. 推荐开发接入顺序

虽然技术选型一次性确定，但开发接入建议按以下顺序进行：

1. 项目工程骨架；
2. FastAPI API 服务；
3. 配置系统；
4. PostgreSQL；
5. SQLAlchemy + Alembic；
6. 用户、角色、权限基础模型；
7. 知识库与文档元数据模型；
8. Redis + Celery；
9. 文档解析与异步入库；
10. BGE-M3 Embedding；
11. Milvus 索引与检索；
12. BGE-Reranker；
13. Hybrid Search；
14. LangGraph Agent；
15. Tool Registry；
16. SQL Guard 与经营分析；
17. 合同审查；
18. Human Review；
19. Trace 与审计；
20. Evaluation；
21. OpenTelemetry；
22. Prometheus；
23. Grafana；
24. 前端页面；
25. Docker Compose 完整部署；
26. Kubernetes 预留文档。

---

## 20. 最终技术栈确认

最终确认技术栈如下：

```text
后端：FastAPI
Agent：LangGraph
LLM：OpenAI-compatible Gateway / 私有化大模型
Embedding：BGE-M3
Reranker：BGE-Reranker
Vector DB / 检索引擎：Milvus
混合检索：BGE-M3 Dense + Sparse + Milvus Hybrid Search
全文检索：OpenSearch 暂不引入，后续可选
元数据库：PostgreSQL
缓存队列：Redis + Celery
事件流：Kafka 暂不引入，后续可选
前端：React + TypeScript + TailwindCSS
部署：Docker Compose + Kubernetes 预留
评估：RAGAS + 自定义 Evaluation
可观测：OpenTelemetry + Prometheus + Grafana
```

---

## 21. 当前版本说明

当前文档为技术选型文档 v1。

核心决策包括：

1. 使用 FastAPI 作为后端框架；
2. 使用 LangGraph 作为 Agent 编排框架；
3. 使用 OpenAI-compatible Gateway 接入 LLM 和私有化大模型；
4. 使用 BGE-M3 作为 Embedding 模型；
5. 使用 BGE-Reranker 作为重排序模型；
6. 使用 Milvus 作为 RAG 主检索引擎；
7. 不首期引入 OpenSearch；
8. 使用 PostgreSQL 存储系统元数据、Trace、权限和评估数据；
9. 使用 Redis + Celery 处理异步任务；
10. 不首期引入 Kafka；
11. 使用 React + TypeScript + TailwindCSS 构建前端；
12. 使用 Docker Compose 支持本地开发和演示；
13. 预留 Kubernetes 生产部署；
14. 使用 RAGAS + 自定义 Evaluation 建设评估体系；
15. 使用 OpenTelemetry + Prometheus + Grafana 建设可观测体系。
