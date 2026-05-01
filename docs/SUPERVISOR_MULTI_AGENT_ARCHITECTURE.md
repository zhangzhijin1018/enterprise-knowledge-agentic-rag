# Supervisor + 多业务 Agent + LangGraph Workflow + MCP/A2A 混合架构设计文档

> **副标题：A2A 宏观调度 + LangGraph 微观执行的混合 Agent 架构**
>
> 基于当前仓库真实代码实现，阐述 Supervisor 宏观路由 ⇄ LangGraph 微观状态机 ⇄ MCP 工具接入的完整协作机制。

---

## 目录

1. [整体架构概述](#一整体架构概述)
2. [宏观调度层：Supervisor + A2A](#二宏观调度层supervisor--a2a)
3. [微观执行层：LangGraph StateGraph + ReAct 状态机](#三微观执行层langgraph-stategraph--react-状态机)
4. [工具车间：MCP 协议化能力接入](#四工具车间mcp-协议化能力接入)
5. [代码对照说明](#五代码对照说明)
6. [实际案例分析](#六实际案例分析)
7. [状态机设计与图编排详解](#七状态机设计与图编排详解)
8. [附录](#附录)

---

## 一、整体架构概述

### 1.1 核心理念：A2A 宏观调度 + LangGraph 微观执行

```
┌─────────────────────────────────────────────────────┐
│              宏观调度层（Supervisor + A2A）            │
│  决定"哪个 Agent 处理这个请求"                            │
│  协议：TaskEnvelope / ResultContract / StatusContract │
│  粒度：按业务域路由                                     │
└───────────────────────┬─────────────────────────────┘
                        │ TaskEnvelope
                        ▼
┌─────────────────────────────────────────────────────┐
│              微观执行层（LangGraph StateGraph）         │
│  决定"这个 Agent 内部怎么一步步执行"                       │
│  协议：节点 → 条件边 → 重试/降级 → 存储分层                │
│  粒度：按业务步骤编排（9 节点状态机）                      │
└─────────────────────────────────────────────────────┘
```

**分层原因**：宏观层不需要知道 SQL Guard 的内部细节；微观层不关心请求来自 Supervisor 还是 API 直接调用。两层可以独立演进。

### 1.2 九层架构全景图

```
Layer 1  用户工作台         Web / 第三方系统
Layer 2  门禁与风控         认证（Auth）、鉴权（RBAC）
Layer 3  业务调度台         Chat / Contract / Analytics Service
Layer 4  智能总指挥台       ★ Supervisor：TaskRouter + A2A Gateway（宏观调度）
Layer 5  业务专家团队       ★ Analytics/Contract Agent → LangGraph Workflow（微观执行）
Layer 6  工具车间           MCP（SQL/File/Report）/ 本地Tool / A2A远程Agent
Layer 7  知识与数据底座      PostgreSQL / SQLite / 向量库
Layer 8  监督与保障         Human Review / Trace / SQL Audit
Layer 9  运行支撑           Celery / Async Runner / 部署监控
```

### 1.3 核心数据流转

```
用户："查询新疆区域 2024 年 3 月的发电量"
  │
  ├─ API 路由 → AnalyticsService.submit_query()
  │     └─ use_workflow=True → WorkflowAdapter.execute_query()
  │
  └─ StateGraph（9 节点）:
        analytics_entry      → 会话管理
        analytics_plan        → 槽位提取（含可选 ReAct 子循环）
        analytics_validate     → 条件分支
           ├─ 槽位不足 → analytics_clarify → 返回追问
           └─ 槽位满足 → analytics_build_sql → analytics_guard_sql
                          → analytics_execute_sql → [SQL MCP]
                          → analytics_summarize（脱敏/摘要/洞察/报告）
                          → analytics_finish（存储分层/返回）
```

### 1.4 关键组件对照

| 组件 | 代码位置 |
|---|---|
| Supervisor / TaskRouter | [task_router.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/control_plane/task_router.py) |
| A2A Contract | [core/tools/a2a/contracts.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/tools/a2a/contracts.py) |
| LangGraph 状态定义 | [state.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/state.py) |
| LangGraph 节点实现 | [nodes.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/nodes.py) |
| LangGraph 图编排 | [graph.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/graph.py) |
| 宏观↔微观衔接 | [adapter.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/adapter.py) |
| SQL MCP Server | [sql_mcp_server.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/tools/mcp/sql_mcp_server.py) |
| Report MCP Server | [report_mcp_server.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/tools/mcp/report_mcp_server.py) |

---

## 二、宏观调度层：Supervisor + A2A

### 2.1 Supervisor 职责边界

Supervisor 是"路由者"而非"思考者"——它只做确定性规则决策：

| 做什么 | 不做什么 |
|---|---|
| 根据问题内容路由到业务 Agent | 不生成 SQL |
| 创建 TaskEnvelope（标准化任务契约） | 不执行检索 |
| 跟踪任务生命周期 | 不做脱敏 |
| 管理 Agent Card 注册 | 不做 LLM 自由推理 |

### 2.2 TaskRouter 规则路由

[task_router.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/control_plane/task_router.py#L35-L85)：

```
用户问句
  ├─ 包含"制度/政策/规程" → route=policy_qa, agent=policy_agent
  ├─ 包含"分析/统计/指标/经营/趋势" + 无已知指标 → need_clarification=true
  └─ 默认 → route=general_qa
```

**为什么不用 LLM 路由**：可解释（明确规则依据）、稳定（相同输入永远相同输出）、不依赖 LLM 可用性。

### 2.3 A2A 契约模型

```python
# 宏观调度契约
TaskEnvelope(
    task_id="task_001",          # 任务唯一标识
    task_type="analytics",       # 任务类型
    parent_task_id="parent_001", # 父任务（委托链追踪）
    trace_id="tr_001",           # 全链路追踪
    payload={"query": "..."},    # 输入内容
    context={"user_id": 1201},   # 用户上下文
)

StatusContract(
    task_id="task_001",
    status="executing",          # pending/executing/succeeded/failed
    sub_status="building_sql",   # 细粒度子状态
)

ResultContract(
    task_id="task_001",
    status="succeeded",
    data={...},                  # 结果数据
    metadata={"latency_ms": 45}, # 执行元数据
)
```

### 2.4 宏观↔微观衔接点：WorkflowAdapter

[adapter.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/adapter.py) 是两层之间的关键适配层：

```python
class AnalyticsWorkflowAdapter:
    def execute_query(self, *, query, user_context, ...) -> dict:
        """对上层暴露"提交经营分析请求"语义，隐藏 graph/node 细节。"""

    def to_result_contract(self, *, envelope, response, ...) -> ResultContract:
        """将 workflow 业务返回收敛为 A2A ResultContract。"""

    def resume_from_clarification(self, *, query, run_id, ...) -> dict:
        """从 clarification 补槽结果恢复 StateGraph 执行。"""
```

**为什么必须用 Adapter**：API 层不应感知 LangGraph 节点细节；Service 层承担太多兼容职责，直接塞 graph 会职责混乱；Adpater 可平滑切换"直接编排→workflow-first"而不改 API 契约。

---

## 三、微观执行层：LangGraph StateGraph + ReAct 状态机

### 3.1 为什么用 LangGraph

| LangGraph 特性 | 如何匹配 |
|---|---|
| 显式节点定义 | 每个业务步骤一个节点（plan/validate/build/guard/execute/summarize） |
| 条件边 | 槽位不足→clarify 分支；槽位满足→SQL 执行分支 |
| 状态流转 | `AnalyticsWorkflowState` 在 9 个节点间传递 |
| 异常可追踪 | 即使节点失败，state 仍保存当前 stage/outcome |

### 3.2 经营分析微观状态机：9 节点 + 状态字段

#### 状态定义（AnalyticsWorkflowState）

[state.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/state.py) 定义了完整微观状态：

```
AnalyticsWorkflowState（TypedDict）
├── 输入态字段
│   ├── query             : str          ← 用户原始问题
│   ├── conversation_id   : str | None   ← 会话 ID
│   ├── run_id / trace_id : str | None   ← 权威运行 ID / 追踪 ID
│   ├── output_mode       : str          ← lite/standard/full
│   └── user_context      : UserContext  ← 用户/角色/权限/部门
│
├── 微观状态机字段
│   ├── workflow_stage    : AnalyticsWorkflowStage  ← 当前阶段
│   ├── workflow_outcome  : AnalyticsWorkflowOutcome← 方向性结果
│   ├── next_step         : str                     ← 下个节点
│   ├── clarification_needed : bool                 ← 是否需澄清
│   └── resume_from_clarification : bool            ← 是否从澄清恢复
│
├── 中间态业务上下文
│   ├── plan              : AnalyticsPlan  ← 槽位规划结果
│   ├── sql_bundle        : dict           ← SQL 构造结果
│   ├── guard_result      : SQLGuardResult ← 安全检查结果
│   ├── execution_result  : Response       ← SQL 执行结果
│   ├── masking_result    : MaskingResult  ← 脱敏结果
│   └── analytics_result  : Result         ← 统一结果对象
│
├── 可观测性字段
│   ├── timing            : dict    ← 各阶段耗时
│   ├── retry_count / retry_history ← 重试记录
│   └── degraded / degraded_features← 降级记录
│
└── ReAct 局部状态
    ├── react_used         : bool   ← 是否触发 ReAct
    ├── react_steps        : list   ← ReAct 步骤摘要
    └── react_fallback_used: bool   ← ReAct 失败后是否回退
```

#### 执行阶段枚举

```python
class AnalyticsWorkflowStage(str, Enum):
    ANALYTICS_ENTRY     = "analytics_entry"       # 输入标准化
    ANALYTICS_PLAN       = "analytics_plan"        # 意图识别+槽位
    ANALYTICS_VALIDATE   = "analytics_validate_slots" # 槽位校验
    ANALYTICS_CLARIFY    = "analytics_clarify"     # 澄清追问
    ANALYTICS_BUILD_SQL  = "analytics_build_sql"   # SQL 构造
    ANALYTICS_GUARD_SQL  = "analytics_guard_sql"   # SQL 安全检查
    ANALYTICS_EXECUTE_SQL= "analytics_execute_sql" # SQL 执行
    ANALYTICS_SUMMARIZE  = "analytics_summarize"   # 脱敏+摘要+生成
    ANALYTICS_FINISH     = "analytics_finish"      # 存储分层+返回
```

### 3.3 StateGraph 编排

[graph.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/graph.py) 的 `_build_graph()`：

```
                    ┌──────────────────┐
                    │ analytics_entry  │  ← 入口：输入校验+会话管理
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │ analytics_plan   │  ← 意图识别+槽位（含可选 ReAct）
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │ anal_valid_slots │  ← 条件分支：满足最小条件？
                    └────────┬─────────┘
              ┌──────────────┼──────────────┐
              ▼                             ▼
     ┌────────────────┐          ┌──────────────────┐
     │analytics_clarify│          │analytics_build_sql│
     └────────┬───────┘          └────────┬─────────┘
              ▼                            ▼
     ┌────────────────┐          ┌──────────────────┐
     │analytics_finish│ ←返回澄清 │analytics_guard_sql│ ← 9层安全检查
     └────────────────┘          └────────┬─────────┘
                                          ▼
                                 ┌──────────────────┐
                                 │analytics_execute_ │ ← SQL MCP 执行
                                 │      sql          │
                                 └────────┬─────────┘
                                          ▼
                                 ┌──────────────────┐
                                 │ analytics_summarize│ ← 脱敏+摘要+洞察+报告
                                 └────────┬─────────┘
                                          ▼
                                 ┌──────────────────┐
                                 │ analytics_finish │ ← 轻快照+重结果+返回
                                 └──────────────────┘
```

**关键条件边**（`analytics_validate_slots` 之后）：

```python
def _route_after_validation(state):
    return state.get("next_step", "analytics_build_sql")
# 槽位满足 → build_sql；槽位不足 → clarify
```

### 3.4 ReAct Planning 子循环（plan 节点内部）

[react/planner.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/react/planner.py) 只在 `analytics_plan` 节点内部运行：

```
analytics_plan 节点
  ├─ AnalyticsReactPlanningPolicy 判断：问题复杂度 > 阈值 → 触发 ReAct
  │
  ├─ 如触发 ReAct（最多 3 步）：
  │   Step 1: thought → action(metric_catalog_lookup) → observation
  │   Step 2: thought → action(schema_registry_lookup)  → observation
  │   Step 3: action(finish) → final_plan_candidate
  │
  ├─ 如 ReAct 失败：fallback → 规则 Planner（不中断主流程）
  └─ 输出：AnalyticsPlan（结构化槽位）
```

**ReAct 关键边界**：不生成 SQL、不执行 SQL、不绕过 Guard、输出必须经 Validator 校验。

### 3.5 重试策略

[retry_policy.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/retry_policy.py) 节点级策略：

| 节点 | 最大尝试 | 退避 | 可重试错误 |
|---|---|---|---|
| analytics_build_sql | 2 | 20ms | RuntimeError |
| analytics_execute_sql | 2 | 50ms | TimeoutError, ConnectionError, SQLGatewayExecutionError |
| analytics_summarize | 2 | 20ms | RuntimeError |

**不可重试**：SQL Guard blocked（治理拒绝）、权限失败。

### 3.6 降级策略

[degradation.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/degradation.py)：

| 可降级（温和失败） | 不可降级（必须成功或硬失败） |
|---|---|
| chart_spec 生成失败 | SQL 执行失败 |
| insight_cards 生成失败 | SQL Guard 拦截 |
| report_blocks 生成失败 | 权限/数据范围治理失败 |

降级后 state 记录 `degraded=True, degraded_features=[...]`，前端据此显示"部分结果可用"。

---

## 四、工具车间：MCP 协议化能力接入

### 4.1 MCP 在架构中的定位

```
经营分析 Agent（微观 Workflow）
  ├─ SQL 执行 → SQLGateway → SQLMCPServer（进程内 MCP）→ 只读 SQL
  └─ 报告生成 → ReportGateway → ReportMCPServer（进程内 MCP）→ 模板渲染
```

### 4.2 MCP 契约示例

```python
# SQL
SQLReadQueryRequest(data_source="local_analytics", sql="SELECT ... LIMIT 500",
                     timeout_ms=3000, row_limit=500, trace_id="tr_001")
# 响应
SQLReadQueryResponse(data_source="local_analytics", db_type="sqlite",
                      columns=["station","total_value"],
                      rows=[{"station":"哈密电站","total_value":4200}],
                      row_count=4, latency_ms=45)
```

### 4.3 MCP vs A2A 边界

| | MCP | A2A |
|---|---|---|
| 场景 | 工具级能力接入 | Agent 级协作委托 |
| 交互 | 请求-响应 | TaskEnvelope→Status→Result |
| 粒度 | 单个工具调用 | 完整子任务 |
| 示例 | SQL MCP 执行查询 | 委托远程分析 Agent 完成分析 |

---

## 五、代码对照说明

### 5.1 宏观调度层

| 组件 | 源文件 | 关键入口 |
|---|---|---|
| Supervisor / TaskRouter | [task_router.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/control_plane/task_router.py) | `TaskRouter.route()` |
| A2A Contract | [core/tools/a2a/contracts.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/tools/a2a/contracts.py) | `TaskEnvelope`/`ResultContract` |
| A2A Gateway | [core/tools/a2a/gateway.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/tools/a2a/gateway.py) | `A2AGateway.dispatch()` |
| Workflow Adapter | [adapter.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/adapter.py) | `execute_query()` / `to_result_contract()` |

### 5.2 微观执行层

| 组件 | 源文件 | 关键入口 |
|---|---|---|
| 状态定义 | [state.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/state.py) | `AnalyticsWorkflowState` |
| 节点实现 | [nodes.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/nodes.py) | `AnalyticsWorkflowNodes`(9方法) |
| 图编排 | [graph.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/graph.py) | `AnalyticsLangGraphWorkflow._build_graph()` |
| ReAct Planner | [react/planner.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/react/planner.py) | `AnalyticsReactPlanner.plan()` |
| ReAct Policy | [react/policy.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/react/policy.py) | `should_use_react()` |
| 重试/降级 | [retry_policy.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/retry_policy.py) / [degradation.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/degradation.py) | `RetryController` / `DegradationController` |

### 5.3 平台服务层

| 组件 | 源文件 |
|---|---|
| 主编排服务 | [analytics_service.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/services/analytics_service.py) |
| 导出服务 | [analytics_export_service.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/services/analytics_export_service.py) |
| 澄清服务 | [clarification_service.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/services/clarification_service.py) |

### 5.4 工具车间层

| 组件 | 源文件 |
|---|---|
| SQL Gateway | [sql_gateway.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/tools/sql/sql_gateway.py) |
| SQL MCP Server/Contract | [sql_mcp_server.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/tools/mcp/sql_mcp_server.py) / [sql_mcp_contracts.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/tools/mcp/sql_mcp_contracts.py) |
| Report MCP Server/Contract | [report_mcp_server.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/tools/mcp/report_mcp_server.py) / [report_mcp_contracts.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/tools/mcp/report_mcp_contracts.py) |

---

## 六、实际案例分析

### 案例 1：简单查询完整链路

> **用户**："查询新疆区域 2024 年 3 月的发电量，看各电站排名"
> **期望**：电站排名 + 柱状图 + 排名洞察

#### 宏观层路由

```
POST /api/v1/analytics/query
  → AnalyticsService.submit_query()
    → use_workflow=True → WorkflowAdapter.execute_query()
```

#### 微观 StateGraph 执行（9 节点逐步追踪）

**节点 1：analytics_entry**
- 校验 query 非空
- 创建/复用 conversation
- state["workflow_stage"] = ANALYTICS_ENTRY
- state["workflow_outcome"] = CONTINUE

**节点 2：analytics_plan**
- SemanticResolver 解析：
  → metric="发电量", time_range={label:"2024年3月",start:"2024-03-01",end:"2024-03-31"}, org_scope={value:"新疆区域"}, group_by="station"
- SlotValidator：missing_slots=[], conflict_slots=[], is_executable=true
- 未触发 ReAct（问题足够明确，规则可处理）

**节点 3：analytics_validate_slots**
- is_executable=true → state["next_step"] = "analytics_build_sql"
- 条件边：走 build_sql 分支

**节点 4：analytics_build_sql**
- SQLBuilder.build(slots, department_code="analytics-center")
- 输出：
```sql
SELECT station, SUM(power_generation) AS total_value
FROM analytics_metrics_daily
WHERE date >= '2024-03-01' AND date <= '2024-03-31'
  AND org_region = '新疆区域' AND department_code = 'analytics-center'
GROUP BY station ORDER BY total_value DESC
```
- timing["sql_build_ms"] = 1.3

**节点 5：analytics_guard_sql**
- SQLGuard 9 层校验全部 PASS
- 自动补 LIMIT 500
- is_safe=true, checked_sql 含 LIMIT

**节点 6：analytics_execute_sql**
- SQLGateway → SQLMCPServer → 执行
- 返回 4 行数据（哈密 4200 / 吐鲁番 3100 / 北疆 2900 / 南疆 2600）
- row_count=4, latency_ms=45

**节点 7：analytics_summarize**
- DataMaskingService：station 敏感字段脱敏（"哈密电站"→"哈***站"）
- Summary："已完成'发电量'在 2024年3月 范围内的排名查询，当前返回 4 行结果"
- Chart Spec：{chart_type:"bar",title:"发电量station分布",x_field:"station",y_field:"total_value"}
- Insight Cards：[{type:"ranking",summary:"排名第一的是 哈***站，数值为 4200"}]
- Report Blocks：8 个标准 block（overview/key_findings/ranking/data_table/chart/...）

**节点 8：analytics_finish**
- 轻快照 → task_run.output_snapshot（summary + slots + row_count + latency_ms + governance_decision）
- 重结果 → analytics_result_repository（tables + insight_cards + report_blocks + chart_spec）
- 构造 ResultContract → 返回

#### 最终响应（output_mode=standard）

```json
{
  "data": {
    "run_id": "run_200",
    "summary": "已完成'发电量'在2024年3月范围内的排名查询，当前返回 4 行结果。",
    "row_count": 4, "latency_ms": 45,
    "chart_spec": {"chart_type":"bar","title":"发电量station分布"},
    "insight_cards": [{"title":"发电量station排名洞察","type":"ranking","summary":"排名第一的是 哈***站，数值为 4200"}],
    "masked_fields": ["station"],
    "timing_breakdown": {"sql_build_ms":1.3,"sql_guard_ms":0.5,"sql_execute_ms":45.0,"masking_ms":0.3}
  },
  "meta": {"status":"succeeded"}
}
```

### 案例 2：缺指标 → 澄清 → 恢复执行

> **第一次**："帮我看一下新疆区域上个月的情况"
> **澄清**："你想看哪个指标？发电量、收入、成本、利润还是产量？"
> **第二次**："看发电量"

#### 第一次请求

```
[analytics_plan]
  SemanticResolver → metric=null, time_range=上个月 ✓, org_scope=新疆区域 ✓
[analytics_validate_slots]
  missing_slots=["metric"], is_executable=false
  → next_step="analytics_clarify"
[analytics_clarify]
  创建 clarification_event (clarification_id="clr_200")
  创建 slot_snapshot (保存 time_range + org_scope)
  task_run.status="awaiting_user_clarification"
  返回: {clarification:{question:"你想看哪个指标？...",target_slots:["metric"]}}
```

#### 第二次请求（恢复执行）

```
POST /clarifications/clr_200/reply {"reply":"看发电量"}
  → ClarificationService.reply()
    → 读取 slot_snapshot → 时间/范围不变
    → 合并 metric="发电量"
    → 更新 clarification_event.status="resolved"
    → 调用 AnalyticsService → WorkflowAdapter.resume_from_clarification()
      → resume_from_clarification=true
      → analytics_entry 跳过"新建 run/记录原 query"
      → analytics_plan 使用 recovered_plan（从 slot_snapshot 重建）
      → 后续正常执行 SQL 链路
```

**恢复不是恢复 Python 线程**，而是根据 `run_id + slot_snapshot + clarification_event` 重新构造状态并重新进入 StateGraph。

---

## 七、状态机设计与图编排详解

### 7.1 双层状态机架构

系统采用**双层状态机**设计：

```
┌─ 宏观生命周期状态（task_run.status）─────────────────────┐
│ pending → executing → succeeded / failed /                │
│ awaiting_user_clarification / awaiting_human_review       │
│ 这些是"权威运行态"，持久化到 task_run，可审计              │
└──────────────────────────┬──────────────────────────────┘
                           │ 映射（status_mapper）
                           ▼
┌─ 微观执行状态（AnalyticsWorkflowState）─────────────────┐
│ workflow_stage ∈ {ENTRY, PLAN, VALIDATE, CLARIFY,       │
│   BUILD_SQL, GUARD_SQL, EXECUTE_SQL, SUMMARIZE, FINISH} │
│ workflow_outcome ∈ {CONTINUE, CLARIFY, REVIEW, FINISH, FAIL}│
│ 这些是"微观临时态"，只在 StateGraph 内部流转，不落库     │
└─────────────────────────────────────────────────────────┘
```

### 7.2 微观状态转换规则

```
ENTRY ──(成功)──► PLAN ──(成功)──► VALIDATE
                                    │
                    槽位齐全         │         槽位不足
                       ▼             │            ▼
                  BUILD_SQL          │        CLARIFY ──► FINISH
                       ▼             │
                  GUARD_SQL          │
                    │                │
         安全通过   │    被阻断      │
            ▼       │      ▼        │
      EXECUTE_SQL   │   FINISH(fail) │
            ▼       │
      SUMMARIZE     │
            ▼       │
      FINISH(success)
```

### 7.3 节点转换条件（关键 code path）

```python
# graph.py _build_graph()

# 固定边
graph.add_edge("analytics_entry", "analytics_plan")
graph.add_edge("analytics_plan", "analytics_validate_slots")
graph.add_edge("analytics_clarify", "analytics_finish")
graph.add_edge("analytics_build_sql", "analytics_guard_sql")
graph.add_edge("analytics_guard_sql", "analytics_execute_sql")
graph.add_edge("analytics_execute_sql", "analytics_summarize")
graph.add_edge("analytics_summarize", "analytics_finish")
graph.add_edge("analytics_finish", END)

# 条件边：唯一需要路由判断的位置
graph.add_conditional_edges(
    "analytics_validate_slots",
    _route_after_validation,
    {"analytics_clarify": "analytics_clarify", "analytics_build_sql": "analytics_build_sql"},
)
```

### 7.4 异常处理机制

| 异常场景 | 处理方式 | node |
|---|---|---|
| query 为空 | 立即抛 AppException(400) | entry |
| 语义解析低置信 | 走 LLM Fallback 补强，失败则澄清 | plan |
| 槽位缺失 | 走 clarification 分支（非异常） | validate |
| SQL Guard 阻断 | task_run.status=failed，抛 SQL_GUARD_BLOCKED（不可重试） | guard_sql |
| SQL 执行超时 | 重试一次（50ms 退避），仍失败则 failed | execute_sql |
| SQL 执行语法错误 | 立即 failed（不可重试） | execute_sql |
| 生成图表失败 | 降级（degraded=true），主查询仍 success | summarize |
| 生成洞察失败 | 降级，主查询仍 success | summarize |

### 7.5 状态持久化边界

**落入 task_run 的字段**（权威运行态，持久化）：
- 通过 `SnapshotBuilder` 构造的轻量快照
- summary / slots / row_count / latency_ms / governance_decision / timing_breakdown
- 不包含微观临时对象（plan/sql_bundle/masking_result 全量）

**不落入 task_run 的字段**（微观临时态，不持久化）：
- 完整 `AnalyticsPlan` 对象
- 完整 `SQLGuardResult` 全量
- `execution_result.rows` 原始数据
- 完整 `DataMaskingResult` 内部状态
- ReAct 完整 trace

**重内容去向**：写入 `analytics_result_repository`
- tables / insight_cards / report_blocks / chart_spec / masking_result 摘要

### 7.6 为什么当前不接 LangGraph Checkpoint

```
LangGraph Checkpoint 的作用：
  序列化整个 workflow state 到外部存储，支持从任意节点恢复

当前不接的原因：
1. 当前中断恢复点相对固定（slot_snapshot + clarification_event），
   不需要 Checkpoint 的"任意节点恢复"能力
2. Checkpoint 会把大量微观临时对象序列化，容易重新放大状态对象
3. 业务状态机（task_run + slot_snapshot + clarification_event）
   已经提供了足够的中断恢复能力

后续何时考虑接：
  当澄清流程变复杂、需要支持多步交互恢复时
  当 review 节点需要在不同状态间切换时
```

---

## 附录

### A. 核心状态字典

#### task_run.status

| 值 | 中文含义 |
|---|---|
| executing | 执行中 |
| succeeded | 执行成功 |
| failed | 执行失败 |
| awaiting_user_clarification | 等待用户澄清 |
| cancelled | 已取消 |

#### task_run.sub_status（常用）

| 值 | 中文含义 |
|---|---|
| planning_query | 正在意图识别与槽位提取 |
| building_sql | 正在构造 SQL |
| checking_sql | 正在 SQL Guard 安全检查 |
| running_sql | 正在通过 MCP 执行查询 |
| explaining_result | 正在生成摘要/图表/洞察 |
| awaiting_slot_fill | 等待用户补充槽位 |

#### AnalyticsWorkflowStage

| 值 | 含义 |
|---|---|
| ANALYTICS_ENTRY | 入口标准化 |
| ANALYTICS_PLAN | 意图识别+槽位 |
| ANALYTICS_VALIDATE_SLOTS | 槽位校验 |
| ANALYTICS_CLARIFY | 澄清生成 |
| ANALYTICS_BUILD_SQL | SQL 构造 |
| ANALYTICS_GUARD_SQL | SQL 安全检查 |
| ANALYTICS_EXECUTE_SQL | SQL 执行 |
| ANALYTICS_SUMMARIZE | 脱敏+摘要+生成 |
| ANALYTICS_FINISH | 存储分层+返回 |

#### AnalyticsWorkflowOutcome

| 值 | 含义 |
|---|---|
| CONTINUE | 当前节点完成，继续向下 |
| CLARIFY | 需进入澄清 |
| REVIEW | 命中审核要求 |
| FINISH | 工作流顺利完成 |
| FAIL | 工作流失败 |

### B. 文件索引

| 文件 | 说明 |
|---|---|
| [core/agent/control_plane/task_router.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/control_plane/task_router.py) | Supervisor 规则路由器 |
| [core/tools/a2a/contracts.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/tools/a2a/contracts.py) | A2A 契约定义 |
| [core/agent/workflows/analytics/graph.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/graph.py) | StateGraph 编排 |
| [core/agent/workflows/analytics/state.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/state.py) | 微观状态定义 |
| [core/agent/workflows/analytics/nodes.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/nodes.py) | 9 个节点实现 |
| [core/agent/workflows/analytics/adapter.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/adapter.py) | 宏观↔微观 Adapter |
| [core/agent/workflows/analytics/react/planner.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/react/planner.py) | ReAct Planning 引擎 |
| [core/agent/workflows/analytics/retry_policy.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/retry_policy.py) | 节点重试策略 |
| [core/agent/workflows/analytics/degradation.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/agent/workflows/analytics/degradation.py) | 降级控制器 |
| [core/tools/mcp/sql_mcp_server.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/tools/mcp/sql_mcp_server.py) | SQL MCP Server |
| [core/services/analytics_service.py](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/core/services/analytics_service.py) | 主编排服务 |
| [docs/ARCHITECTURE.md](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/docs/ARCHITECTURE.md) | 系统总架构文档 |
| [docs/AGENT_WORKFLOW.md](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/docs/AGENT_WORKFLOW.md) | 工作流设计文档 |
| [docs/ANALYTICS_AGENT_E2E_WORKFLOW.md](file:///Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag/docs/ANALYTICS_AGENT_E2E_WORKFLOW.md) | 经营分析 11 场景链路文档 |

---

> 本文档基于当前仓库实际代码编写，所有架构概念均可对应到具体源文件。
> 文档中的每个组件、状态定义、编排逻辑均与代码实现保持一致。
