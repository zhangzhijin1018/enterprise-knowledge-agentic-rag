# 经营分析 Agent 验收清单

> 本文档是经营分析 Agent 的验收检查清单，用于确保链路文档、代码实现和业务需求的完整对齐。
>
> 更新时间：2026-05-02
>
> 与 `docs/ANALYTICS_AGENT_E2E_WORKFLOW.md` 配套使用。

---

## 一、链路文档验收

### 1.1 场景覆盖

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| 场景 1：简单明确查询 | 必须 | ✅ | "查询新疆区域 2024 年 3 月的发电量"，三要素齐全，一次性成功 |
| 场景 2：指标歧义，需要澄清 | 必须 | ✅ | "新疆最近电量咋样"，返回 metric_ambiguity |
| 场景 3：指标缺失，需要澄清 | 必须 | ✅ | "帮我看一下新疆区域上个月的情况"，返回 metric_missing |
| 场景 4：复杂归因分析（PARALLEL 策略） | 必须 | ✅ | "分析近三个月发电量下降原因，和去年对比" |
| 场景 5：跨数据源查询（PARALLEL 策略） | 必须 | ✅ | "对比聚乙烯销量和发电量" |
| 场景 6：同一数据源多表查询（JOIN 策略） | 必须 | ✅ | "查询各电站的发电量和上网电量" |
| 场景 7：澄清后恢复执行 | 必须 | ✅ | 用户回答"看发电量"，系统恢复执行 |
| 场景 8：SQL Guard 阻断 | 必须 | ✅ | SQL 缺少部门过滤被阻断，不可重试 |
| 场景 9：SQL Gateway 临时失败重试 | 必须 | ✅ | timeout 可重试一次，与 Guard blocked 区分 |
| 场景 10：图表/洞察/报告块降级 | 必须 | ✅ | Chart Spec 失败不影响主查询，degraded=true |

### 1.2 执行策略覆盖

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| SINGLE 策略 | 必须 | ✅ | 单个查询直接执行 |
| PARALLEL 策略（同数据源） | 必须 | ✅ | 同数据源、同表、不同时间并行查询 |
| PARALLEL 策略（跨数据源） | 必须 | ✅ | 不同数据源并行查询 |
| JOIN 策略 | 必须 | ✅ | 同数据源、多表关联查询 |
| 策略选择逻辑正确 | 必须 | ✅ | QueryPlanner 正确判断 |

### 1.3 文档质量要求

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| 每个场景有实际用户问句 | 必须 | ✅ | 每个场景以真实问句开头 |
| 每个场景有实际输入输出示例 | 必须 | ✅ | 包含完整 JSON 示例 |
| 所有关键字段有中文解释 | 必须 | ✅ | 使用字段说明表 |
| 展示了 LLM 生成内容 | 必须 | ✅ | AnalyticsIntent 完整示例 |
| 展示了执行计划 | 必须 | ✅ | ExecutionPlan 和 ExecutionPhase 示例 |
| 展示了策略选择 | 必须 | ✅ | SINGLE/PARALLEL/JOIN 示例 |
| 适合非英语熟练读者阅读 | 必须 | ✅ | 所有英文状态值配中文解释 |

---

## 二、功能实现验收

### 2.1 意图解析

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| LLMAnalyticsIntentParser 正常工作 | 必须 | ✅ | 解析用户问句为 AnalyticsIntent |
| 支持 semantic_confidence 字段 | 必须 | ✅ | 语义理解置信度 |
| 支持 metric.candidates 字段 | 必须 | ✅ | 指标候选列表（歧义场景） |
| 支持 required_queries 字段 | 必须 | ✅ | 子查询列表（复杂场景） |
| 支持 original_query 字段 | 必须 | ✅ | 原始问句 |

### 2.2 歧义检测

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| ClarificationManager 检测指标歧义 | 必须 | ✅ | candidates.length >= 2 |
| ClarificationManager 检测指标缺失 | 必须 | ✅ | metric is None or metric_code is None |
| ClarificationManager 检测时间缺失 | 必须 | ✅ | time_range is None |
| ClarificationManager 生成澄清选项 | 必须 | ✅ | clarification_options |

### 2.3 执行计划

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| QueryPlanner 生成 ExecutionPlan | 必须 | ✅ | |
| QueryPlanner 判断 SINGLE 策略 | 必须 | ✅ | 单个查询 |
| QueryPlanner 判断 PARALLEL 策略 | 必须 | ✅ | 同一数据源 + 同表 + 不同时间 |
| QueryPlanner 判断 JOIN 策略 | 必须 | ✅ | 同一数据源 + 多表 |
| ExecutionPhase 包含 strategy 字段 | 必须 | ✅ | SINGLE/PARALLEL/JOIN |
| ExecutionPhase 包含 join_sql 字段 | 必须 | ✅ | JOIN 策略时 |

