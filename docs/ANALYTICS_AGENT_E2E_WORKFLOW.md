# 经营分析 Agent 端到端链路文档

## 文档概述

本文档详细描述经营分析 Agent 的完整执行链路，从用户问句到最终结果返回。

核心设计理念：
- **LLM 只负责语义理解**：识别用户想要什么指标
- **本地负责业务映射**：指标代码 → 数据源/表/字段
- **执行策略智能选择**：SINGLE / PARALLEL / JOIN
- **歧义检测本地化**：不依赖 LLM

---

## 一、架构总览

### 1.1 执行策略

```
┌─────────────────────────────────────────────────────────────────┐
│                     执行策略选择                                   │
├─────────────────────────────────────────────────────────────────┤
│ 同一数据源 + 多表    →  SQL JOIN（最优）                        │
│ 同一数据源 + 同表    →  并行查询 → 应用层合并                  │
│ 不同数据源           →  并行查询 → 应用层合并                  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 完整链路流程

```
┌─────────────────────────────────────────────────────────────────┐
│                     用户问句                                      │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. LLM 意图解析                                                │
│    - semantic_confidence: 语义置信度                           │
│    - metric: {metric_code, candidates: [...]}                   │
│    - required_queries: [{metric_code, period_role, ...}]       │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. 歧义检测（本地）                                            │
│    if candidates.length >= 2:                                   │
│        return ClarificationResponse                             │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. QueryPlanner（本地）                                          │
│    MetricResolver.resolve(metric_code)                          │
│    → 获取 data_source_key                                       │
│    → 判断策略：SINGLE / PARALLEL / JOIN                         │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. QueryExecutor（执行）                                        │
│    - asyncio.gather 并行执行所有查询                            │
│    - JOIN 策略执行单条 SQL                                       │
│    - PARALLEL 策略并行执行多条 SQL                               │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. 应用层合并                                                   │
│    - 不同数据源结果合并                                         │
│    - 不同时间周期结果合并                                        │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. 返回结果                                                     │
│    - Summary: 摘要                                             │
│    - Chart Spec: 图表描述                                      │
│    - Insight Cards: 洞察卡片                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、置信度体系

### 2.1 置信度类型

| 置信度类型 | 字段 | 说明 | 阈值参考 |
|-----------|------|------|---------|
| 语义理解 | `semantic_confidence` | LLM 是否听懂用户 | >= 0.85 可执行 |
| 指标选择 | `metric.confidence` | 是否选对指标 | >= 0.85 可执行 |
| 时间范围 | `time_range.confidence` | 时间解析准确度 | >= 0.70 |
| 执行可行性 | `confidence.execution` | 数据源是否可用 | 1.0 或 0.0 |

### 2.2 置信度阈值规则

```
| overall >= 0.85    | 可执行，无需澄清                                  |
| 0.65 <= overall < 0.85 | 如无歧义可执行，否则澄清                  |
| overall < 0.65     | 必须澄清                                        |
```

---

## 三、用户问句场景覆盖

### 场景 1：简单明确查询

**用户问句**：`"查询新疆区域 2024 年 3 月发电量"`

**场景说明**：用户明确指定了指标、时间范围和组织范围，无需歧义检测。

**系统执行步骤**：

```
Step 1: LLM 意图解析
┌─────────────────────────────────────────────────────────────┐
│ AnalyticsIntent {                                          │
│   original_query: "查询新疆区域 2024 年 3 月发电量",       │
│   complexity: "simple",                                    │
│   planning_mode: "direct",                                 │
│   semantic_confidence: 0.95,                              │
│   metric: {                                               │
│     metric_code: "generation",                            │
│     metric_name: "发电量",                                │
│     confidence: 0.95                                       │
│   },                                                       │
│   time_range: {                                            │
│     type: "absolute",                                      │
│     value: "2024-03",                                     │
│     start: "2024-03-01",                                 │
│     end: "2024-03-31",                                   │
│     confidence: 0.95                                       │
│   },                                                       │
│   org_scope: {                                            │
│     type: "region",                                       │
│     name: "新疆区域",                                      │
│     confidence: 0.90                                       │
│   },                                                       │
│   compare_target: "none",                                  │
│   need_clarification: false                              │
│ }                                                          │
└─────────────────────────────────────────────────────────────┘
```

