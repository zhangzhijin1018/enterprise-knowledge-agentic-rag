# AGENTS.md

## 1. 项目身份

你正在开发一个生产级企业 AI 项目：

**新疆能源集团知识与生产经营智能 Agent 平台**

英文名称：

**Enterprise Knowledge Agentic RAG Platform**

推荐仓库名：

```text
enterprise-knowledge-agentic-rag
```

本项目不是普通 RAG Demo，也不是简单聊天机器人，而是面向新疆能源集团业务场景的生产级 Agentic RAG 平台。

系统覆盖以下业务场景：

- 集团制度政策问答
- 安全生产规程问答
- 设备检修与故障排查
- 新能源电站运维辅助
- 合同与合规审查
- 经营数据分析
- 项目建设资料问答
- 报告生成
- Human Review 人工复核
- Trace 审计
- Evaluation 评估

---

## 2. 参考文档

开发前必须优先阅读以下文档：

```text
docs/PRD.md
docs/ARCHITECTURE.md
docs/TECH_SELECTION.md
```

如果文档与当前代码冲突，应优先说明冲突点，不要擅自扩大重构范围。

---

## 3. 技术栈约束

本项目当前确认技术栈如下：

```text
后端：FastAPI
Agent 编排：LangGraph
LLM 接入：OpenAI-compatible Gateway / 私有化大模型
Embedding：BGE-M3
Reranker：BGE-Reranker
向量数据库 / 检索引擎：Milvus
混合检索：BGE-M3 Dense + Sparse + Milvus Hybrid Search
元数据库：PostgreSQL
缓存与任务队列：Redis + Celery
前端：React + TypeScript + TailwindCSS
部署：Docker Compose + Kubernetes 预留
评估：RAGAS + 自定义 Evaluation
可观测性：OpenTelemetry + Prometheus + Grafana
```

以下技术暂不作为首期必选：

```text
OpenSearch：后续可选，用于审计日志搜索、后台全文搜索、复杂聚合分析
Kafka：后续可选，用于实时设备数据、告警流、事件总线
A2A：架构预留，用于跨 Agent / 跨系统协作
```

---

## 4. 总体开发原则

### 4.1 终局架构驱动

本项目不采用“先写简陋 Demo，后期大重构”的方式。

所有代码都应遵循生产级完整架构：

- 模块边界清晰
- 配置可替换
- 数据模型可扩展
- 权限控制前置
- 工具调用可审计
- Agent 执行可追踪
- RAG 检索可评估
- 高风险任务可人工复核

### 4.2 小步提交

每次只完成一个明确任务，不要一次性实现多个大模块。

正确示例：

```text
本次只创建 FastAPI 项目骨架和 /health 接口
本次只实现 PostgreSQL 配置和数据库连接
本次只实现 documents 表和 Alembic 迁移
本次只实现 Tool Registry 基础抽象
```

### 4.3 不擅自扩大范围

用户要求实现什么，就只实现什么。

如果发现需要额外变更，应先在输出中说明原因，不要擅自大规模修改无关文件。

### 4.4 先读后写

修改任何模块之前，应先阅读：

1. 相关文档；
2. 相关源码；
3. 相关测试；
4. 当前目录结构。

不要盲目新建重复模块。

---

## 5. 目录结构约束

建议项目目录结构如下：

```text
enterprise-knowledge-agentic-rag/
├── apps/
│   ├── api/
│   ├── worker/
│   └── web/
├── core/
│   ├── config/
│   ├── domain/
│   ├── database/
│   ├── security/
│   ├── agent/
│   ├── rag/
│   ├── llm/
│   ├── embeddings/
│   ├── vectorstore/
│   ├── tools/
│   ├── analytics/
│   ├── contracts/
│   ├── review/
│   ├── observability/
│   └── evaluation/
├── docs/
├── tests/
├── scripts/
├── docker/
├── docker-compose.yml
├── pyproject.toml
├── README.md
├── AGENTS.md
└── .env.example
```

### 5.1 API 层

路径：

```text
apps/api/
```

职责：

- FastAPI app 创建
- 路由注册
- 请求参数校验
- 依赖注入
- 响应封装
- API 错误处理