### 2.4 查询执行

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| QueryExecutor 支持 SINGLE 策略 | 必须 | ✅ | 单个查询直接执行 |
| QueryExecutor 支持 PARALLEL 策略 | 必须 | ✅ | asyncio.gather 并行执行 |
| QueryExecutor 支持 JOIN 策略 | 必须 | ✅ | 执行单条 JOIN SQL |
| QueryExecutor 并行执行不同数据源 | 必须 | ✅ | asyncio.gather 跨连接池 |
| ExecutionResult 返回 query_id 对应结果 | 必须 | ✅ | |

### 2.5 SQL 治理

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| SQLBuilder 生成 schema-aware SQL | 必须 | ✅ | 基于槽位和 schema 构造 |
| SQLGuard 做只读校验 | 必须 | ✅ | 必须以 SELECT 开头 |
| SQLGuard 做 DDL/DML 禁止 | 必须 | ✅ | INSERT/UPDATE/DELETE/DROP 等 |
| SQLGuard 做表白名单 | 必须 | ✅ | 只允许白名单表 |
| SQLGuard 做部门过滤 | 必须 | ✅ | department_code 必须存在 |
| SQLGuard 自动补 LIMIT | 必须 | ✅ | 默认 LIMIT 500 |
| SQLGuard blocked 不可重试 | 必须 | ✅ | 与 Gateway timeout 区分 |

### 2.6 执行与结果

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| SQL Gateway 走 MCP server | 必须 | ✅ | 进程内 SQL MCP Server |
| 执行超时可重试 | 必须 | ✅ | TimeoutError 可重试 |
| DataMaskingService 脱敏 | 必须 | ✅ | 敏感字段缺少权限时脱敏 |
| Summary 生成 | 必须 | ✅ | 根据 group_by/compare_target 生成不同摘要 |
| Insight Cards 生成 | 必须 | ✅ | 按规则生成 ranking/trend |
| Chart Spec 生成 | 必须 | ✅ | 按 group_by 决定 chart_type |

### 2.7 存储与性能

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| output_snapshot 轻量化 | 必须 | ✅ | 不含 tables/insight_cards 等 |
| 重结果写入 analytics_result_repository | 必须 | ✅ | tables/insight_cards 等单独存储 |
| output_mode 分级返回 | 必须 | ✅ | lite/standard/full |
| slot_snapshot 保存中间态 | 必须 | ✅ | 供恢复执行使用 |
| clarification_event 独立存储 | 必须 | ✅ | 可审计的交互事件 |

---

## 三、执行策略说明

### 3.1 策略定义

| 策略 | 场景 | 执行方式 | 说明 |
|------|------|---------|------|
| SINGLE | 单个查询 | 直接执行 | 简单查询 |
| PARALLEL | 同数据源 + 同表 + 不同时间 | 并行查询 | asyncio.gather |
| PARALLEL | 不同数据源 | 并行查询 | asyncio.gather 跨连接池 |
| JOIN | 同数据源 + 多表 | 单条 SQL | JOIN 更高效 |

### 3.2 策略选择逻辑

```
if queries.length == 1:
    return SINGLE

if queries.length > 1:
    if same_data_source:
        if same_table:
            if different_time_periods:
                return PARALLEL
            else:
                return JOIN
        else:
            return JOIN
    else:
        return PARALLEL  # 不同数据源也可以并行
```

### 3.3 并行执行说明

```
┌─────────────────────────────────────────────────────────────┐
│ asyncio.gather 并行执行：                                  │
│                                                              │
│ - 同一数据源的多个查询：使用同一连接池，并行执行           │
│ - 不同数据源的多个查询：使用不同连接池，并行执行           │
│ - 所有查询结束后，应用层合并结果                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 四、回归检查项

| 检查项 | 说明 |
|---|---|
| 简单三要素查询一次成功 | metric + time_range + org_scope 齐全 |
| 指标歧义返回澄清 | candidates.length >= 2 |
| 指标缺失返回澄清 | metric is None |
| 跨数据源并行执行 | asyncio.gather |
| 同数据源多表使用 JOIN | JOIN SQL |
| 同数据源同表不同时间并行 | asyncio.gather |
| SQL 审计有记录 | 每次执行都有 audit 可查询 |
| 脱敏生效 | 敏感字段缺少权限时脱敏 |

---

> 本清单与 `docs/ANALYTICS_AGENT_E2E_WORKFLOW.md` 配套使用。