**Step 2: 歧义检测**
- `candidates.length = 0`：无歧义
- `need_clarification = false`：无需澄清

**Step 3: QueryPlanner 生成执行计划**
```
┌─────────────────────────────────────────────────────────────┐
│ ExecutionPlan {                                           │
│   phases: [                                              │
│     {                                                    │
│       phase_id: "phase_0",                              │
│       data_source_key: "enterprise_readonly",             │
│       queries: ["q_simple"],                            │
│       strategy: "single"                                 │
│     }                                                    │
│   ],                                                     │
│   need_merge: false,                                     │
│   total_queries: 1                                       │
│ }                                                        │
└─────────────────────────────────────────────────────────────┘
```

**Step 4: QueryExecutor 执行**
```
SQL: SELECT station_name, SUM(metric_value) as generation
     FROM analytics_metrics_daily
     WHERE metric_code = 'generation'
       AND biz_date >= '2024-03-01'
       AND biz_date <= '2024-03-31'
       AND region_name = '新疆区域'
     GROUP BY station_name
```

**字段说明表**：

| 字段 | 示例值 | 中文含义 |
|------|--------|---------|
| original_query | 查询新疆区域 2024 年 3 月发电量 | 用户原始问句 |
| complexity | simple | 问题复杂度：简单查询 |
| planning_mode | direct | 规划模式：直接执行 |
| semantic_confidence | 0.95 | 语义理解置信度 |
| metric_code | generation | 指标代码 |
| metric_name | 发电量 | 指标名称 |
| time_range.value | 2024-03 | 时间范围值 |
| time_range.start | 2024-03-01 | 时间范围起始日期 |
| time_range.end | 2024-03-31 | 时间范围结束日期 |
| org_scope.name | 新疆区域 | 组织范围名称 |
| compare_target | none | 对比目标：无 |
| need_clarification | false | 是否需要澄清 |

**最终返回**：

| 字段 | 示例值 | 中文含义 |
|------|--------|---------|
| summary | 2024年3月新疆区域发电量为12800 MWh | 数据摘要 |
| data | [{station: 哈密电站, value: 4200}, ...] | 查询结果 |
| degraded | false | 是否降级 |

---

### 场景 2：指标歧义，需要澄清

**用户问句**：`"新疆最近电量咋样"`

**场景说明**：用户说"电量"可能指发电量、上网电量或售电量，需要澄清。

**系统执行步骤**：

**Step 1: LLM 意图解析**
```json
{
  "original_query": "新疆最近电量咋样",
  "complexity": "simple",
  "planning_mode": "clarification",
  "semantic_confidence": 0.70,
  "metric": {
    "raw_text": "电量",
    "confidence": 0.50,
    "candidates": [
      {"metric_code": "generation", "metric_name": "发电量", "confidence": 0.40, "business_domain": "new_energy"},
      {"metric_code": "online", "metric_name": "上网电量", "confidence": 0.30, "business_domain": "new_energy"},
      {"metric_code": "sales", "metric_name": "售电量", "confidence": 0.30, "business_domain": "new_energy"}
    ]
  },
  "time_range": {
    "raw_text": "最近",
    "type": "relative",
    "value": "最近",
    "confidence": 0.70
  },
  "org_scope": {
    "type": "region",
    "name": "新疆",
    "confidence": 0.90
  },
  "need_clarification": true,
  "clarification_type": "metric_ambiguity"
}
```

**Step 2: ClarificationManager 歧义检测**
```
检测结果：
- metric.candidates.length = 3 >= 2
- 触发澄清
```

**返回给用户的澄清问题**：
```
您说的「电量」可能是：
1. 发电量
2. 上网电量
3. 售电量

请回复选项编号或指标名称。
```

**字段说明表**：

| 字段 | 示例值 | 中文含义 |
|------|--------|---------|
| ambiguous_fields | ["metric"] | 存在歧义的字段 |
| clarification_type | metric_ambiguity | 澄清类型：指标歧义 |
| metric.raw_text | 电量 | 用户原始指标文本 |
| metric.candidates | [{generation}, {online}, {sales}] | 指标候选列表 |
| clarification_options | [...] | 澄清选项 |

---

### 场景 3：指标缺失，需要澄清

**用户问句**：`"帮我看一下新疆区域上个月的情况"`