禁止：

- 在 route 里写复杂业务逻辑
- 在 route 里直接调用 Milvus
- 在 route 里直接调用 LLM
- 在 route 里直接执行 SQL
- 在 route 里实现 Agent 工作流

### 5.2 Worker 层

路径：

```text
apps/worker/
```

职责：

- Celery worker 启动
- 异步任务注册
- 文档解析任务
- embedding 任务
- 索引任务
- 报告生成任务
- 评估任务

### 5.3 Core 层

路径：

```text
core/
```

职责：

- 业务核心逻辑
- Agent 工作流
- RAG 检索
- 文档处理
- 工具调用
- 权限控制
- Trace 审计
- Evaluation 评估
- LLM / Embedding / VectorStore 抽象

---

## 6. 分层职责

### 6.1 API 层

API 层只负责：

- 接收请求
- 校验参数
- 获取用户上下文
- 调用 Service
- 返回响应

### 6.2 Service 层

Service 层负责：

- 应用级业务编排
- 调用 Agent / RAG / Tool / Repository
- 控制事务边界
- 组织响应数据

### 6.3 Agent 层

Agent 层负责：

- 问题理解
- 场景路由
- 状态管理
- 工具选择
- 风险判断
- Human Review 中断
- 最终答案生成

Agent 层不能直接操作数据库、Milvus 或 Redis，必须通过 Service / Repository / Gateway / Tool 抽象访问。

### 6.4 RAG 层

RAG 层负责：

- Query Rewrite
- Dense Retrieval
- Sparse Retrieval
- Hybrid Search
- Rerank
- Context Builder
- Citation Builder
- Retrieval Log

### 6.5 Tool 层

Tool 层负责：

- Tool Registry
- 参数 Schema
- 权限校验
- 风险等级
- 超时和重试
- Tool Call Trace
- MCP Tool Proxy 预留
- A2A Agent Gateway 预留

### 6.6 Database 层

Database 层负责：

- SQLAlchemy model
- Repository
- Session 管理
- Alembic 迁移

业务代码不得绕过 Repository 随意执行 SQL。

---

## 7. 编码规范

### 7.1 Python 规范

- 使用 Python 3.10+
- 类型标注尽量完整
- 优先使用 Pydantic 定义请求、响应和配置模型
- 函数职责单一
- 文件职责单一
- 命名清晰
- 避免超长函数
- 避免循环依赖
- 不写无意义的抽象
- 不写硬编码密钥
- 不写与业务无关的示例代码

### 7.2 命名规范

推荐命名：

```text
xxx_service.py
xxx_repository.py
xxx_model.py
xxx_schema.py
xxx_router.py
xxx_tool.py
xxx_node.py
xxx_gateway.py
```

示例：

```text
document_service.py
document_repository.py
document_model.py
document_schema.py
document_router.py
rag_search_tool.py
route_node.py
llm_gateway.py
```

### 7.3 异常处理

必须使用统一异常模型。

错误响应至少包含：

```json
{
  "error_code": "string",
  "message": "string",
  "trace_id": "string",
  "detail": {}
}
```

### 7.4 配置规范

所有环境相关配置必须通过：

```text
.env
.env.example
core/config/settings.py
```

禁止：

- 硬编码数据库账号
- 硬编码 API Key
- 硬编码模型地址
- 硬编码 Milvus 地址
- 硬编码 Redis 地址

### 7.5 日志规范

关键流程必须记录日志：

- API 请求
- 文档上传
- 文档解析
- Embedding
- Milvus 索引
- Agent Run
- Tool Call
- SQL Audit
- Human Review
- Evaluation

日志中不得输出明文密钥。

### 7.6 中文注释与技术讲解规范

本项目不仅是生产级工程项目，也是学习、复盘和面试展示项目。因此代码注释必须详细、清晰、可读。

#### 7.6.1 注释语言

所有核心业务代码、关键技术代码、数据模型字段、配置项和复杂流程必须使用中文注释。

允许保留必要英文技术名词，例如：

```text
FastAPI
LangGraph
Milvus
Embedding
Reranker
Tool Calling
Human Review
Trace
```

但需要配合中文解释。

