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
docs/AGENT_WORKFLOW.md
docs/DB_DESIGN.md
docs/API_DESIGN.md
docs/PROJECT_STRUCTURE.md
```

如果文档与当前代码冲突，应优先说明冲突点，不要擅自扩大重构范围。

优先级建议：

```text
架构边界：ARCHITECTURE.md
工作流与状态机：AGENT_WORKFLOW.md
接口契约：API_DESIGN.md
数据库与模型：DB_DESIGN.md
代码目录与分层：PROJECT_STRUCTURE.md
```

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

### 3.1 MCP 实现技术栈约束

本项目第一期允许并推荐实现 MCP 接入边界，但不要求一次性接入所有外部系统。

推荐实现方式：

```text
MCP Server：Python
MCP 服务承载：FastAPI 或独立 Python 服务
MCP 协议层：MCP Python SDK / FastMCP 风格实现
输入输出模型：Pydantic
传输方式：优先 HTTP；本地工具场景可预留 stdio
项目内接入层：core/tools/mcp/
```

第一期优先落地的 MCP 服务类型：

```text
SQL MCP
File MCP
Report MCP
Enterprise API MCP
```

要求：

- MCP 作为 Tool / Capability Fabric 的一种实现方式；
- 不允许在业务代码里直接硬编码外部系统调用；
- 所有 MCP 调用必须经过统一网关、统一审计、统一权限与风险判断。

### 3.2 A2A 实现技术栈约束

A2A 在本项目中不是“先不管”，而是：

```text
第一期架构必须预留
第一期代码必须预留抽象边界
第一期不强制完整实现标准化跨系统生产协议
```

第一期推荐实现方式：

```text
A2A Gateway：Python + FastAPI
通信方式：HTTP/JSON
契约模型：Pydantic
代码位置：core/tools/a2a/ 或 core/agent/gateway/
任务契约：Task Envelope
结果契约：Result Contract
```

也就是说：

- 第一阶段先实现“内部 A2A 风格网关抽象”；
- 先把跨 Agent 委托、任务状态、结果回传、错误语义、Trace 贯通；
- 不要求第一天就强绑定某个重型第三方 A2A SDK；
- 后续若标准协议成熟，可在网关层替换，不改业务层。

### 3.3 当前不作为首期必选

```text
OpenSearch：后续可选，用于审计日志搜索、后台全文搜索、复杂聚合分析
Kafka：后续可选，用于实时设备数据、告警流、事件总线
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
- 多轮对话可承接
- 缺信息时可澄清
- 用户补充后可恢复执行

### 4.2 小步提交

每次只完成一个明确任务，不要一次性实现多个大模块。

正确示例：

```text
本次只创建 FastAPI 项目骨架和 /health 接口
本次只实现 PostgreSQL 配置和数据库连接
本次只实现 conversations / task_runs 最小模型
本次只实现 /chat 最小闭环骨架
本次只实现 clarification reply 流程骨架
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

推荐项目目录结构如下：

```text
enterprise-knowledge-agentic-rag/
├── apps/
│   ├── api/
│   │   ├── main.py
│   │   ├── deps.py
│   │   ├── middleware/
│   │   ├── routers/
│   │   └── schemas/
│   ├── worker/
│   │   ├── celery_app.py
│   │   └── tasks/
│   └── web/
├── core/
│   ├── common/
│   ├── config/
│   ├── security/
│   ├── database/
│   │   └── models/
│   ├── repositories/
│   ├── services/
│   ├── agent/
│   │   ├── control_plane/
│   │   ├── mesh/
│   │   └── contracts/
│   ├── tools/
│   │   ├── rag/
│   │   ├── mcp/
│   │   ├── a2a/
│   │   └── local/
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
- 归档任务

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

### 6.3 Repository 层

Repository 层只负责：

- ORM 查询
- 持久化
- 简单查询封装

禁止：

- 在 Repository 中写复杂业务逻辑
- 在 Repository 中做路由决策
- 在 Repository 中做风险判断

### 6.4 Agent 层

Agent 层负责：

- 问题理解
- 场景路由
- 状态管理
- 多轮上下文继承
- 槽位校验
- 澄清生成
- 恢复执行
- 工具选择
- 风险判断
- Human Review 中断
- 最终答案生成

Agent 层不能直接操作数据库、Milvus 或 Redis，必须通过 Service / Repository / Gateway / Tool 抽象访问。