**场景说明**：用户没有明确指标，需要引导补充。

**系统执行步骤**：

**Step 1: LLM 意图解析**
```json
{
  "original_query": "帮我看一下新疆区域上个月的情况",
  "metric": null,
  "time_range": {
    "raw_text": "上个月",
    "type": "relative",
    "value": "上月",
    "confidence": 0.80
  },
  "org_scope": {
    "type": "region",
    "name": "新疆区域",
    "confidence": 0.90
  },
  "need_clarification": true,
  "clarification_type": "metric_missing",
  "missing_fields": ["metric"]
}
```

**返回给用户的澄清问题**：
```
请问您想查看哪个经营指标？
1. 发电量
2. 上网电量
3. 收入
4. 成本
5. 利润
```

---

### 场景 4：复杂归因分析（PARALLEL 策略）

**用户问句**：`"分析新疆区域近三个月发电量下降的原因，并和去年同期对比，看哪些电站拖累最大"`

**场景说明**：需要查询当前周期和去年同期数据，进行同比分析。

**系统执行步骤**：

**Step 1: LLM 意图解析**
```json
{
  "original_query": "分析新疆区域近三个月发电量下降的原因，并和去年同期对比，看哪些电站拖累最大",
  "complexity": "complex",
  "planning_mode": "decomposed",
  "analysis_intent": "decline_attribution",
  "semantic_confidence": 0.92,
  "metric": {
    "metric_code": "generation",
    "metric_name": "发电量",
    "confidence": 0.95
  },
  "time_range": {
    "raw_text": "近三个月",
    "type": "relative",
    "value": "近三个月",
    "confidence": 0.90
  },
  "org_scope": {
    "type": "region",
    "name": "新疆区域",
    "confidence": 0.90
  },
  "group_by": "station",
  "compare_target": "yoy",
  "sort_by": "decline_contribution",
  "sort_direction": "desc",
  "top_n": 10,
  "required_queries": [
    {
      "query_id": "q_current",
      "query_name": "current",
      "purpose": "查询当前周期各电站发电量",
      "metric_code": "generation",
      "period_role": "current",
      "group_by": "station"
    },
    {
      "query_id": "q_yoy",
      "query_name": "yoy_baseline",
      "purpose": "查询去年同期各电站发电量",
      "metric_code": "generation",
      "period_role": "yoy_baseline",
      "group_by": "station"
    }
  ]
}
```

**Step 2: 歧义检测**
- `candidates.length = 0`：无歧义
- `missing_fields = []`：无缺失
- `need_clarification = false`

**Step 3: QueryPlanner 生成执行计划**
```
┌─────────────────────────────────────────────────────────────┐
│ ExecutionPlan {                                           │
│   phases: [                                              │
│     {                                                    │
│       phase_id: "phase_0",                              │
│       data_source_key: "enterprise_readonly",             │
│       queries: ["q_current", "q_yoy"],                 │
│       strategy: "parallel"  ← 同一数据源、同表、不同时间 │
│     }                                                    │
│   ],                                                     │
│   need_merge: false,  ← 同一数据源不需要应用层合并        │
│   total_queries: 2                                       │
│ }                                                        │
└─────────────────────────────────────────────────────────────┘
```

**Step 4: QueryExecutor 执行（并行）**
```
并行执行（asyncio.gather）：
Task 1: SELECT station_name, SUM(metric_value)
        FROM analytics_metrics_daily
        WHERE metric_code = 'generation'
          AND biz_date >= '2024-02-01'  -- 近三个月
          AND biz_date <= '2024-04-30'
          AND region_name = '新疆区域'
        GROUP BY station_name

Task 2: SELECT station_name, SUM(metric_value)
        FROM analytics_metrics_daily
        WHERE metric_code = 'generation'
          AND biz_date >= '2023-02-01'  -- 去年同期
          AND biz_date <= '2023-04-30'
          AND region_name = '新疆区域'
        GROUP BY station_name
```

**字段说明表**：

| 字段 | 示例值 | 中文含义 |
|------|--------|---------|
| analysis_intent | decline_attribution | 分析意图：下降归因 |
| required_queries | [{current}, {yoy_baseline}] | 子查询列表 |
| period_role | current / yoy_baseline | 时间周期角色 |
| group_by | station | 分组维度：电站 |
| compare_target | yoy | 对比目标：同比 |
| sort_direction | desc | 排序方向：降序 |
| top_n | 10 | 返回前10个 |
| strategy | parallel | 执行策略：并行 |