#### 7.6.2 必须添加注释的内容

以下内容必须添加详细注释：

1. 核心业务逻辑；
2. 每个重要函数的作用；
3. 每个关键步骤的业务含义；
4. 每个数据模型字段的中文说明；
5. 每个 Pydantic Schema 字段的中文说明；
6. 每个数据库表字段的中文说明；
7. 每个 Agent State 字段的中文说明；
8. 每个 Tool 的输入、输出、权限和风险等级；
9. 每个 RAG 检索步骤；
10. 每个 SQL Guard 校验规则；
11. 每个 Human Review 状态；
12. 每个 Trace / Audit 字段；
13. 每个配置项的含义；
14. 关键技术点背后的原理。

#### 7.6.3 业务逻辑注释要求

核心流程不能只写“调用某函数”，而要解释为什么这么做。

错误示例：

```python
# 检索文档
chunks = retriever.search(query)
```

正确示例：

```python
# 根据用户问题检索知识库中的相关 chunk。
# 这里不是直接检索所有文档，而是先根据用户角色、业务领域和知识库权限构造 metadata filter，
# 确保用户只能召回自己有权限访问的文档内容，避免出现越权知识泄露。
chunks = retriever.search(query=query, filters=permission_filters)
```

#### 7.6.4 字段注释要求

数据模型字段必须写清楚中文含义。

错误示例：

```python
class Document(Base):
    id: str
    status: str
```

正确示例：

```python
class Document(Base):
    # 文档唯一 ID，用于关联 chunk、向量索引、检索日志和审计记录
    id: str

    # 文档当前处理状态，例如 uploaded、parsing、indexed、failed。
    # 该字段用于前端展示文档入库进度，也用于 worker 判断是否需要重新处理。
    status: str
```

如果使用 SQLAlchemy，字段也应尽量通过 `comment` 或代码注释说明含义。

示例：

```python
title = Column(
    String(255),
    nullable=False,
    comment="文档标题，例如《动火作业安全管理制度》",
)
```

#### 7.6.5 函数注释要求

核心函数必须包含 docstring，说明：

- 函数作用；
- 输入参数；
- 返回值；
- 业务场景；
- 注意事项；
- 是否涉及权限、安全、审计或高风险操作。

示例：

```python
def build_permission_filters(user_context: UserContext) -> dict:
    """
    根据当前用户上下文构造 Milvus metadata filter。

    业务作用：
    - 限制用户只能检索自己有权限访问的知识库和文档；
    - 防止普通员工检索到安全生产、合同、经营分析等敏感资料；
    - 该 filter 会在 RAG 检索前传入 Milvus，而不是检索后再过滤。

    参数：
    - user_context: 当前用户身份、角色、部门和权限集合。

    返回：
    - dict: 可用于向量检索的 metadata filter 条件。

    注意：
    - 权限过滤必须前置；
    - 不允许只在前端做权限控制；
    - 不允许先检索全部 chunk 再过滤。
    """
```

#### 7.6.6 Agent 工作流注释要求

LangGraph / Agent 相关代码必须详细解释每个 node 的职责。

示例：

```python
def route_node(state: AgentState) -> AgentState:
    """
    Agent 路由节点。

    业务作用：
    - 分析用户问题属于哪个业务场景；
    - 例如制度问答、安全生产问答、设备检修、合同审查、经营分析等；
    - 路由结果会决定后续调用哪个业务 Agent 或工具。

    关键点：
    - 不能只依赖关键词规则，后续可结合 LLM 分类；
    - 路由结果必须写入 state.route；
    - 路由过程需要记录 Trace，便于后续评估 Route Accuracy。
    """
```

#### 7.6.7 RAG 代码注释要求

RAG 检索链路必须解释每一步的原理和业务目的。

必须说明：

```text
为什么要 query rewrite
为什么要 dense retrieval
为什么要 sparse retrieval
为什么要 hybrid search
为什么要 rerank
为什么要 context compression
为什么答案必须带 citation
为什么权限 filter 必须在检索前执行
```

示例：

