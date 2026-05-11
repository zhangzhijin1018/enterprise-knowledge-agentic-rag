# analytics_build_sql 节点原理详解

> 本文档详细解释经营分析系统中，如何将复杂的 AnalyticsIntent 转换为 SQL 语句的完整原理。

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              用户问句                                        │
│  "查询新疆区域2024年3月发电量，和去年对比，看看TOP10电站"                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         analytics_parse 节点                                 │
│                         (LLM 解析意图)                                       │
│                                                                              │
│  输出：AnalyticsIntent                                                        │
│  - metric: 发电量                                                           │
│  - time_range: 2024-03                                                       │
│  - org_scope: 新疆区域                                                      │
│  - compare_target: yoy                                                       │
│  - group_by: station                                                        │
│  - top_n: 10                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         analytics_build_sql 节点                             │
│                         (Intent → SQL)                                       │
│                                                                              │
│  输入：AnalyticsIntent                                                        │
│  输出：SQL Bundle                                                            │
│        - generated_sql: SELECT ... FROM ... WHERE ...                        │
│        - metric_scope: 发电量                                                │
│        - data_source: warehouse                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         analytics_guard_sql 节点                             │
│                         (SQL 安全校验)                                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         analytics_execute_sql 节点                           │
│                         (执行查询)                                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、核心数据结构：AnalyticsIntent

`AnalyticsIntent` 是 LLM 解析后的统一意图结构，包含了经营分析查询的所有必要信息。

### 2.1 完整结构

```python
class AnalyticsIntent(BaseModel):
    """经营分析统一意图结构"""

    # ========== 基础信息 ==========
    original_query: str                    # 用户原始问句
    task_type: str                         # "analytics_query"

    # ========== 核心意图 ==========
    metric: MetricIntent | None           # 指标意图
    time_range: TimeRangeIntent | None    # 时间范围意图
    org_scope: OrgScopeIntent | None      # 组织范围意图
    group_by: str | None                  # 分组维度（station/region）
    compare_target: CompareTarget | None   # 对比目标（none/yoy/mom）
    top_n: int | None                    # TOP N 排名

    # ========== 执行规划 ==========
    planning_mode: PlanningMode           # 执行模式（direct/decomposed）
    complexity: ComplexityType           # 复杂度（simple/complex）
    required_queries: list[RequiredQuery]  # 子查询列表
    execution_plan: ExecutionPlan | None # 执行计划

    # ========== 置信度 ==========
    confidence: IntentConfidence | None   # 解析置信度
```

### 2.2 枚举类型

```python
# 执行模式
class PlanningMode(str, Enum):
    DIRECT = "direct"       # 直接执行，无需拆解
    DECOMPOSED = "decomposed"  # 需要拆解为多个子查询

# 对比目标
class CompareTarget(str, Enum):
    NONE = "none"
    YOY = "yoy"   # 同比
    MOM = "mom"   # 环比

# 时间范围类型
class TimeRangeType(str, Enum):
    ABSOLUTE = "absolute"   # 绝对时间（如 2024-03）
    RELATIVE = "relative"    # 相对时间（如 最近三个月）

# 组织范围类型
class OrgScopeType(str, Enum):
    REGION = "region"    # 区域
    STATION = "station"  # 电站
    DEPARTMENT = "department"  # 部门
    GROUP = "group"      # 集团
```

---

## 三、SQL 构建核心逻辑

### 3.1 入口方法：build()

```python
class AnalyticsIntentSQLBuilder:
    """基于 AnalyticsIntent 的 Schema-aware SQL 构造器"""

    def build(self, intent: AnalyticsIntent, *, department_code: str | None = None) -> dict:
        """根据 AnalyticsIntent 构造 SQL"""

        # 根据执行模式选择不同的构建策略
        if intent.planning_mode == PlanningMode.DECOMPOSED:
            return self._build_complex_sql(intent, department_code=department_code)
        else:
            return self._build_simple_sql(intent, department_code=department_code)
```

### 3.2 简单模式：_build_simple_sql()

适用于 `planning_mode = DIRECT`，生成单个 SQL 查询。

### 3.3 复杂模式：_build_complex_sql()

适用于 `planning_mode = DECOMPOSED`，需要生成多个子查询。

