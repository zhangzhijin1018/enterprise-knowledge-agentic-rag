# A2A_LANGGRAPH_MIXED_ARCHITECTURE.md

# “A2A 宏观调度 + LangGraph 微观执行”混合架构说明

---

## 1. 文档定位

本文档解释本项目为什么采用 **A2A 宏观调度 + LangGraph 微观执行** 的混合架构，而不是在两者之间二选一。

当前阶段的目标不是推翻现有“单控制面 + 多业务 Agent + MCP-ready / A2A-ready”架构，而是在这个基础上增量演进：

- 宏观层引入 Supervisor / A2A Gateway / Event Bus-ready
- 微观层以业务专家内部 workflow 的方式接入 LangGraph 样板
- 第一轮只选择经营分析专家作为样板

---

## 2. 核心结论

### 2.1 A2A 不替代 LangGraph

A2A 解决的是：

- 任务交给谁做
- 本地执行还是远程委托
- 如何透传 `run_id / trace_id / parent_task_id`
- 如何统一 `TaskEnvelope / ResultContract`

因此，A2A 负责的是 **宏观调度**。

### 2.2 LangGraph 不替代 A2A

LangGraph 解决的是：

- 单个业务专家内部如何拆节点
- 节点之间如何显式流转状态
- 何时 clarification
- 何时 build_sql / guard_sql / execute_sql
- 何时 summarize / finish

因此，LangGraph 负责的是 **微观执行**。

### 2.3 一句话记忆

- **A2A 管“谁来做”**
- **LangGraph 管“怎么做”**

---

## 3. 当前项目中的角色分工

### 3.1 宏观层

宏观层由以下模块构成：

- `SupervisorService`
- `DelegationController`
- `A2AGateway`
- `EventBus`

职责是：

1. 接收业务请求
2. 识别目标业务专家
3. 决定本地执行还是 A2A-ready 委托
4. 构造 `TaskEnvelope`
5. 标准化 `ResultContract`
6. 记录跨专家协作事件

这一层不负责：

- 经营分析 SQL 的具体执行细节
- 合同条款级审查逻辑
- RAG 检索与重排细节

### 3.2 微观层

微观层由各业务专家内部 workflow 构成。

第一轮只落地：

- `core/agent/workflows/analytics/`

经营分析工作流节点包括：

1. `analytics_entry`
2. `analytics_plan`
3. `analytics_validate_slots`
4. `analytics_clarify`
5. `analytics_build_sql`
6. `analytics_guard_sql`
7. `analytics_execute_sql`
8. `analytics_summarize`
9. `analytics_finish`

---

## 4. Redis Streams 与 PostgreSQL 的职责边界

### 4.1 Redis Streams 的定位

Redis Streams 在本项目中的定位是：

- 事件流总线
- 异步分发通道
- A2A-ready 的事件媒介

适合承载：

- 任务提交事件
- 任务完成事件
- 委托事件
- 后续异步恢复与通知事件

### 4.2 PostgreSQL 的定位

PostgreSQL 仍然是权威状态存储与审计存储，负责保存：

- `task_run`
- `slot_snapshot`
- `clarification_event`
- `review`
- `sql_audit`
- `analytics_result`

### 4.3 为什么必须分开

原因很明确：

1. Redis Streams 更适合描述“发生了什么事件”
2. PostgreSQL 更适合回答“系统现在的权威状态是什么”
3. 恢复执行、审计追踪、问题排查都不能依赖仅存在于事件流中的临时消息

---

## 5. 第一轮增量改造范围

本轮只做以下四类改造：

1. 文档改造：明确宏观/微观边界
2. 目录骨架：补齐 supervisor / workflow / a2a / events
3. A2A 契约：统一 `TaskEnvelope / ResultContract / StatusContract`
4. 经营分析样板：把 analytics 主链整理成 LangGraph-ready workflow

本轮不做：

- 全量远程 A2A 分布式生产系统
- 所有业务专家一起迁移到 LangGraph
- 合同审查主链大重构

---

## 6. 当前目录落点

```text
core/agent/supervisor/
core/agent/workflows/
core/agent/workflows/analytics/
core/tools/a2a/
core/tools/a2a/contracts/
core/tools/a2a/gateway/
core/runtime/events/
```

这些目录分别对应：

- `supervisor/`：宏观调度层
- `workflows/`：业务专家微观执行层
- `a2a/contracts/`：统一跨专家委托契约
- `a2a/gateway/`：本地 / 远程委托边界
- `runtime/events/`：事件总线抽象

---

## 7. 为什么经营分析适合作为第一批样板

经营分析当前已经有比较清晰的执行边界：

- clarification 分层
- schema-aware planner
- SQL Builder
- SQL Guard
- SQL Gateway / SQL MCP Server
- governance / review / export

所以它非常适合先作为 LangGraph 微观执行样板，用来验证：

- 结构化 state 是否合理
- 节点划分是否清晰
- 现有 service 是否能平滑复用

---

## 8. 下一阶段演进路线

建议顺序：

1. 继续让 analytics workflow 与现有 `analytics/query` 主链更深度接线
2. 把 clarification reply 恢复能力接到 workflow 恢复执行
3. 把 Event Bus 从 in-memory 升级到 Redis Streams
4. 再逐步选择下一个业务专家做 workflow 样板

---

## 9. 当前阶段可如何对外描述

当前项目已经可以描述为：

> 一个采用 **Supervisor / A2A Gateway 做宏观调度**、采用 **业务专家内部 Workflow 做微观执行**、并以 **经营分析专家作为第一批 LangGraph 样板** 的企业级 Agent 平台。
