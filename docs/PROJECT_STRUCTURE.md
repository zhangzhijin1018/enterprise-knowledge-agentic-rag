# PROJECT_STRUCTURE.md

# 新疆能源集团知识与生产经营智能 Agent 平台
## 项目代码骨架设计文档

---

## 1. 文档定位

本文档用于把 `ARCHITECTURE.md`、`AGENT_WORKFLOW.md`、`DB_DESIGN.md`、`API_DESIGN.md` 进一步落到：

- 项目目录结构；
- 后端代码分层；
- FastAPI 路由骨架；
- Pydantic Schema 骨架；
- Service / Repository / Agent / Tool 分层边界；
- 第一阶段最小闭环实现顺序。

这份文档的目标不是讲概念，而是让你可以开始真正搭项目。

---

## 2. 第一阶段代码分层原则

### 2.1 API 层只负责协议，不负责业务编排

API 路由层只负责：

- 收请求
- 参数校验
- 调 Service
- 返回响应

不在 API 层写：

- 复杂业务逻辑
- SQL
- Agent 编排
- MCP 调用细节

### 2.2 Service 层负责业务用例编排

Service 层负责：

- 业务流程组织
- 权限校验串联
- 调用 Agent Control Plane
- 组织响应对象

### 2.3 Repository 层负责数据访问

Repository 只做：

- ORM 查询
- 持久化
- 简单查询封装

不做：

- 复杂业务判断
- 风险决策
- 路由决策

### 2.4 Agent 层负责智能编排

Agent 层负责：

- 路由
- 工作流
- 多轮上下文
- 澄清
- 恢复执行
- 专家调度

### 2.5 Tool 层负责执行

Tool / Capability 层负责：

- RAG 检索
- Rerank
- SQL MCP
- File MCP
- Report MCP
- A2A 调用

---

## 3. 推荐项目目录结构

```text
enterprise-knowledge-agentic-rag/
├── apps/
│   ├── api/
│   │   ├── main.py
│   │   ├── deps.py
│   │   ├── middleware/
│   │   │   ├── request_context.py
│   │   │   ├── trace_middleware.py
│   │   │   └── exception_handler.py
│   │   ├── routers/
│   │   │   ├── chat.py
│   │   │   ├── conversations.py
│   │   │   ├── clarifications.py
│   │   │   ├── documents.py
│   │   │   ├── contracts.py
│   │   │   ├── analytics.py
│   │   │   ├── reports.py
│   │   │   ├── reviews.py
│   │   │   ├── traces.py
│   │   │   └── evaluations.py
│   │   └── schemas/
│   │       ├── common.py
│   │       ├── chat.py
│   │       ├── conversation.py
│   │       ├── clarification.py
│   │       ├── document.py
│   │       ├── contract.py
│   │       ├── analytics.py
│   │       ├── report.py
│   │       ├── review.py
│   │       ├── trace.py
│   │       └── evaluation.py
│   └── worker/
│       ├── celery_app.py
│       └── tasks/
│           ├── ingestion_tasks.py
│           ├── report_tasks.py
│           ├── review_tasks.py
│           └── archive_tasks.py
│
├── core/
│   ├── common/
│   │   ├── enums.py
│   │   ├── exceptions.py
│   │   ├── ids.py
│   │   ├── pagination.py
│   │   └── response.py
│   ├── config/
│   │   ├── settings.py
│   │   └── logging.py
│   ├── security/
│   │   ├── auth.py
│   │   ├── context.py
│   │   ├── policy_engine.py
│   │   └── risk_engine.py
│   ├── database/
│   │   ├── base.py
│   │   ├── session.py
│   │   ├── mixins.py
│   │   └── models/
│   │       ├── iam.py
│   │       ├── knowledge.py
│   │       ├── conversation.py
│   │       ├── runtime.py
│   │       ├── governance.py
│   │       ├── logs.py
│   │       └── evaluation.py
│   ├── repositories/
│   │   ├── conversation_repository.py
│   │   ├── document_repository.py
│   │   ├── task_run_repository.py
│   │   ├── review_repository.py
│   │   ├── trace_repository.py
│   │   └── audit_repository.py
│   ├── services/
│   │   ├── chat_service.py
│   │   ├── conversation_service.py
│   │   ├── clarification_service.py
│   │   ├── document_service.py
│   │   ├── contract_review_service.py
│   │   ├── analytics_service.py
│   │   ├── report_service.py
│   │   ├── review_service.py
│   │   ├── trace_service.py
│   │   └── evaluation_service.py
│   ├── agent/
│   │   ├── control_plane/
│   │   │   ├── task_router.py
│   │   │   ├── workflow_engine.py
│   │   │   ├── state_manager.py
│   │   │   ├── clarification_manager.py
│   │   │   ├── review_manager.py
│   │   │   └── result_aggregator.py
│   │   ├── mesh/
│   │   │   ├── policy_agent.py
│   │   │   ├── safety_agent.py
│   │   │   ├── equipment_agent.py
│   │   │   ├── energy_agent.py
│   │   │   ├── contract_agent.py
│   │   │   ├── analytics_agent.py
│   │   │   ├── project_agent.py
│   │   │   └── report_agent.py
│   │   └── contracts/
│   │       ├── task_contracts.py
│   │       ├── result_contracts.py
│   │       └── state_contracts.py
│   ├── tools/
│   │   ├── rag/
│   │   │   ├── retriever.py
│   │   │   ├── reranker.py
│   │   │   └── citation_builder.py
│   │   ├── mcp/
│   │   │   ├── sql_mcp_client.py
│   │   │   ├── file_mcp_client.py
│   │   │   ├── report_mcp_client.py
│   │   │   └── api_mcp_client.py
│   │   ├── a2a/
│   │   │   ├── a2a_client.py
│   │   │   └── registry_client.py
│   │   └── local/
│   │       ├── parser.py
│   │       ├── ocr.py
│   │       └── exporter.py
│   ├── review/
│   │   ├── hooks.py
│   │   ├── interruptor.py
│   │   └── recovery.py
│   └── observability/
│       ├── tracing.py
│       ├── metrics.py
│       └── audit_logger.py
│
├── tests/
│   ├── api/
│   ├── services/
│   ├── agent/
│   ├── repositories/
│   └── integration/
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── AGENT_WORKFLOW.md
│   ├── DB_DESIGN.md
│   ├── API_DESIGN.md
│   └── PROJECT_STRUCTURE.md
│
├── pyproject.toml
├── README.md
└── .env.example
```