---

## 四、详细构建步骤

### 4.1 步骤一：解析指标定义

```python
# 根据 metric_name 或 metric_code 从 MetricCatalog 中查找指标定义
metric_definition = self.metric_catalog.resolve_metric(metric_name)
# 或
metric_definition = self.metric_catalog.resolve_metric(metric_code)
```

**指标定义结构**：

```python
class MetricDefinition(BaseModel):
    """指标定义"""

    metric_code: str            # "generation" (指标代码)
    metric_name: str            # "发电量" (指标名称)
    data_source: str           # "warehouse" (数据源)
    table_name: str            # "fact_power_generation" (表名)
    aggregation: str            # "SUM" (聚合方式)
    unit: str                   # "万千瓦时" (单位)
    description: str           # "电站发电量统计" (描述)
```

### 4.2 步骤二：获取表定义

```python
# 根据指标定义获取表结构信息
table_definition = self.schema_registry.get_table_definition(
    table_name=metric_definition.table_name,
    data_source=metric_definition.data_source,
)
```

**表定义结构**：

```python
class TableDefinition(BaseModel):
    """表结构定义"""

    name: str                        # "fact_power_generation"
    data_source: str                 # "warehouse"

    # 关键列映射
    metric_code_column: str          # "metric_code" (指标代码列)
    metric_name_column: str          # "metric_name" (指标名称列)
    metric_value_column: str         # "value" (指标值列)
    time_column: str                 # "stat_date" (时间列)

    # 维度列
    dimension_columns: dict          # {"region": "region_code", "station": "station_code"}

    # 安全过滤列
    department_filter_column: str | None  # "dept_code" (部门过滤列)
```

### 4.3 步骤三：解析时间范围

```python
# 将用户时间描述转换为具体的起止日期
time_range_dict = self._parse_time_range(intent)
# 输出：
# {
#     "start_date": "2024-03-01",
#     "end_date": "2024-03-31"
# }
```

**解析规则**：

| 用户输入 | 解析结果 |
|---------|---------|
| "2024-03" | 2024-03-01 ~ 2024-03-31 |
| "上个月" | 上月1日 ~ 上月末日 |
| "最近3个月" | 3个月前1日 ~ 今天 |
| "本月" | 本月1日 ~ 本月末日 |

### 4.4 步骤四：解析组织范围

```python
# 将用户组织描述转换为 WHERE 条件
org_scope_dict = self._parse_org_scope(intent, table_definition)
# 输出（如果有）：
# {"where_clause": "region_code = 'XJ'", "type": "region", "value": "XJ"}
```

### 4.5 步骤五：构建 WHERE 子句

```python
# 组合所有过滤条件
where_clauses = [
    # 1. 指标代码过滤（必须）
    f"{table_definition.metric_code_column} = '{metric_definition.metric_code}'",

    # 2. 时间范围过滤（必须）
    f"{table_definition.time_column} >= '{start_date}'",
    f"{table_definition.time_column} <= '{end_date}'",

    # 3. 组织范围过滤（可选）
    # f"{table_definition.dimension_columns['region']} = 'XJ'",

    # 4. 部门过滤（安全必须）
    # f"{table_definition.department_filter_column} = '{department_code}'",
]
```

### 4.6 步骤六：构建 SELECT 子句

```python
select_fields = [table_definition.metric_name_column]

# 处理对比目标（yoy/mom）
if compare_target in {"yoy", "mom"}:
    select_fields.extend([
        # 当前周期值
        f"""SUM(CASE
            WHEN {table_definition.time_column} >= '{start_date}'
            AND {table_definition.time_column} <= '{end_date}'
            THEN {table_definition.metric_value_column} ELSE 0 END) AS current_value""",

        # 对比周期值
        f"""SUM(CASE
            WHEN {table_definition.time_column} >= '{compare_start_date}'
            AND {table_definition.time_column} <= '{compare_end_date}'
            THEN {table_definition.metric_value_column} ELSE 0 END) AS compare_value""",
    ])
else:
    select_fields.append(
        f"SUM({table_definition.metric_value_column}) AS total_value"
    )
```

### 4.7 步骤七：处理 GROUP BY