---

### 场景 5：跨数据源查询（PARALLEL 策略）

**用户问句**：`"对比一下聚乙烯销量和发电量的变化趋势"`

**场景说明**：涉及化工贸易和新能源两个数据源，需要分别查询后应用层合并。

**系统执行步骤**：

**Step 1: LLM 意图解析**
```json
{
  "original_query": "对比一下聚乙烯销量和发电量的变化趋势",
  "complexity": "complex",
  "planning_mode": "decomposed",
  "analysis_intent": "comparison",
  "semantic_confidence": 0.88,
  "metric": {
    "raw_text": "销量和发电量",
    "confidence": 0.90,
    "candidates": [
      {"metric_code": "generation", "metric_name": "发电量", "confidence": 0.45, "business_domain": "new_energy"},
      {"metric_code": "chemical_sales_volume", "metric_name": "化工产品销售量", "confidence": 0.45, "business_domain": "chemical"}
    ]
  },
  "time_range": {
    "raw_text": "变化趋势",
    "type": "relative",
    "value": "最近",
    "confidence": 0.60
  },
  "compare_target": "yoy",
  "required_queries": [
    {
      "query_id": "q_gen",
      "query_name": "generation_trend",
      "purpose": "查询发电量趋势",
      "metric_code": "generation",
      "period_role": "current",
      "group_by": "month"
    },
    {
      "query_id": "q_sales",
      "query_name": "sales_trend",
      "purpose": "查询聚乙烯销量趋势",
      "metric_code": "chemical_sales_volume",
      "period_role": "current",
      "group_by": "month"
    }
  ]
}
```

**Step 2: 歧义检测**
- 用户明确说了两个指标，无需澄清

**Step 3: QueryPlanner 生成执行计划**
```
┌─────────────────────────────────────────────────────────────┐
│ ExecutionPlan {                                           │
│   phases: [                                              │
│     {                                                    │
│       phase_id: "phase_0",                              │
│       data_source_key: "enterprise_readonly",  ← 发电量   │
│       queries: ["q_gen"],                               │
│       strategy: "single"                                 │
│     },                                                   │
│     {                                                    │
│       phase_id: "phase_1",                              │
│       data_source_key: "enterprise_trade",    ← 聚乙烯   │
│       queries: ["q_sales"],                             │
│       strategy: "single"                                 │
│     }                                                    │
│   ],                                                     │
│   need_merge: true,  ← 不同数据源需要应用层合并          │
│   total_queries: 2                                       │
│ }                                                        │
└─────────────────────────────────────────────────────────────┘
```

**Step 4: QueryExecutor 执行（并行）**
```
所有阶段并行执行（asyncio.gather）：

Phase 0 (enterprise_readonly):
SQL: SELECT month, SUM(metric_value) as generation
     FROM analytics_metrics_daily
     WHERE metric_code = 'generation'
       AND biz_date >= '2024-01-01'
     GROUP BY month
     ORDER BY month

Phase 1 (enterprise_trade):
SQL: SELECT month, SUM(sales_volume) as sales_volume
     FROM chemical_product_sales_daily
     WHERE product_type = '聚乙烯'
       AND biz_date >= '2024-01-01'
     GROUP BY month
     ORDER BY month
```

**Step 5: 应用层合并**
```
合并策略：按 month 字段关联
结果：
[
  {month: "2024-01", generation: 1200, sales_volume: 500},
  {month: "2024-02", generation: 1350, sales_volume: 520},
  {month: "2024-03", generation: 1280, sales_volume: 480},
]
```

---

### 场景 6：同一数据源多表查询（JOIN 策略）

**用户问句**：`"查询各电站的发电量和上网电量"`

**场景说明**：同一数据源需要关联发电量和上网电量两张表。

**系统执行步骤**：