### 6.5 RAG 层

RAG 层负责：

- Query Rewrite
- Dense Retrieval
- Sparse Retrieval
- Hybrid Search
- Rerank
- Context Builder
- Citation Builder
- Retrieval Log

### 6.6 Tool 层

Tool 层负责：

- Tool Registry
- 参数 Schema
- 权限校验
- 风险等级
- 超时和重试
- Tool Call Trace
- MCP Tool Proxy
- A2A Gateway

### 6.7 Database 层

Database 层负责：

- SQLAlchemy model
- Repository
- Session 管理
- Schema 迁移

业务代码不得绕过 Repository 随意执行 SQL。

---

## 7. API 开发规则

### 7.1 API 前缀

所有正式接口统一使用：

```text
/api/v1
```

### 7.2 统一响应模型

所有接口尽量返回统一结构：

```json
{
  "success": true,
  "trace_id": "tr_xxx",
  "request_id": "req_xxx",
  "data": {},
  "meta": {}
}
```

错误响应统一返回：

```json
{
  "success": false,
  "trace_id": "tr_xxx",
  "request_id": "req_xxx",
  "error": {
    "error_code": "string",
    "message": "string",
    "detail": {}
  }
}
```

### 7.3 统一链路标识

必须贯穿：

- `request_id`
- `trace_id`
- `run_id`
- `conversation_id`

### 7.4 API 状态表达

接口层必须能表达这些状态：

- `succeeded`
- `failed`
- `waiting_review`
- `awaiting_user_clarification`
- `waiting_async_result`
- `resuming_previous_task`

不要只返回“成功 / 失败”二值语义。

---

## 8. 编码规范

### 8.1 Python 规范

- 使用 Python 3.10+
- 本地开发最低支持 Python 3.10，推荐 Python 3.11；生产 Docker 镜像建议使用 Python 3.11。
- 本项目本地默认开发环境为 `conda activate tmf_project`。
- 如果当前终端无法直接 `conda activate`，则默认使用 `conda run -n tmf_project python`、`conda run -n tmf_project pytest`、`conda run -n tmf_project uvicorn` 执行 Python、测试和本地启动命令。
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

### 8.2 命名规范

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

### 8.3 异常处理

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

### 8.4 配置规范

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

### 8.5 日志规范

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
- Clarification
- Task Resume

日志中不得输出明文密钥。

### 8.6 中文注释与技术讲解规范

本项目不仅是生产级工程项目，也是学习、复盘和面试展示项目。因此代码注释必须详细、清晰、可读。

#### 8.6.1 注释语言

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
MCP
A2A
```

但需要配合中文解释。

#### 8.6.2 必须添加注释的内容

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
13. 每个 Clarification / Slot 字段；
14. 每个配置项的含义；
15. 关键技术点背后的原理。

#### 8.6.3 业务逻辑注释要求

核心流程不能只写“调用某函数”，而要解释为什么这么做。

#### 8.6.4 字段注释要求

数据模型字段必须写清楚中文含义。  
如果使用 SQLAlchemy，字段也应尽量通过 `comment` 或代码注释说明含义。

#### 8.6.5 函数注释要求

核心函数必须包含 docstring，说明：

- 函数作用；
- 输入参数；
- 返回值；
- 业务场景；
- 注意事项；
- 是否涉及权限、安全、审计或高风险操作。

#### 8.6.6 Agent 工作流注释要求

LangGraph / Agent 相关代码必须详细解释每个 node 的职责。

#### 8.6.7 RAG 代码注释要求

RAG 检索链路必须解释每一步的原理和业务目的。

#### 8.6.8 SQL Agent 注释要求

SQL Agent 代码必须详细说明安全控制逻辑。

#### 8.6.9 Tool Calling 注释要求

每个 Tool 必须注释说明：

- 工具解决什么业务问题；
- 输入参数是什么；
- 输出结果是什么；
- 需要什么权限；
- 风险等级是什么；
- 是否需要 Human Review；
- 调用结果如何进入 Trace。

#### 8.6.10 配置项注释要求

配置文件中的每个关键配置都要说明中文含义。

#### 8.6.11 注释不要写成废话

注释应该解释：

```text
业务目的
设计原因
技术原理
风险点
边界条件
```

#### 8.6.12 面试友好原则

关键模块的注释要做到：

- 初学者能看懂这个模块做什么；
- 面试时能直接基于代码讲解；
- 后续复盘时能快速理解为什么这样设计；
- Codex 后续修改时不会破坏架构边界。

---

## 9. Agent 开发规则

### 9.1 Agent State

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
conversation_id
slot_snapshot
clarification_state
```