---

## 4. FastAPI 路由骨架建议

## 4.1 `apps/api/main.py`

职责：

- 创建 FastAPI app
- 注册中间件
- 注册路由
- 初始化异常处理
- 挂健康检查接口

建议：

- 不写复杂业务逻辑
- 不在这里直接连数据库
- 不在这里直接 new 大模型客户端

## 4.2 第一批路由文件

### `routers/chat.py`
负责：

- `POST /api/v1/chat`

### `routers/conversations.py`
负责：

- `GET /api/v1/conversations`
- `GET /api/v1/conversations/{conversation_id}/messages`
- `POST /api/v1/conversations/{conversation_id}/cancel`

### `routers/clarifications.py`
负责：

- `POST /api/v1/clarifications/{clarification_id}/reply`

### `routers/documents.py`
负责：

- `POST /api/v1/documents/upload`
- `GET /api/v1/documents/{document_id}`

### `routers/contracts.py`
负责：

- `POST /api/v1/contracts/review`
- `GET /api/v1/contracts/reviews/{run_id}`

### `routers/analytics.py`
负责：

- `POST /api/v1/analytics/query`
- `GET /api/v1/analytics/runs/{run_id}`

### `routers/reviews.py`
负责：

- `GET /api/v1/reviews`
- `GET /api/v1/reviews/{review_id}`
- `POST /api/v1/reviews/{review_id}/decision`

### `routers/traces.py`
负责：

- `GET /api/v1/traces/{run_id}`

---

## 5. Pydantic Schema 骨架建议

## 5.1 通用 schema

建议先做：

### `schemas/common.py`

包含：

- `SuccessResponse`
- `ErrorResponse`
- `MetaInfo`
- `PaginationRequest`
- `PaginationResponse`

## 5.2 chat schema

### `schemas/chat.py`

建议至少包含：

- `ChatRequest`
- `ChatAnswerData`
- `ChatClarificationData`
- `ChatResponse`

## 5.3 conversation schema

### `schemas/conversation.py`

建议至少包含：

- `ConversationItem`
- `ConversationListResponse`
- `ConversationMessageItem`
- `ConversationMessagesResponse`

## 5.4 clarification schema

### `schemas/clarification.py`

建议至少包含：

- `ClarificationReplyRequest`
- `ClarificationReplyResponse`

## 5.5 contract / analytics / review schema

这些都按：

```text
Request
ResponseData
Response
DetailResponse
```

四层拆开，不要把所有字段都堆在一个 schema 里。

---

## 6. Service 层骨架建议

## 6.1 ChatService

职责：

- 接收问答请求
- 调用权限上下文构建
- 调用 Agent Control Plane
- 组织问答结果 / 澄清结果 / 审核结果

不负责：

- ORM 明细查询
- SQL 拼接
- RAG 细节

## 6.2 ConversationService

职责：

- 查询会话列表
- 查询会话消息
- 取消会话
- 会话标题生成（后续）

## 6.3 ClarificationService

职责：

- 接收用户补充信息
- 更新 clarification event
- 更新 slot snapshot
- 恢复 task run

## 6.4 DocumentService

职责：

- 上传文档
- 写入文档元数据
- 发起异步解析任务

## 6.5 ContractReviewService

职责：

- 创建合同审查任务
- 查询审查结果
- 返回风险项与报告信息

## 6.6 AnalyticsService