```python
# 使用 BGE-M3 同时生成 dense 向量和 sparse 向量。
# dense 向量更擅长语义相似召回，例如“动火作业安全确认”和“特殊作业审批要求”；
# sparse 向量更擅长关键词精确匹配，例如“E101 告警”“挂牌上锁”“环评批复”。
# 两者结合可以同时提升语义召回和关键词召回效果。
dense_vector, sparse_vector = embedding_gateway.embed_query(query)
```

#### 7.6.8 SQL Agent 注释要求

SQL Agent 代码必须详细说明安全控制逻辑。

必须解释：

```text
为什么只能 SELECT
为什么要自动 LIMIT
为什么要校验敏感字段
为什么要记录 SQL Audit
为什么不能让 LLM 直接执行 SQL
```

示例：

```python
# SQL 由 LLM 生成后不能直接执行。
# 因为 LLM 可能生成 DELETE、UPDATE、DROP 等危险语句，
# 也可能查询当前用户无权限访问的敏感字段。
# 所以必须先经过 SQL Guard 做语法、操作类型、表权限、字段权限和 LIMIT 校验。
checked_sql = sql_guard.validate(generated_sql, user_context)
```

#### 7.6.9 Tool Calling 注释要求

每个 Tool 必须注释说明：

- 工具解决什么业务问题；
- 输入参数是什么；
- 输出结果是什么；
- 需要什么权限；
- 风险等级是什么；
- 是否需要 Human Review；
- 调用结果如何进入 Trace。

示例：

```python
class SQLQueryTool(BaseTool):
    """
    经营数据查询工具。

    业务作用：
    - 用于经营分析 Agent 查询煤炭产量、销售收入、新能源发电量、成本利润等数据；
    - 工具只允许执行经过 SQL Guard 校验的只读 SQL；
    - 查询结果会返回给 Agent，用于生成经营分析结论或报告。

    风险控制：
    - risk_level = medium；
    - 查询敏感字段时需要权限校验；
    - 所有 SQL 必须记录到 sql_audits 表；
    - 禁止执行写操作。
    """
```

#### 7.6.10 配置项注释要求

配置文件中的每个关键配置都要说明中文含义。

示例：

```python
class Settings(BaseSettings):
    # PostgreSQL 数据库连接地址，用于存储用户、知识库、文档元数据、Trace 和评估数据
    database_url: str

    # Redis 连接地址，用作 Celery Broker 和短期缓存
    redis_url: str

    # Milvus 服务地址，用于存储和检索文档 chunk 的 dense/sparse 向量
    milvus_uri: str
```

#### 7.6.11 注释不要写成废话

禁止无意义注释。

错误示例：

```python
# 定义变量
x = 1

# 调用函数
result = func()
```

注释应该解释：

```text
业务目的
设计原因
技术原理
风险点
边界条件
```

#### 7.6.12 面试友好原则

关键模块的注释要做到：

- 初学者能看懂这个模块做什么；
- 面试时能直接基于代码讲解；
- 后续复盘时能快速理解为什么这样设计；
- Codex 后续修改时不会破坏架构边界。

也就是说，本项目代码不仅要“能运行”，还要“能讲清楚”。

---

## 8. Agent 开发规则

### 8.1 Agent State

Agent State 必须结构化，不允许用散乱 dict 到处传。

State 至少包含：

```text
run_id
user_id
user_role
query
route
business_domain
knowledge_base_ids
retrieved_chunks
tool_calls
risk_level
need_human_review
review_status
final_answer
status
```

### 8.2 Agent Router

Router 负责判断任务类型：

```text
policy_qa
safety_qa
equipment_qa
new_energy_ops_qa
contract_review
project_qa
business_analysis
report_generation
human_review_required
unsupported
```

### 8.3 业务 Agent

业务 Agent 包括：

```text
制度政策 Agent
安全生产 Agent
设备检修 Agent
新能源运维 Agent
合同审查 Agent
经营分析 Agent
项目资料 Agent
报告生成 Agent
```

### 8.4 高风险任务

以下任务不得直接自动执行：

- 安全生产高风险建议
- 危险作业处置建议
- 设备带电检修建议
- 合同重大风险判定
- 经营敏感数据查询
- 外部系统写操作
- 邮件正式发送
- 工单正式提交

必须进入 Human Review 或返回风险提示。