### 9.2 Agent Router

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

### 9.3 业务 Agent

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

### 9.4 多轮对话规则

系统必须支持：

- `conversation_id` 承接多轮；
- 会话记忆读取；
- 指代消解；
- 槽位抽取；
- 缺失槽位时进入澄清；
- 用户补充后恢复原任务。

禁止：

- 把所有请求都当成单轮请求处理；
- 缺少关键槽位时盲猜执行；
- 高风险场景基于模糊上下文直接执行。

### 9.5 最小可执行条件规则

对经营分析、合同审查、报告生成等任务，必须在执行前校验最小可执行条件。

例如：

- 合同审查至少要有 `contract_file_id`
- 经营分析至少要有 `metric + time_range`
- 项目问答至少要能确定项目对象或唯一引用

如果不满足，则必须生成澄清，不允许硬执行。

### 9.6 高风险任务

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

## 10. Tool Calling / Function Call 规则

### 10.1 必须通过 Tool Registry

所有 Agent 可调用工具必须注册到 Tool Registry。

工具不得散落在业务代码中直接调用。

### 10.2 Tool 元数据

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

### 10.3 Tool 调用流程

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

### 10.4 内部工具

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

### 10.5 MCP 规则

MCP 在本项目中属于 Tool / Capability Fabric 的实现方式之一。

要求：

- 所有 MCP 调用必须经过统一的 `mcp gateway/client` 抽象；
- MCP Server 输入输出必须使用结构化 schema；
- MCP 调用必须记录到 `mcp_calls`；
- SQL MCP 必须经过 SQL Guard；
- File MCP 必须走权限过滤；
- 不允许业务代码绕过统一网关直接调用外部服务。

### 10.6 A2A 规则

A2A 在本项目中属于跨 Agent 委托能力。

要求：

- 所有 A2A 调用必须经过统一 A2A Gateway；
- 必须使用 `task envelope / result contract / status contract`；
- 必须支持 trace_id / run_id 透传；
- 必须记录 `a2a_delegations`；
- 第一阶段可先实现“内部 HTTP/JSON 契约版 A2A”；
- 不允许把 A2A 逻辑散落在业务 Agent 中随意拼请求。

---

## 11. RAG 开发规则

### 11.1 检索主链路

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

### 11.2 权限过滤必须前置

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

### 11.3 答案必须可溯源

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

### 11.4 无依据回答规则

如果知识库中没有明确依据，必须回答：

```text
知识库中未找到明确依据，无法基于现有资料给出确定回答。
```

禁止编造制度条款、安全规程、合同规则或经营数据。

---

## 12. SQL Agent 开发规则

### 12.1 SQL 必须经过安全校验

任何 SQL 执行前必须经过 SQL Guard。

### 12.2 禁止 SQL 操作

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

### 12.3 查询限制

必须支持：

- 只读账号
- 自动 LIMIT
- 查询超时
- 返回行数限制
- 表级权限
- 字段级权限
- SQL Audit

### 12.4 SQL 输出

经营分析页面应展示：

- 用户问题
- 生成 SQL
- 安全校验结果
- 查询结果
- 分析结论
- Trace ID

---

## 13. 合同审查开发规则

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

## 14. Human Review 开发规则

### 14.1 触发条件

以下任务必须支持 Human Review：

- 高风险安全生产回答
- 高风险合同审查
- 敏感经营数据查询
- 外部系统高风险调用
- 正式报告发布
- 邮件或工单正式提交

### 14.2 Review 状态

Review 状态包括：

```text
pending
approved
rejected
revised
expired
cancelled
```

### 14.3 Review 数据

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

## 15. Trace 与审计规则

所有关键链路必须记录 Trace。

至少包括：

```text
agent_runs
tool_calls
retrieval_logs
llm_calls
mcp_calls
a2a_delegations
sql_audits
human_reviews
evaluation_tasks
clarification_events
workflow_events
```

每次用户请求必须有唯一：

```text
run_id / trace_id
```

### 15.1 不允许缺失审计的操作

以下操作必须记录：