职责：

- 发起经营分析任务
- 承接澄清
- 返回分析结果或任务状态

## 6.7 ReviewService

职责：

- 查询审核任务
- 查询审核详情
- 提交审核结论
- 触发恢复执行

---

## 7. Repository 层骨架建议

第一阶段建议至少先落：

### `conversation_repository.py`
- `get_by_id`
- `get_by_uuid`
- `list_by_user`
- `save_message`
- `get_messages`

### `task_run_repository.py`
- `create_run`
- `get_by_run_id`
- `update_status`
- `update_output_snapshot`

### `document_repository.py`
- `create_document`
- `get_by_document_id`
- `update_parse_status`
- `update_index_status`

### `review_repository.py`
- `create_review`
- `get_by_review_id`
- `list_pending_reviews`
- `update_review_status`

### `audit_repository.py`
- `create_sql_audit`
- `create_mcp_call`
- `create_llm_call`

---

## 8. Agent Control Plane 骨架建议

## 8.1 TaskRouter

职责：

- 判断任务属于 chat / contract / analytics / report
- 判断是否为多轮延续
- 判断是否进入澄清流程

## 8.2 WorkflowEngine

职责：

- 驱动状态迁移
- 调节点执行
- 管理主状态 / 子状态
- 处理中断与恢复

## 8.3 StateManager

职责：

- 保存 task_run
- 保存 workflow_event
- 保存 slot_snapshot
- 保存 clarification_event
- 恢复状态

## 8.4 ClarificationManager

职责：

- 判断是否缺最小可执行槽位
- 生成澄清问题
- 接收用户补充
- 触发恢复执行

## 8.5 ReviewManager

职责：

- 判断是否需要 Human Review
- 创建 review
- 等待 review
- 审核通过后恢复
- 审核拒绝后终止

## 8.6 ResultAggregator

职责：

- 统一拼接答案
- 统一拼接 citation
- 统一拼接表格 / 风险项 / 报告链接

---

## 9. 第一阶段最小闭环实现顺序

建议不要并行乱写，按下面顺序推进。

### 第 1 步：API 基础设施
先做：

- `main.py`
- 基础 router 注册
- 统一响应模型
- 统一异常处理
- request_id / trace_id 中间件

### 第 2 步：数据库与 Session 基础设施
先搭：

- SQLAlchemy Base
- Session 管理
- Repository 基类
- 核心模型导入

### 第 3 步：多轮会话最小能力
先做：

- conversations
- conversation_messages
- conversation_memory
- task_runs

### 第 4 步：`/chat` 最小闭环
做到：

- 接收 query
- 创建 conversation / task_run
- 走最小 ChatService
- 返回 mock 或最小真实结果
- 落库 message / run

### 第 5 步：澄清能力
做到：

- slot_snapshot
- clarification_event
- `/clarifications/{id}/reply`
- 恢复原任务

### 第 6 步：文档上传与合同审查起步
做到：

- `/documents/upload`
- 文档元数据落库
- `/contracts/review`
- 创建合同审查任务

### 第 7 步：经营分析起步
做到：

- `/analytics/query`
- 最小澄清
- 最小 SQL MCP 调用占位

### 第 8 步：Human Review 起步
做到：

- review 表
- review 列表
- review decision
- 审核后恢复

---

## 10. 第一阶段建议先写的实际代码文件

如果你现在马上开始写代码，我建议先写这 15 个文件：

```text
apps/api/main.py
apps/api/routers/chat.py
apps/api/routers/conversations.py
apps/api/routers/clarifications.py
apps/api/schemas/common.py
apps/api/schemas/chat.py
apps/api/schemas/conversation.py
apps/api/schemas/clarification.py

core/config/settings.py
core/database/base.py
core/database/session.py
core/database/models/conversation.py
core/database/models/runtime.py
core/repositories/conversation_repository.py
core/repositories/task_run_repository.py
core/services/chat_service.py
```

这批写完，项目就从“文档阶段”进入“真正代码阶段”了。

---

## 11. 你和 Codex 的配合方式建议

你现在最适合的节奏是：

### 第一步
先让我给你每一批代码文件的“骨架版”。

### 第二步
你把骨架放进本地项目，交给 Codex 补全。

### 第三步
你把 Codex 写出来的代码贴回来，我帮你做：

- 架构对齐检查
- 业务边界检查
- 注释检查
- 异常处理检查
- 可维护性检查

也就是说：

```text
我负责设计、把控边界、给骨架、做审查
Codex 负责高效生成重复性代码
你负责在本地集成、运行、提交
```

---

## 12. 当前版本说明

本文档已经覆盖：

- 推荐项目目录结构
- FastAPI 路由骨架
- Pydantic Schema 骨架
- Service / Repository / Agent / Tool 分层建议
- 第一阶段最小闭环实现顺序
- 第一批最应该先写的代码文件

这版已经可以直接作为下一步“开始搭项目代码骨架”的依据。