**Step 1: LLM 意图解析**
```json
{
  "original_query": "查询各电站的发电量和上网电量",
  "complexity": "complex",
  "planning_mode": "decomposed",
  "analysis_intent": "simple_query",
  "metric": {
    "confidence": 0.90,
    "candidates": [
      {"metric_code": "generation", "metric_name": "发电量"},
      {"metric_code": "online", "metric_name": "上网电量"}
    ]
  },
  "required_queries": [
    {
      "query_id": "q_gen",
      "metric_code": "generation",
      "join_with": "q_online",
      "join_type": "left"
    },
    {
      "query_id": "q_online",
      "metric_code": "online",
      "join_with": "q_gen",
      "join_type": "left"
    }
  ]
}
```

**Step 3: QueryPlanner 生成执行计划**
```
┌─────────────────────────────────────────────────────────────┐
│ ExecutionPlan {                                           │
│   phases: [                                              │
│     {                                                    │
│       phase_id: "phase_0",                              │
│       data_source_key: "enterprise_readonly",            │
│       queries: ["q_gen", "q_online"],                   │
│       strategy: "join"  ← 同一数据源、多表              │
│     }                                                    │
│   ],                                                     │
│   need_merge: false,  ← JOIN 查询不需要应用层合并        │
│   total_queries: 2                                       │
│ }                                                        │
└─────────────────────────────────────────────────────────────┘
```

**Step 4: QueryExecutor 执行（JOIN）**
```
单条 JOIN SQL：
SELECT
    a.station_name,
    a.generation,
    b.online
FROM (
    SELECT station_name, SUM(metric_value) as generation
    FROM analytics_metrics_daily
    WHERE metric_code = 'generation'
      AND biz_date >= '2024-03-01'
      AND biz_date <= '2024-03-31'
    GROUP BY station_name
) a
LEFT JOIN (
    SELECT station_name, SUM(metric_value) as online
    FROM analytics_metrics_daily
    WHERE metric_code = 'online'
      AND biz_date >= '2024-03-01'
      AND biz_date <= '2024-03-31'
    GROUP BY station_name
) b ON a.station_name = b.station_name
```

---

### 场景 7：澄清后恢复执行

**接场景 2**

用户补充：`"看发电量"`

**系统执行步骤**：

**Step 1: 读取澄清上下文**
```json
{
  "clarification_id": "clar_001",
  "original_query": "新疆最近电量咋样",
  "confirmed_metric": null,
  "confirmed_time_range": "最近"
}
```

**Step 2: 应用澄清结果**
```json
{
  "original_query": "新疆最近电量咋样",
  "metric": {
    "metric_code": "generation",
    "metric_name": "发电量",
    "confidence": 1.0  ← 用户确认后置信度为 1.0
  },
  "time_range": {
    "type": "relative",
    "value": "最近",
    "confidence": 0.70
  },
  "need_clarification": false,
  "clarification_type": null
}
```

**Step 3: 重新进入执行流程**
```
ExecutionPlan:
  phases: [
    {
      phase_id: "phase_0",
      data_source_key: "enterprise_readonly",
      queries: ["q_simple"],
      strategy: "single"
    }
  ]
```

**状态变化表**：

| 阶段 | task_run.status | 中文含义 |
|------|-----------------|---------|
| 初次询问 | awaiting_user_clarification | 等待用户补充信息 |
| 用户补充后 | executing | 重新进入执行中 |
| 查询完成 | succeeded | 执行成功 |

---

### 场景 8：SQL Guard 阻断

**用户问句**：`"查询所有区域所有用户明细"`

**场景说明**：查询缺少必要的过滤条件，可能存在数据泄露风险。

**系统执行步骤**：

**SQL Guard 检查结果**：
```json
{
  "success": false,
  "error_code": "SQL_GUARD_BLOCKED",
  "message": "SQL 安全检查未通过",
  "blocked_reason": "缺少部门过滤条件或访问了非白名单表",
  "can_retry": false
}
```

**字段说明表**：

| 字段 | 示例值 | 中文含义 |
|------|--------|---------|
| success | false | 请求是否成功 |
| error_code | SQL_GUARD_BLOCKED | SQL 安全检查失败错误码 |
| message | SQL 安全检查未通过 | 给用户展示的错误信息 |
| blocked_reason | 缺少部门过滤条件 | 被阻断的原因 |
| can_retry | false | 是否可重试：不可重试 |

**说明**：
- SQL Guard blocked 不可重试
- 不能通过 ReAct 或 LLM 绕过
- task_run.status 变成 failed

---