---

## 9. Tool Calling / Function Call 规则

### 9.1 必须通过 Tool Registry

所有 Agent 可调用工具必须注册到 Tool Registry。

工具不得散落在业务代码中直接调用。

### 9.2 Tool 元数据

每个 Tool 必须包含：

```text
name
description
input_schema
output_schema
required_permission
risk_level
timeout
retry_policy
audit_enabled
human_review_required
```

### 9.3 Tool 调用流程

工具调用必须经过：

```text
Agent 选择工具
  ↓
读取 Tool Registry
  ↓
校验参数 Schema
  ↓
校验用户权限
  ↓
判断风险等级
  ↓
必要时创建 Human Review
  ↓
执行工具
  ↓
记录 Tool Call
  ↓
返回工具结果
```

### 9.4 内部工具

内部工具包括：

```text
rag_search
document_reader
sql_query
sql_safety_check
contract_risk_check
report_generate
create_human_review
resume_agent_run
record_trace
```

### 9.5 MCP 与 A2A

本项目预留：

```text
MCP Tool Proxy
A2A Agent Gateway
```

当前代码可以先设计接口和目录，不要求立刻实现完整协议。

---

## 10. RAG 开发规则

### 10.1 检索主链路

本项目 RAG 主链路为：

```text
BGE-M3 Dense + Sparse
  ↓
Milvus Hybrid Search
  ↓
BGE-Reranker
  ↓
Context Builder
  ↓
Citation Builder
  ↓
LLM Answer
```

### 10.2 权限过滤必须前置

检索时必须使用 metadata filter 限制：

```text
user_role
department
knowledge_base_id
business_domain
access_scope
security_level
```

禁止先检索全部结果再在前端过滤。

### 10.3 答案必须可溯源

RAG 答案必须返回：

```text
document_id
filename
chunk_id
section
page
score
content_preview
```

### 10.4 无依据回答规则

如果知识库中没有明确依据，必须回答：

```text
知识库中未找到明确依据，无法基于现有资料给出确定回答。
```

禁止编造制度条款、安全规程、合同规则或经营数据。

---

## 11. SQL Agent 开发规则

### 11.1 SQL 必须经过安全校验

任何 SQL 执行前必须经过 SQL Guard。

### 11.2 禁止 SQL 操作

默认禁止：

```text
INSERT
UPDATE
DELETE
DROP
ALTER
TRUNCATE
CREATE
GRANT
REVOKE
```

### 11.3 查询限制

必须支持：

- 只读账号
- 自动 LIMIT
- 查询超时
- 返回行数限制
- 表级权限
- 字段级权限
- SQL Audit

### 11.4 SQL 输出

经营分析页面应展示：

- 用户问题
- 生成 SQL
- 安全校验结果
- 查询结果
- 分析结论
- Trace ID

---

## 12. 合同审查开发规则

合同审查必须包含：

- 合同解析
- 合同类型识别
- 条款抽取
- 标准模板检索
- 制度对比
- 风险识别
- 风险等级分类
- 审查报告生成
- 高风险法务复核

高风险合同不得直接输出“通过”结论。

---

## 13. Human Review 开发规则

### 13.1 触发条件

以下任务必须支持 Human Review：

- 高风险安全生产回答
- 高风险合同审查
- 敏感经营数据查询
- 外部系统高风险调用
- 正式报告发布
- 邮件或工单正式提交

### 13.2 Review 状态

Review 状态包括：

```text
pending
approved
rejected
revised
expired
cancelled
```

### 13.3 Review 数据

Review 必须记录：

```text
review_id
run_id
risk_level
review_status
reviewer_id
review_comment
created_at
reviewed_at
```

---

## 14. Trace 与审计规则

所有关键链路必须记录 Trace。

至少包括：

```text
agent_runs
tool_calls
retrieval_logs
llm_calls
sql_audits
human_reviews
evaluation_tasks
```

每次用户请求必须有唯一：

```text
run_id / trace_id
```

### 14.1 不允许缺失审计的操作

以下操作必须记录：

- Agent 执行
- Tool 调用
- SQL 查询
- 文档入库
- 合同审查
- Human Review
- Evaluation
- 高风险拒绝