```python
# 如果需要分组
if intent.group_by:
    group_by_rule = self.schema_registry.get_group_by_rule(
        intent.group_by,
        table_name=table_definition.name,
        data_source=data_source,
    )
    if group_by_rule:
        # 添加分组字段到 SELECT
        select_fields.append(
            f"{group_by_rule.select_expression} AS {group_by_rule.alias}"
        )
        group_by_fields.append(group_by_rule.group_expression)
```

### 4.8 步骤八：构建 ORDER BY 和 LIMIT

```python
# TOP N 排序
if intent.top_n:
    ranking_col = "current_value" if compare_target in {"yoy", "mom"} else "total_value"
    order_by_clause = f"ORDER BY {ranking_col} {sort_direction} LIMIT {intent.top_n}"

# 同比/环比查询默认按当前值降序
elif compare_target in {"yoy", "mom"} and not intent.group_by:
    order_by_clause = "ORDER BY current_value DESC"
```

---

## 五、完整 SQL 生成示例

### 5.1 示例一：简单查询

**用户问句**：`"查询新疆区域2024年3月发电量"`

**Intent 结构**：
```python
intent = AnalyticsIntent(
    metric=MetricIntent(metric_code="generation", metric_name="发电量"),
    time_range=TimeRangeIntent(type="absolute", value="2024-03", start="2024-03-01", end="2024-03-31"),
    org_scope=OrgScopeIntent(type="region", name="XJ"),
    compare_target=CompareTarget.NONE,
    planning_mode=PlanningMode.DIRECT,
)
```

**生成 SQL**：
```sql
SELECT
    metric_name,
    SUM(value) AS total_value
FROM fact_power_generation
WHERE
    metric_code = 'generation'
    AND stat_date >= '2024-03-01'
    AND stat_date <= '2024-03-31'
    AND region_code = 'XJ'
    AND dept_code = 'D001'
GROUP BY metric_name
```

---

### 5.2 示例二：同比查询

**用户问句**：`"查询新疆区域2024年3月发电量，和去年对比"`

**Intent 结构**：
```python
intent = AnalyticsIntent(
    metric=MetricIntent(metric_code="generation", metric_name="发电量"),
    time_range=TimeRangeIntent(type="absolute", value="2024-03", start="2024-03-01", end="2024-03-31"),
    org_scope=OrgScopeIntent(type="region", name="XJ"),
    compare_target=CompareTarget.YOY,
    planning_mode=PlanningMode.DIRECT,
)
```

**生成 SQL**：
```sql
SELECT
    metric_name,

    -- 当前周期值
    SUM(CASE
        WHEN stat_date >= '2024-03-01' AND stat_date <= '2024-03-31'
        THEN value ELSE 0 END) AS current_value,

    -- 去年同期值
    SUM(CASE
        WHEN stat_date >= '2023-03-01' AND stat_date <= '2023-03-31'
        THEN value ELSE 0 END) AS compare_value

FROM fact_power_generation
WHERE
    metric_code = 'generation'
    AND stat_date >= '2023-03-01'
    AND stat_date <= '2024-03-31'
    AND region_code = 'XJ'
    AND dept_code = 'D001'
GROUP BY metric_name
ORDER BY current_value DESC
```

---

### 5.3 示例三：TOP N 排名

**用户问句**：`"查询新疆区域2024年3月发电量，看看TOP10电站"`

**Intent 结构**：
```python
intent = AnalyticsIntent(
    metric=MetricIntent(metric_code="generation", metric_name="发电量"),
    time_range=TimeRangeIntent(type="absolute", value="2024-03", start="2024-03-01", end="2024-03-31"),
    org_scope=OrgScopeIntent(type="region", name="XJ"),
    compare_target=CompareTarget.NONE,
    group_by="station",
    top_n=10,
    planning_mode=PlanningMode.DIRECT,
)
```

**生成 SQL**：
```sql
SELECT
    metric_name,
    station_name AS station,
    SUM(value) AS total_value
FROM fact_power_generation
WHERE
    metric_code = 'generation'
    AND stat_date >= '2024-03-01'
    AND stat_date <= '2024-03-31'
    AND region_code = 'XJ'
    AND dept_code = 'D001'
GROUP BY metric_name, station_name
ORDER BY total_value DESC
LIMIT 10
```