### 场景 9：SQL Gateway 临时失败重试

**用户问句**：`"查询新疆区域 2024 年 3 月发电量"`

**系统执行步骤**：

```
第一次尝试：
  SQL Gateway Timeout
  retry_count: 1
  → 可重试

第二次尝试：
  SQL 执行成功
  retry_count: 1
```

**retry_history 字段说明**：

| 字段 | 示例值 | 中文含义 |
|------|--------|---------|
| node_name | analytics_execute_sql | 发生重试的节点 |
| attempt | 1 | 第几次尝试 |
| error_type | TimeoutError | 错误类型 |
| error_message | SQL Gateway 请求超时 | 错误信息 |

**重试策略说明**：

| 错误类型 | 是否可重试 |
|---------|-----------|
| TimeoutError | 可重试 |
| ConnectionError | 可重试 |
| SQL_GUARD_BLOCKED | 不可重试 |
| PermissionError | 不可重试 |

---

### 场景 10：图表、洞察、报告块降级

**用户问句**：`"生成新疆区域 2024 年 3 月发电量的完整分析"`

**系统执行步骤**：

```
Step 1: SQL 执行成功
Step 2: Summary 生成成功
Step 3: Chart Spec 生成失败（降级）
Step 4: Insight Cards 生成成功
Step 5: Report Blocks 生成失败（降级）
```

**最终返回**：

| 字段 | 示例值 | 中文含义 |
|------|--------|---------|
| summary | 2024年3月新疆区域发电量为12800 MWh | 摘要 |
| degraded | true | 是否发生降级 |
| degraded_features | ["chart_spec", "report_blocks"] | 发生降级的功能 |
| row_count | 4 | 查询结果行数 |

**降级规则说明**：
- 图表、洞察、报告块可以降级
- SQL 执行失败不能降级成成功
- 系统不能编造查询结果

---

## 四、组件职责

### 4.1 组件列表

| 组件 | 文件路径 | 职责 |
|------|---------|------|
| LLMAnalyticsIntentParser | core/analytics/intent/parser.py | LLM 意图解析 |
| MetricResolver | core/analytics/metric_resolver.py | 指标 → 数据源映射 |
| ClarificationManager | core/analytics/intent/clarification_manager.py | 歧义检测与澄清 |
| QueryPlanner | core/analytics/intent/query_planner.py | 子查询规划（策略选择） |
| QueryExecutor | core/analytics/intent/query_executor.py | SQL 执行（并行/串行） |

### 4.2 组件关系图

```
┌─────────────────────────────────────────────────────────────────┐
│                     LLMAnalyticsIntentParser                      │
│                     （意图解析 + 歧义候选）                       │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                     ClarificationManager                         │
│                     （歧义检测 + 澄清生成）                       │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                     MetricResolver                              │
│                     （指标 → 数据源映射）                         │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                     QueryPlanner                                 │
│                     （策略选择：SINGLE/PARALLEL/JOIN）           │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                     QueryExecutor                               │
│                     （执行：asyncio.gather 并行）                 │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                     SQL Gateway                                  │
│                     （数据库访问）                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 五、状态机

### 5.1 task_run 状态

| 状态值 | 中文含义 | 说明 |
|-------|---------|------|
| pending | 待处理 | 任务刚创建 |
| executing | 执行中 | 正在执行 |
| awaiting_user_clarification | 等待用户补充信息 | 需要澄清 |
| succeeded | 执行成功 | 任务完成 |
| failed | 执行失败 | 任务失败 |
| awaiting_human_review | 等待人工审核 | 需要人工审核 |

### 5.2 clarification_event 状态

| 状态值 | 中文含义 | 说明 |
|-------|---------|------|
| pending | 待回复 | 等待用户回复 |
| resolved | 已解决 | 用户已回复并确认 |
| expired | 已过期 | 超过有效期 |
| cancelled | 已取消 | 用户取消 |

---

## 六、后续阅读建议

1. **理解执行策略**：先看"一、架构总览"理解 SINGLE/PARALLEL/JOIN 的选择逻辑
2. **理解置信度体系**：再看"二、置信度体系"理解何时需要澄清
3. **理解完整链路**：通过"三、用户问句场景覆盖"的 10 个场景理解完整流程
4. **理解组件职责**：通过"四、组件职责"理解各组件的边界