---

## 15. Evaluation 开发规则

系统需要支持：

- RAG Evaluation
- Agent Evaluation
- SQL Evaluation
- Contract Review Evaluation
- Human Review Trigger Evaluation

评估模块应独立于业务接口，可以通过 API、脚本或 Celery 任务运行。

评估结果必须可持久化。

---

## 16. 前端开发规则

前端技术栈：

```text
React
TypeScript
TailwindCSS
```

前端页面包括：

- 登录页面
- 智能问答页面
- 知识库管理页面
- 文档管理页面
- 合同审查页面
- 经营分析页面
- Human Review 页面
- Trace 页面
- Evaluation 页面
- 系统配置页面

前端不负责最终权限判断，权限必须由后端执行。

---

## 17. 测试规则

新增核心功能必须补充测试。

### 17.1 单元测试

必须覆盖：

- 权限判断
- Parser
- Chunker
- Retriever
- SQL Guard
- Tool Registry
- Risk Policy
- Agent Router

### 17.2 集成测试

必须覆盖：

- 文档入库链路
- RAG 问答链路
- SQL 分析链路
- 合同审查链路
- Human Review 链路
- Trace 查询链路

### 17.3 测试命令

如果项目已有测试命令，修改完成后必须运行相关测试。

如果暂时没有完整测试框架，应至少保证新增代码可导入、基础接口可启动。

---

## 18. Codex 执行任务格式

每次执行任务时，应遵循以下流程：

```text
1. 阅读相关文档和源码
2. 明确本次任务范围
3. 列出计划修改的文件
4. 只修改必要文件
5. 补充必要测试
6. 运行相关测试或说明无法运行原因
7. 输出修改总结
```

每次任务结束时，应输出：

```text
修改文件列表
实现内容
运行命令
测试结果
未完成事项
后续建议
```

---

## 19. 禁止事项

禁止：

- 未经要求大规模重构
- 随意修改技术栈
- 硬编码密钥
- 路由层写复杂业务
- Agent 直接操作数据库
- Agent 直接操作 Milvus
- 绕过 Tool Registry 调用工具
- 绕过权限校验检索文档
- 绕过 SQL Guard 执行 SQL
- 高风险任务绕过 Human Review
- 编造制度、安全规程、合同条款或经营数据
- 删除已有文档和测试，除非用户明确要求
- 引入未讨论的新重型依赖
- 把 OpenSearch 或 Kafka 作为首期必选组件
- 将 A2A 作为当前必须实现功能
- 生成缺少中文注释的核心业务代码
- 生成没有字段中文说明的数据模型
- 生成没有解释关键技术原理的 RAG、Agent、SQL、Tool 代码

---

## 20. 当前开发优先级

在正式写业务代码前，推荐开发顺序为：

```text
1. 项目目录结构
2. FastAPI 基础骨架
3. 配置系统
4. PostgreSQL + SQLAlchemy + Alembic
5. 用户、角色、权限基础模型
6. 知识库与文档元数据模型
7. Redis + Celery
8. 文档解析与异步入库
9. BGE-M3 Embedding Gateway
10. Milvus VectorStore
11. Hybrid Search
12. BGE-Reranker
13. LangGraph Agent 基础工作流
14. Tool Registry
15. Trace 与审计
16. Human Review
17. SQL Agent
18. 合同审查 Agent
19. Evaluation
20. 前端页面
21. OpenTelemetry + Prometheus + Grafana
```

---

## 21. 输出风格要求

输出要工程化、简洁、明确。

不要只说“已完成”，要说明：

- 做了什么
- 为什么这样做
- 改了哪些文件
- 怎么验证
- 有哪些风险
- 下一步是什么

---

## 22. 当前版本说明

当前 `AGENTS.md` 为 v2 版本，用于约束 Codex 在本项目中的编码行为。

v2 重点新增：

- 中文详细注释规范；
- 字段级中文注释要求；
- 业务逻辑逐步说明要求；
- RAG / Agent / SQL / Tool 关键技术原理注释要求；
- 面试友好型代码说明要求。

后续如 PRD、架构或技术选型发生变化，应同步更新本文件。