---

### 5.4 示例四：同比 + 分组 + TOP N

**用户问句**：`"查询新疆区域2024年3月发电量，和去年对比，看看TOP10电站"`

**Intent 结构**：
```python
intent = AnalyticsIntent(
    metric=MetricIntent(metric_code="generation", metric_name="发电量"),
    time_range=TimeRangeIntent(type="absolute", value="2024-03", start="2024-03-01", end="2024-03-31"),
    org_scope=OrgScopeIntent(type="region", name="XJ"),
    compare_target=CompareTarget.YOY,
    group_by="station",
    top_n=10,
    planning_mode=PlanningMode.DIRECT,
)
```

**生成 SQL**：
```sql
SELECT
    metric_name,
    station_name AS station,

    -- 当前周期值
    SUM(CASE
        WHEN stat_date >= '2024-03-01' AND stat_date <= '2024-03-31'
        THEN value ELSE 0 END) AS current_value,

    -- 去年同期值
    SUM(CASE
        WHEN stat_date >= '2023-03-01' AND stat_date <= '2023-03-31'
        THEN value ELSE 0 END) AS compare_value

FROM fact_power_generation
WHERE
    metric_code = 'generation'
    AND stat_date >= '2023-03-01'
    AND stat_date <= '2024-03-31'
    AND region_code = 'XJ'
    AND dept_code = 'D001'
GROUP BY metric_name, station_name
ORDER BY current_value DESC
LIMIT 10
```

---

## 六、对比时间计算逻辑

### 6.1 同比计算（YOY）

```python
def _build_compare_range(self, start_date, end_date, compare_target):
    """构造环比/同比比较时间范围"""

    if compare_target == "yoy":
        # 同比：去年同期
        compare_start = start_date - 1 year
        compare_end = end_date - 1 year
    else:  # mom
        # 环比：上月同期
        compare_start = start_date - 1 month
        compare_end = end_date - 1 month

    return {
        "start_date": compare_start,
        "end_date": compare_end,
    }
```

### 6.2 月份平移处理

```python
def _shift_month(self, target_date, month_delta):
    """按月平移日期，并自动处理月底越界"""

    total_month = (target_date.year * 12 + target_date.month - 1) + month_delta
    new_year = total_month // 12
    new_month = total_month % 12 + 1
    max_day = calendar.monthrange(new_year, new_month)[1]
    new_day = min(target_date.day, max_day)  # 防止31号跳到2月的问题

    return target_date.replace(year=new_year, month=new_month, day=new_day)
```

---

## 七、复杂模式（Decomposed）

### 7.1 何时使用

当 `planning_mode = DECOMPOSED` 时，需要生成多个子查询：

```python
# 示例：需要查询"发电量 + 收入 + 成本"的综合分析
intent = AnalyticsIntent(
    planning_mode=PlanningMode.DECOMPOSED,
    required_queries=[
        RequiredQuery(query_name="current", period_role=PeriodRole.CURRENT, metric_code="generation"),
        RequiredQuery(query_name="yoy_baseline", period_role=PeriodRole.YOY_BASELINE, metric_code="generation"),
        RequiredQuery(query_name="revenue", period_role=PeriodRole.CURRENT, metric_code="revenue"),
    ],
)
```

### 7.2 复杂 SQL 构建流程

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        _build_complex_sql()                                  │
│                                                                              │
│  1. 遍历 required_queries，为每个子查询生成 SQL                               │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  for req_query in intent.required_queries:                         │   │
│  │      sub_sql = _build_required_query_sql(req_query, intent)        │   │
│  │      sub_queries.append(sub_sql)                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  2. 根据 period_role 分类                                                   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  main_query = 找到 period_role="current" 的查询                     │   │
│  │  baseline_query = 找到 period_role="yoy_baseline" 的查询            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  3. 返回复合 SQL Bundle                                                     │
│                                                                              │
│  output:                                                                    │
│  {                                                                            │
│      "generated_sql": main_query.generated_sql,                             │
│      "sub_queries": [sub_sql_1, sub_sql_2, ...],                           │
│      "builder_metadata": {                                                   │
│          "planning_mode": "decomposed",                                     │
│          "has_baseline_query": True,                                        │
│      }                                                                      │
│  }                                                                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 八、安全机制