- Agent 执行
- Tool 调用
- MCP 调用
- A2A 委托
- SQL 查询
- 文档入库
- 合同审查
- Human Review
- Evaluation
- 高风险拒绝
- Clarification 生成
- 任务恢复执行

---

## 16. Evaluation 开发规则

系统需要支持：

- RAG Evaluation
- Agent Evaluation
- SQL Evaluation
- Contract Review Evaluation
- Human Review Trigger Evaluation

评估模块应独立于业务接口，可以通过 API、脚本或 Celery 任务运行。

评估结果必须可持久化。

---

## 17. 前端开发规则

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

## 18. 测试规则

新增核心功能必须补充测试。

### 18.1 单元测试

必须覆盖：

- 权限判断
- Parser
- Chunker
- Retriever
- SQL Guard
- Tool Registry
- Risk Policy
- Agent Router
- Clarification Manager
- Review Manager

### 18.2 集成测试

必须覆盖：

- 文档入库链路
- RAG 问答链路
- SQL 分析链路
- 合同审查链路
- Human Review 链路
- Clarification 链路
- Trace 查询链路

### 18.3 测试命令

如果项目已有测试命令，修改完成后必须运行相关测试。

如果暂时没有完整测试框架，应至少保证新增代码可导入、基础接口可启动。

默认优先在 `tmf_project` 环境下执行测试与启动命令。

---

## 19. Codex 执行任务格式

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

### 19.1 Codex 本轮任务提示词要求

如果任务是由上层设计文档驱动，Codex 应优先遵循：

1. `ARCHITECTURE.md`
2. `AGENT_WORKFLOW.md`
3. `API_DESIGN.md`
4. `DB_DESIGN.md`
5. `PROJECT_STRUCTURE.md`

### 19.2 Codex 不得擅自做的事

- 不得擅自引入未讨论的新重型依赖；
- 不得擅自把单轮接口写成最终版完整业务系统；
- 不得忽略 conversation / run / clarification / review 状态；
- 不得只写“能跑”的代码而破坏分层边界；
- 不得省略核心中文注释。

---

## 20. 禁止事项

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
- 缺少关键槽位时盲猜执行
- 绕过澄清流程直接执行高风险任务
- 编造制度、安全规程、合同条款或经营数据
- 删除已有文档和测试，除非用户明确要求
- 引入未讨论的新重型依赖
- 把 OpenSearch 或 Kafka 作为首期必选组件
- 生成缺少中文注释的核心业务代码
- 生成没有字段中文说明的数据模型
- 生成没有解释关键技术原理的 RAG、Agent、SQL、Tool、MCP、A2A 代码

---

## 21. 当前开发优先级

在正式写完整业务代码前，推荐开发顺序为：

```text
1. 项目目录结构
2. FastAPI 基础骨架
3. 配置系统
4. PostgreSQL + SQLAlchemy
5. 用户、角色、权限基础模型
6. conversations / task_runs / clarification / review 基础模型
7. Redis + Celery
8. API 基础路由与统一响应模型
9. /chat 最小闭环
10. 多轮会话与澄清恢复
11. 文档解析与异步入库
12. BGE-M3 Embedding Gateway
13. Milvus VectorStore
14. Hybrid Search
15. BGE-Reranker
16. LangGraph Agent 基础工作流
17. Tool Registry
18. MCP Gateway
19. Trace 与审计
20. Human Review
21. SQL Agent
22. 合同审查 Agent
23. A2A Gateway
24. Evaluation
25. 前端页面
26. OpenTelemetry + Prometheus + Grafana
```

---

## 22. 输出风格要求

输出要工程化、简洁、明确。

不要只说“已完成”，要说明：

- 做了什么
- 为什么这样做
- 改了哪些文件
- 怎么验证
- 有哪些风险
- 下一步是什么

---

## 23. 当前版本说明

当前 `AGENTS.md` 用于约束 Codex 在本项目中的编码行为。

本版重点强调：

- 与最新架构、工作流、数据库、API、项目骨架文档保持一致；
- MCP 采用 Python 服务 + 统一网关抽象；
- A2A 第一阶段采用内部 HTTP/JSON 契约式网关预留；
- 多轮对话、槽位澄清、恢复执行上升为项目级开发规则；
- API 响应、状态、链路标识统一；
- 中文详细注释与面试友好型代码说明要求继续保持。

后续如 PRD、架构或技术选型发生变化，应同步更新本文件。