### 8.1 部门过滤

所有 SQL 必须包含部门过滤：

```python
# 表定义中指定了部门过滤列
if table_definition.department_filter_column:
    where_clauses.append(
        f"{table_definition.department_filter_column} = '{department_code}'"
    )
```

### 8.2 白名单校验

SQL 生成后，必须经过 `SQL Guard` 校验：

```python
guard_result = sql_guard.validate(
    sql_bundle["generated_sql"],
    allowed_tables=schema_registry.get_allowed_tables(data_source),
    required_filter_column=table_definition.department_filter_column,
    required_filter_value=user_context.department_code,
)
```

---

## 九、输出结构

```python
{
    "generated_sql": """
        SELECT metric_name, SUM(value) AS total_value
        FROM fact_power_generation
        WHERE metric_code = 'generation'
        AND stat_date >= '2024-03-01'
        AND stat_date <= '2024-03-31'
        AND region_code = 'XJ'
        AND dept_code = 'D001'
        GROUP BY metric_name
    """,
    "metric_scope": "发电量",
    "data_source": "warehouse",
    "builder_metadata": {
        "planning_mode": "direct",
        "complexity": "simple",
        "group_by": None,
        "compare_target": "none",
        "top_n": None,
        "table_name": "fact_power_generation",
        "db_type": "postgresql",
        "effective_filters": {
            "metric_code": "generation",
            "time_range": {"start_date": "2024-03-01", "end_date": "2024-03-31"},
            "org_scope": "XJ",
            "department_code": "D001",
        },
    },
}
```

---

## 十、流程图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         analytics_build_sql 节点                            │
│                                                                              │
│  输入: AnalyticsIntent + UserContext                                        │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Step 1: 解析指标定义                                                  │   │
│  │                                                                      │   │
│  │ metric_catalog.resolve_metric(metric_name)                          │   │
│  │           ↓                                                          │   │
│  │ MetricDefinition(metric_code, table_name, aggregation, ...)          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Step 2: 获取表定义                                                    │   │
│  │                                                                      │   │
│  │ schema_registry.get_table_definition(table_name, data_source)        │   │
│  │           ↓                                                          │   │
│  │ TableDefinition(column_mappings, dimension_columns, ...)             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Step 3: 解析时间范围                                                  │   │
│  │                                                                      │   │
│  │ _parse_time_range(intent)                                            │   │
│  │           ↓                                                          │   │
│  │ {start_date: "2024-03-01", end_date: "2024-03-31"}                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Step 4: 解析组织范围                                                  │   │
│  │                                                                      │   │
│  │ _parse_org_scope(intent, table_definition)                           │   │
│  │           ↓                                                          │   │
│  │ {where_clause: "region_code = 'XJ'"}                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Step 5: 构建 SQL                                                     │   │
│  │                                                                      │   │
│  │ - SELECT: metric_name, 聚合函数(value)                               │   │
│  │ - FROM: table_name                                                   │   │
│  │ - WHERE: metric_code, time_range, org_scope, dept_code              │   │
│  │ - GROUP BY: metric_name, [group_by_field]                           │   │
│  │ - ORDER BY: [current_value] [DESC] [LIMIT n]                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  输出: SQL Bundle                                                           │
│  {generated_sql, metric_scope, data_source, builder_metadata}             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 十一、总结

| 步骤 | 输入 | 处理 | 输出 |
|-----|------|------|------|
| 1 | metric_name | MetricCatalog.resolve_metric | MetricDefinition |
| 2 | MetricDefinition | SchemaRegistry.get_table_definition | TableDefinition |
| 3 | intent.time_range | _parse_time_range | start_date, end_date |
| 4 | intent.org_scope | _parse_org_scope | WHERE clause |
| 5 | 所有组件 | 组装 SQL | generated_sql |

核心设计理念：
1. **Schema-aware**：所有字段、表都来自注册表，不允许硬编码
2. **安全优先**：强制部门过滤，禁止未授权访问
3. **灵活组合**：支持简单/复杂、单表/多表、同比/环比等多种查询

---

**文档版本**: v1.0
**最后更新**: 2026-05-02
**适用模块**: Analytics Workflow、SQL Builder
