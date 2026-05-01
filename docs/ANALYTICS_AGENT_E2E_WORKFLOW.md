# 经营分析 Agent 完整链路文档（E2E 教程）

> 本文档通过真实用户问句，一步步展示经营分析 Agent 从输入到输出的完整执行链路。
>
> 目标读者：前端开发理解 API 契约与状态变化；后端开发理解模块边界；面试讲解用真实场景串起架构。
>
> 所有示例基于新疆能源集团经营分析语境，使用合理化的 mock 经营数据。

---

## 目录

1. [系统总览：一条请求的完整旅程](#一系统总览)
2. [场景 1：简单明确查询](#场景-1简单明确查询)
3. [场景 2：缺少指标，需要澄清](#场景-2缺少指标需要澄清)
4. [场景 3：缺少时间，需要澄清](#场景-3缺少时间需要澄清)
5. [场景 4：澄清后恢复执行](#场景-4澄清后恢复执行)
6. [场景 5：复杂问题触发 ReAct Planning](#场景-5复杂问题触发-react-planning)
7. [场景 6：规则低置信触发 LLM Slot Fallback](#场景-6规则低置信触发-llm-slot-fallback)
8. [场景 7：SQL Guard 阻断](#场景-7sql-guard-阻断)
9. [场景 8：SQL Gateway 临时失败重试](#场景-8sql-gateway-临时失败重试)
10. [场景 9：图表、洞察、报告块降级](#场景-9图表洞察报告块降级)
11. [场景 10：导出报告](#场景-10导出报告)
12. [场景 11：高风险导出进入人工审核](#场景-11高风险导出进入人工审核)
13. [附录：核心状态字典](#附录核心状态字典)

---

## 一、系统总览

### 1.1 一条经营分析请求的完整旅程

```
用户输入
  → API 路由（routers/analytics.py）
    → AnalyticsService.submit_query() 编排主链路
      → SemanticResolver 口语化语义补强 + 多轮上下文承接
      → SlotValidator 校验必填槽位与冲突
      → AnalyticsPlanner.plan() 整合规划结果
      → 如果不满足最小可执行条件 → 返回澄清
      → 如果满足 → 进入执行链路：
        → SQLBuilder 构造 schema-aware SQL
        → SQLGuard 安全检查
        → SQLGateway 通过 SQL MCP 执行只读查询
        → DataMaskingService 脱敏处理
        → InsightBuilder 生成洞察卡片
        → ReportFormatter 生成报告块
        → 写入 output_snapshot（轻快照）/ analytics_result_repository（重结果）
        → SQLAuditRepository 记录审计
      → 返回分级响应（lite / standard / full）
```

### 1.2 关键模块职责边界

| 模块 | 职责 | 不负责 |
|---|---|---|
| SemanticResolver | 口语解析、多轮上下文继承、LLM fallback 补槽位 | 判断是否可执行 |
| SlotValidator | 判断必填槽位是否齐全、是否存在冲突 | 补强槽位 |
| ClarificationGenerator | 生成结构化澄清问题和建议选项 | 决定是否要澄清 |
| SQLBuilder | 将结构化槽位转成 schema-aware SQL | 执行 SQL、安全检查 |
| SQLGuard | 校验 SQL 只读性、表白名单、字段白名单、部门过滤、自动补 LIMIT | 生成 SQL |
| SQLGateway | 通过 SQL MCP Server 执行只读查询 | 直接连数据库 |
| DataMaskingService | 按字段级权限对结果做脱敏/隐藏 | 查权限 |
| InsightBuilder | 基于规则生成洞察卡片 | LLM 自由分析 |
| ReportFormatter | 将结果整理为结构化报告块 | 生成文件导出 |

### 1.3 数据存储边界

| 存储位置 | 存什么 | 不存什么 |
|---|---|---|
| task_run.output_snapshot（轻快照） | summary、slots、sql_preview、row_count、latency_ms、compare_target、group_by、governance_decision（简版）、timing_breakdown | tables、insight_cards、report_blocks、chart_spec |
| analytics_result_repository（重结果） | tables、insight_cards、report_blocks、chart_spec、masking_result | 轻快照字段 |
| slot_snapshot | required_slots、collected_slots、missing_slots、resume_step | SQL 结果、审计记录 |
| clarification_event | question_text、target_slots、user_reply、resolved_slots、status | workflow 上下文 |

> **为什么 output_snapshot 不能无限膨胀？**
>
> task_run 是整个平台的任务运行主表，如果把 tables（可能是几百行大 JSON）、insight_cards、report_blocks、chart_spec 全部塞进同一行的 JSONB 字段：
> 1. 单行写入和读取的 IO 压力陡增；
> 2. PG 的 TOAST 机制虽然能存大 JSON，但查询 task_run 列表时会拖慢所有读取；
> 3. 任务列表页每次列 20 条 task_run 就要加载 20 个大 JSON，成本过高。
>
> **为什么拆轻快照与重结果？**
>
> 轻快照保留"能不能答复用户、任务是否成功"的最小必读字段；重结果保留"需要展开分析、用于导出、用于下钻"的大对象。两者解耦后：主查询接口默认只返回 lite 视图（只读轻快照），payload 显著减小；导出和详情页再去 analytics_result_repository 按需拉取重结果；前端轮询 task_run 状态时不需要每次都加载完整结果。

---

## 场景 1：简单明确查询

> 用户问句：
>
> **"查询新疆区域 2024 年 3 月的发电量"**

### 这个场景要解决什么问题

用户给出了明确的三要素（指标+时间+范围），系统不需要追问任何信息，可以直接执行查询并返回结果。这是经营分析最常见的理想场景。

### 系统执行步骤

```
1. SemanticResolver 解析 → metric=发电量, time_range=2024年3月, org_scope=新疆区域
2. SlotValidator 校验 → is_executable=true
3. SQLBuilder 构造 schema-aware SQL
4. SQLGuard 安全检查（只读校验、表白名单、部门过滤、自动补 LIMIT）
5. SQLGateway 通过 SQL MCP Server 执行只读查询
6. DataMaskingService 脱敏处理
7. 生成 Summary / Chart Spec / Insight Cards / Report Blocks
8. 写入 output_snapshot（轻快照）+ analytics_result_repository（重结果）
9. 记录 SQL Audit
10. 按 output_mode 返回分级视图
```

### Planner 识别结果

| 字段 | 示例值 | 中文含义 |
|---|---|---|
| metric | 发电量 | 用户要查询的经营指标 |
| time_range.type | absolute_month | 时间范围类型：绝对月份 |
| time_range.label | 2024年3月 | 时间的可读标签 |
| time_range.start_date | 2024-03-01 | 查询开始日期 |
| time_range.end_date | 2024-03-31 | 查询结束日期 |
| org_scope.type | region | 组织范围类型：区域 |
| org_scope.value | 新疆区域 | 组织范围具体值 |
| planning_source | rule | 规划来源：规则匹配 |
| confidence | 0.95 | 置信度：高 |
| is_executable | true | 满足最小可执行条件 |

### SQLBuilder 输出

```json
{
  "generated_sql": "SELECT station, SUM(power_generation) AS total_value FROM analytics_metrics_daily WHERE date >= '2024-03-01' AND date <= '2024-03-31' AND org_region = '新疆区域' AND department_code = 'analytics-center' GROUP BY station ORDER BY total_value DESC",
  "data_source": "local_analytics",
  "metric_scope": "发电量",
  "builder_metadata": {
    "effective_filters": {
      "department_code": "analytics-center",
      "date_range": "2024-03-01 ~ 2024-03-31",
      "org_region": "新疆区域"
    }
  }
}
```

| 字段 | 中文含义 |
|---|---|
| generated_sql | Schema-aware 受控模板生成的 SQL |
| data_source | 数据源标识，决定去哪个数据库执行 |
| metric_scope | 指标中文名，用于前端展示和审计 |
| effective_filters | 实际生效的过滤条件（含部门治理字段） |

### SQLGuard 校验通过

SQLGuard 做 9 层校验全部 PASS，输出：

```json
{
  "is_safe": true,
  "checked_sql": "SELECT station, SUM(power_generation) AS total_value FROM analytics_metrics_daily WHERE ... LIMIT 500",
  "blocked_reason": null
}
```

### SQL MCP 执行结果（mock 业务数据）

| station | total_value |
|---|---|
| 哈密电站 | 4200 MWh |
| 吐鲁番电站 | 3100 MWh |
| 北疆风电场 | 2900 MWh |
| 南疆光伏站 | 2600 MWh |

### Chart Spec（图表描述）

```json
{
  "chart_type": "bar",
  "title": "发电量station分布",
  "x_field": "station",
  "y_field": "total_value",
  "series_field": null,
  "dataset_ref": "main_result",
  "data_mapping": {
    "primary_series": "total_value",
    "secondary_series": null
  }
}
```

| 字段 | 中文含义 |
|---|---|
| chart_type | 图表类型：bar=柱状图，line=折线图，pie=饼图，ranking_bar=排行榜柱状图 |
| title | 图表标题 |
| x_field / y_field | X/Y 轴对应字段 |
| data_mapping.primary_series | 主数据系列字段名 |

### Insight Cards（洞察卡片）

```json
[
  {
    "title": "发电量station排名洞察",
    "type": "ranking",
    "summary": "当前排名第一的是 哈密电站，数值为 4200。",
    "evidence": {
      "dimension": "哈密电站",
      "value": 4200,
      "row_count": 4
    }
  }
]
```

| 字段 | 中文含义 |
|---|---|
| title | 洞察卡片标题 |
| type | 洞察类型：ranking=排名，trend=趋势，comparison=对比，anomaly=异常提醒 |
| summary | 洞察摘要，可直接展示给用户 |
| evidence | 支撑洞察的证据数据 |

### Report Blocks（报告块，部分示例）

```json
[
  { "block_type": "overview", "title": "分析概览", "content": "已完成"发电量"在2024年3月范围内的排名查询..." },
  { "block_type": "key_findings", "title": "关键发现", "content": [{"type": "ranking", "summary": "当前排名第一的是 哈密电站，数值为 4200。"}] },
  { "block_type": "ranking", "title": "排名分析", "content": [...] },
  { "block_type": "data_table", "title": "main_result", "content": {"columns": ["station","total_value"], "rows": [...]} },
  { "block_type": "chart", "title": "发电量station分布", "content": {"chart_type": "bar", ...} },
  { "block_type": "governance_note", "title": "治理说明", "content": {"masked_fields": ["station"], ...} },
  { "block_type": "risk_note", "title": "风险提示", "content": "当前结果基于受控模板 SQL..." },
  { "block_type": "recommendation", "title": "后续建议", "content": "如需更深入分析..." }
]
```

| block_type | 中文含义 |
|---|---|
| overview | 分析概览 |
| key_findings | 关键发现 |
| ranking / trend | 排名/趋势分析 |
| data_table | 数据表 |
| chart | 图表 |
| governance_note | 治理说明 |
| risk_note | 风险提示 |
| recommendation | 后续建议 |

### 存储：轻快照 vs 重结果

**轻快照写入 task_run.output_snapshot**：

```json
{
  "summary": "已完成"发电量"在2024年3月范围内的排名查询，当前返回 4 行结果。",
  "sql_preview": "SELECT station, SUM(power_generation) AS total_value FROM ... LIMIT 500",
  "safety_check_result": {"is_safe": true},
  "metric_scope": "发电量",
  "data_source": "local_analytics",
  "row_count": 4,
  "latency_ms": 45,
  "compare_target": null,
  "group_by": "station",
  "governance_decision": {"masked_fields": ["station"], "governance_action": "fields_masked"},
  "slots": {"metric": "发电量", "time_range": {"label": "2024年3月"}, "org_scope": {"value": "新疆区域"}, "group_by": "station"},
  "planning_source": "rule"
}
```

**重内容写入 analytics_result_repository**：

```json
{
  "tables": [{"name": "main_result", "columns": ["station", "total_value"], "rows": [["哈***站", 4200], ["吐***站", 3100], ...]}],
  "insight_cards": [{"title": "发电量station排名洞察", "type": "ranking", "summary": "..."}],
  "report_blocks": [...],
  "chart_spec": {"chart_type": "bar", "title": "发电量station分布"},
  "masking_result": {"masked_fields": ["station"], "governance_decision": "fields_masked"}
}
```

### 任务状态变化

| 阶段 | task_run.status | task_run.sub_status | 中文含义 |
|---|---|---|---|
| 创建任务 | executing | planning_query | 正在意图识别 |
| 构造 SQL | executing | building_sql | 正在构造 SQL |
| 安全检查 | executing | checking_sql | 正在 SQL Guard 校验 |
| 执行查询 | executing | running_sql | 正在执行 SQL |
| 生成结果 | succeeded | explaining_result | 正在生成摘要/图表 |
| 最终状态 | succeeded | explaining_result | 执行成功 |

### 最终返回（output_mode=full）

```json
{
  "data": {
    "run_id": "run_200", "trace_id": "tr_050",
    "summary": "已完成"发电量"在2024年3月范围内的排名查询，当前返回 4 行结果。",
    "row_count": 4, "latency_ms": 45,
    "metric_scope": "发电量", "data_source": "local_analytics",
    "compare_target": null, "group_by": "station",
    "sql_preview": "SELECT station, SUM(power_generation) AS total_value FROM ... LIMIT 500",
    "chart_spec": {"chart_type": "bar", "title": "发电量station分布"},
    "insight_cards": [...], "tables": [...], "report_blocks": [...],
    "safety_check_result": {"is_safe": true},
    "audit_info": {"execution_status": "succeeded", "row_count": 4, "latency_ms": 45},
    "masked_fields": ["station"],
    "effective_filters": {"department_code": "analytics-center"},
    "governance_decision": {"governance_action": "fields_masked"},
    "timing_breakdown": {"planning_ms": 2.1, "sql_build_ms": 1.3, "sql_guard_ms": 0.5, "sql_execute_ms": 45.0, "masking_ms": 0.3, "insight_ms": 0.2, "report_ms": 0.4}
  },
  "meta": {"conversation_id": "conv_200", "run_id": "run_200", "status": "succeeded", "is_async": false}
}
```

### output_mode 返回分级

| output_mode | 返回内容 |
|---|---|
| lite（默认） | summary、row_count、latency_ms、run_id、trace_id、metric_scope、data_source、compare_target、group_by |
| standard | lite + sql_preview、chart_spec、insight_cards、masked_fields、effective_filters、governance_decision |
| full | standard + tables、report_blocks、sql_explain、safety_check_result、permission_check_result、data_scope_result、audit_info、timing_breakdown |

### 本场景关键结论

1. 用户给出明确三要素时，系统一次性执行成功，不依赖 LLM；
2. SQL 不是自由生成的，而是 SQLBuilder 基于 schema 和槽位的受控模板；
3. 每一层（构建→检查→执行→脱敏→解释）都有明确的边界；
4. 重内容分离存储：轻快照写入 output_snapshot，重结果写入 analytics_result_repository；
5. 前端可通过 output_mode 控制返回粒度：列表页用 lite，详情页用 full。

---

## 场景 2：缺少指标，需要澄清

> 用户问句：
>
> **"帮我看一下新疆区域上个月的情况"**

### 这个场景要解决什么问题

用户表达了分析意图，也给出了组织范围和时间，但没有说明想看什么指标。系统不能替用户猜测——这是安全性和业务严谨性的底线。

### 系统执行步骤

```
1. SemanticResolver 解析 → time_range=上个月, org_scope=新疆区域, metric=null
2. SlotValidator 校验 → missing_slots=["metric"], is_executable=false
3. ClarificationGenerator 生成澄清 → clarification_type="missing_required_slot"
4. 创建 slot_snapshot（保存已收集槽位）
5. 创建 clarification_event
6. task_run.status = "awaiting_user_clarification"
7. 返回澄清给用户
```

### 关键输入输出

**SemanticResolver 解析结果**：

| 字段 | 示例值 | 中文含义 |
|---|---|---|
| metric | null | 未识别到指标 |
| time_range.type | relative_30_days | 时间范围：相对近 30 天 |
| time_range.label | 近一个月 | 时间可读标签 |
| org_scope.value | 新疆区域 | 组织范围 |
| planning_source | rule | 规则匹配 |
| confidence | 0.7 | 中等置信度 |

**ClarificationGenerator 输出**：

```json
{
  "clarification_type": "missing_required_slot",
  "question": "当前分析范围已经基本确定，但还缺少主指标。你想看发电量、收入、成本、利润还是产量？",
  "target_slots": ["metric"],
  "reason": "缺少主指标，无法安全构造 SQL",
  "suggested_options": ["发电量", "收入", "成本", "利润", "产量"]
}
```

**slot_snapshot**（保存已收集槽位，供恢复执行使用）：

| 字段 | 示例值 | 中文含义 |
|---|---|---|
| run_id | run_201 | 关联的任务运行 ID |
| collected_slots | {"time_range": {...}, "org_scope": {...}} | 已收集槽位 |
| missing_slots | ["metric"] | 缺失槽位 |
| awaiting_user_input | true | 等待用户补充 |
| resume_step | resume_after_analytics_slot_fill | 恢复执行入口步骤 |

**clarification_event**：

| 字段 | 示例值 | 中文含义 |
|---|---|---|
| clarification_id | clr_200 | 澄清事件唯一 ID |
| question_text | 当前分析范围已经基本确定... | 澄清问题文本 |
| target_slots | ["metric"] | 期望用户补充的槽位 |
| status | pending | 等待用户回复 |

### 状态变化

| 阶段 | task_run.status | 中文含义 |
|---|---|---|
| 创建任务 | executing（planning_query） | 开始分析 |
| 发现缺槽位 | awaiting_user_clarification（awaiting_slot_fill） | 等待用户补充 |

### API 返回

```json
{
  "data": {
    "clarification": {
      "clarification_id": "clr_200",
      "question": "当前分析范围已经基本确定，但还缺少主指标。你想看发电量、收入、成本、利润还是产量？",
      "target_slots": ["metric"],
      "clarification_type": "missing_required_slot",
      "reason": "缺少主指标，无法安全构造 SQL",
      "suggested_options": ["发电量", "收入", "成本", "利润", "产量"]
    }
  },
  "meta": {
    "conversation_id": "conv_200", "run_id": "run_201",
    "status": "awaiting_user_clarification", "need_clarification": true
  }
}
```

| 字段 | 中文含义 |
|---|---|
| need_clarification | 是否需要用户补充信息 |
| clarification_id | 澄清事件 ID，后续回复时使用 |
| question | 返回给用户的追问文本 |
| target_slots | 本次期望用户补充的槽位名称 |
| clarification_type | missing_required_slot=缺必填槽位, slot_conflict=槽位冲突 |
| suggested_options | 候选选项，前端可渲染为快捷选择按钮 |

### 本场景关键结论

1. 系统缺必填槽位时，绝不自行猜测，必须结构化澄清；
2. 已收集的槽位保存到 slot_snapshot，用户补充后不需重新输入；
3. 澄清由 SlotValidator 规则决定，不是 LLM 决定。

---

## 场景 3：缺少时间，需要澄清

> 用户问句：
>
> **"查询新疆区域发电量"**

### 系统执行步骤

规则识别出 metric=发电量、org_scope=新疆区域，但 time_range 未匹配 → SlotValidator 判断 missing_slots=["time_range"] → 返回澄清。

### 澄清输出

```json
{
  "clarification_type": "missing_required_slot",
  "question": "你想看哪个时间范围？例如上个月、本月、2024年3月。",
  "target_slots": ["time_range"],
  "reason": "缺少时间范围，无法安全构造 SQL",
  "suggested_options": ["上个月", "本月", "近一个月", "2024年3月"]
}
```

### 本场景关键结论

metric 和 time_range 是两个必填槽位，缺一不可。不同缺槽位场景给出不同的 suggested_options。

---

## 场景 4：澄清后恢复执行

> 承场景 2，用户回答澄清：
>
> **"看发电量"**

### 恢复机制说明

澄清恢复不是重新发起一次全新 API，而是：
1. 根据 `clarification_id` 找到之前的澄清事件；
2. 读取 `slot_snapshot` 中保存的已收集槽位；
3. 将用户补充的新槽位与已有槽位合并；
4. 重新做 SlotValidator 校验；
5. 满足条件后重新进入执行链路。

> "恢复 workflow 不是恢复原来的 Python 线程，而是根据 run_id、clarification_id、slot_snapshot 重新构造状态，并重新进入 StateGraph 执行。"

### 系统执行步骤

```
1. POST /api/v1/clarifications/clr_200/reply {"reply": "看发电量"}
2. ClarificationService 读取 clarification_event → 获取 run_id=run_201
3. 读取 slot_snapshot → 获取 time_range、org_scope
4. 合并槽位 → metric="看发电量", time_range=已有值, org_scope=已有值
5. 更新 clarification_event → status="resolved"
6. 更新 slot_snapshot → awaiting_user_input=false
7. task_run.status → "succeeded"（当前阶段最小 mock）
```

### 状态变化表

| 阶段 | task_run.status | clarification_event.status | slot_snapshot.awaiting_user_input | 中文含义 |
|---|---|---|---|---|
| 初次缺槽位 | awaiting_user_clarification | pending | true | 等待用户补充 |
| 用户补充后 | succeeded | resolved | false | 已补充，恢复执行 |
| 完成 | succeeded | resolved | false | 执行成功 |

### API 返回

```json
{
  "data": {"message": "已收到补充信息，任务继续执行"},
  "meta": {
    "conversation_id": "conv_200", "run_id": "run_201",
    "status": "succeeded", "sub_status": "resumed_after_clarification",
    "need_clarification": false
  }
}
```

### 本场景关键结论

1. 澄清回复只需 clarification_id，不需重新传 conversation_id；
2. 已收集的槽位不会因等待而丢失——slot_snapshot 保存了中间态；
3. 当前为最小 mock 实现，后续接入真实 workflow 恢复（重新进入 _execute_analytics_plan）。

---

## 场景 5：复杂问题触发 ReAct Planning

> 用户问句：
>
> **"分析新疆区域近三个月发电量下降的原因，并和去年同期对比，看哪些电站拖累最大"**

### 为什么是复杂问题

这个问句包含多种分析诉求：趋势分析（近三个月）、同比对比、排名分析（拖累最大意味着 sort_direction=asc）、原因分析。单一规则难以准确处理，需要 ReAct Planning 多步推理。

### ReAct 的边界

- ReAct 只在 analytics_plan 节点内部运行；
- ReAct 不生成 SQL、不执行 SQL、不绕过 SQL Guard；
- ReAct 输出必须是结构化槽位（AnalyticsPlan），不是 SQL；
- ReAct 输出必须经过 ReactPlanValidator。

> 简单说：**ReAct 负责"想清楚要查什么"，不负责"怎么查"。**

### ReAct Step 1

| 字段 | 示例值 | 中文含义 |
|---|---|---|
| thought | 用户问题包含趋势、同比和电站排名，需要确认指标和维度 | 模型的规划思考摘要 |
| action | metric_catalog_lookup | 只读工具：查询指标目录 |
| action_input | {"query": "发电量"} | 工具输入参数 |

**Observation**：

| 字段 | 示例值 | 中文含义 |
|---|---|---|
| matched | true | 匹配到指标 |
| metric | 发电量 | 指标名称 |
| metric_code | power_generation | 指标编码 |
| sensitivity_level | medium | 敏感级别 |

### ReAct Step 2

| 字段 | 示例值 | 中文含义 |
|---|---|---|
| thought | 需要确认可用表结构和维度字段 | 思考 |
| action | schema_registry_lookup | 只读工具：查询 schema |
| action_input | {"data_source": "local_analytics", "table": "analytics_metrics_daily"} | 工具输入 |

**Observation**：

| 字段 | 示例值 | 中文含义 |
|---|---|---|
| database_type | sqlite | 数据库类型 |
| columns | ["date","station","power_generation","org_region",...] | 可用字段 |
| available_dimensions | ["month", "station", "region"] | 可用维度 |

### ReAct Final Plan Candidate

| 字段 | 示例值 | 中文含义 |
|---|---|---|
| metric | 发电量 | 主指标 |
| time_range | 近三个月 | 时间范围 |
| org_scope | 新疆区域 | 组织范围 |
| group_by | station | 按电站分组 |
| compare_target | yoy | 同比 |
| sort_direction | asc | 升序（拖累最大的排前面） |
| top_n | 5 | 返回前 5 |
| confidence | 0.86 | ReAct 对规划结果的置信度 |

### 本场景关键结论

1. 复杂多诉求问句通过 ReAct 多步推理完成槽位补全；
2. ReAct 只规划"怎么查"，不负责执行 SQL；
3. 后续仍然走 SQLBuilder → SQLGuard → SQLGateway 标准流程。

---

## 场景 6：规则低置信触发 LLM Slot Fallback

> 用户问句：
>
> **"新疆那边最近电量咋样"**

### 为什么需要 LLM Fallback

规则能识别 `org_scope=新疆区域`、`time_range=近一个月`，但"电量"是否为"发电量"置信度较低。LLM Slot Fallback 只做槽位补强，不生成 SQL，不越权判断可执行性。

### LLM Slot Fallback 输出

| 字段 | 示例值 | 中文含义 |
|---|---|---|
| metric | 发电量 | LLM 补强的指标 |
| time_range | 近一个月 | 规则/LLM 识别的时间 |
| org_scope | 新疆区域 | 组织范围 |
| confidence | 0.78 | 置信度 |
| should_use | true | 是否建议使用此次补强 |
| reason | 用户口语中的"电量"在经营分析语境中通常对应发电量 | LLM 给出的简短原因 |

### LLM Fallback 的边界

- 它不是 ReAct（不会多步循环）；
- 它不生成 SQL；
- 它的输出必须经过 AnalyticsSlotFallbackValidator；
- SlotValidator 仍然决定 is_executable，LLM 不能越权。

---

## 场景 7：SQL Guard 阻断

> 用户问句/系统构造出的 SQL：
>
> **"查询所有区域所有用户明细"** → 生成的 SQL 缺少部门过滤条件

### 详细阻断过程

假设因某种原因 SQLBuilder 生成了这条 SQL：

```sql
SELECT * FROM analytics_metrics_daily WHERE date >= '2024-03-01'
```

SQLGuard 校验流程：

```
校验 1：非空检查 → PASS
校验 2：只读检查（以 SELECT 开头）→ PASS
校验 3：多语句检查 → PASS
校验 4：注释检查 → PASS
校验 5：危险关键字检查 → PASS
校验 6：表白名单检查（analytics_metrics_daily ✓）→ PASS
校验 7：字段白名单检查（预留）→ PASS
校验 8：部门过滤检查 → FAIL
  原因：缺少 department_code = 'analytics-center' 过滤条件
```

### SQL Guard 阻断结果

```json
{
  "is_safe": false,
  "checked_sql": null,
  "blocked_reason": "缺少必需的数据范围过滤：department_code",
  "governance_detail": {
    "stage": "data_scope_check",
    "required_filter_column": "department_code",
    "required_filter_value": "analytics-center"
  }
}
```

### 关于重试

SQL Guard blocked **不能重试**。这与 SQL Gateway timeout（场景 8）有本质区别：
- SQL Guard blocked：治理规则层面拒绝，重试也不会通过；
- SQL Gateway timeout：临时网络/负载问题，可以重试；
- 权限失败：也不可重试。

### API 返回

```json
{
  "success": false,
  "error_code": "SQL_GUARD_BLOCKED",
  "message": "SQL 安全检查未通过",
  "detail": {
    "blocked_reason": "缺少必需的数据范围过滤：department_code"
  }
}
```

### 任务状态变化

| 阶段 | task_run.status | 中文含义 |
|---|---|---|
| 构造 SQL | executing（building_sql） | 正在构造 |
| SQL Guard 阻断 | failed（checking_sql） | 安全检查失败，任务终止 |

---

## 场景 8：SQL Gateway 临时失败重试

> 用户问句：
>
> **"查询新疆区域 2024 年 3 月发电量"**

### 重试模拟

SQL Gateway 第一次调用因网络超时失败，系统判断这是临时错误，发起重试。

**retry_history 字段说明**：

| 字段 | 示例值 | 中文含义 |
|---|---|---|
| node_name | analytics_execute_sql | 发生重试的节点 |
| attempt | 1 | 第几次尝试 |
| error_type | TimeoutError | 错误类型 |
| error_message | SQL Gateway 请求超时 | 错误信息 |

### 重试策略

- SQL Gateway 超时：可重试一次；
- SQL Guard blocked：不可重试；
- 权限失败：不可重试。

### 最终任务状态

task_run.status = succeeded，retry_count = 1（在 metadata 中记录重试历史）。

---

## 场景 9：图表、洞察、报告块降级

> 用户问句：
>
> **"生成新疆区域 2024 年 3 月发电量的完整分析"**

### 降级模拟

SQL 执行成功，但 Chart Spec 生成失败（例如数据不满足图表条件）、Report Blocks 部分生成失败。系统容忍这些非关键组件失败，主查询仍然成功。

### 降级原则

> - 图表、洞察、报告块可以降级；
> - SQL 执行失败不能降级成成功；
> - 系统不能编造查询结果。

### 最终返回

| 字段 | 示例值 | 中文含义 |
|---|---|---|
| summary | 2024年3月新疆区域发电量为 12800 MWh | 摘要 |
| degraded | true | 是否发生降级 |
| degraded_features | chart_spec, report_blocks | 降级的功能列表 |
| row_count | 4 | 查询结果行数 |

---

## 场景 10：导出报告

> 用户操作：
>
> **"把这次分析导出成 PDF"**

### 导出数据来源

- task_run.output_snapshot 不保存完整 rows
- 完整表格、图表、洞察、报告块从 analytics_result_repository 读取
- 导出不是重新查询数据库，而是基于已保存结果生成报告

### 系统执行步骤

```
1. POST /api/v1/analytics/runs/run_200/export {"export_type": "pdf"}
2. 校验 run status = succeeded
3. 读取 output_snapshot（轻快照）
4. 读取 analytics_result_repository（重结果：tables/insight_cards/report_blocks/chart_spec）
5. ReviewPolicy 评估：result_count < 100、非正式导出格式 → review_required=false
6. 创建 export_task，状态 = "running"
7. Report MCP 生成 PDF 文件
8. 更新 export_task 状态 = "succeeded"
```

### export_task 返回

| 字段 | 示例值 | 中文含义 |
|---|---|---|
| export_id | export_001 | 导出任务 ID |
| run_id | run_001 | 对应的经营分析任务 ID |
| format | pdf | 导出格式 |
| status | succeeded | 导出任务状态 |
| review_required | false | 是否需要人工审核 |
| filename | analytics_run_001_report.pdf | 生成的文件名 |
| artifact_path | /storage/exports/export_001.pdf | 文件存储路径 |

---

## 场景 11：高风险导出进入人工审核

> 用户操作：
>
> **"导出包含敏感经营指标的完整报告"**

### Review Policy 判断逻辑

Review Policy 评估规则（确定性本地规则，非 LLM）：

1. 导出格式为正式格式（pdf/docx）→ 触发审核，review_level=high；
2. 结果包含敏感字段 → 触发审核；
3. 结果包含脱敏字段 → 触发审核；
4. 数据源非 local_analytics → 触发审核。

### review_task 字段说明

| 字段 | 示例值 | 中文含义 |
|---|---|---|
| review_id | review_001 | 审核任务 ID |
| subject_type | analytics_export | 审核对象类型 |
| subject_id | export_001 | 被审核的导出任务 ID |
| review_status | pending | 审核状态：等待审核 |
| review_level | high | 审核级别 |
| review_reason | 正式导出类型需要人工复核；结果包含敏感字段治理或脱敏处理 | 审核原因 |

### 状态流转

```json
{
  "export_id": "export_001",
  "status": "awaiting_human_review",
  "review_required": true,
  "review_status": "pending"
}
```

### 审核通过示例

```json
{
  "review_status": "approved",
  "reviewer_name": "经营管理部审核员",
  "review_comment": "允许导出，仅限内部使用"
}
```

### 审核拒绝示例

```json
{
  "review_status": "rejected",
  "reviewer_name": "经营管理部审核员",
  "review_comment": "导出范围过大，请缩小区域或时间范围"
}
```

### 审核通过后恢复导出

系统调用 `resume_export_after_review(export_id)`，校验 review_status=approved 后，继续执行 `_render_export_task` 完成文件生成。

---

## 附录：核心状态字典

### task_run.status

| 状态值 | 中文含义 | 说明 |
|---|---|---|
| executing | 执行中 | 任务正在运行 |
| succeeded | 执行成功 | 任务正常完成 |
| failed | 执行失败 | 任务异常终止 |
| awaiting_user_clarification | 等待用户补充信息 | 需要用户回复澄清问题 |
| cancelled | 已取消 | 用户主动取消 |

### task_run.sub_status（部分常用值）

| 子状态值 | 中文含义 |
|---|---|
| planning_query | 正在进行意图识别与槽位提取 |
| building_sql | 正在构造 SQL |
| checking_sql | 正在进行 SQL Guard 安全检查 |
| running_sql | 正在通过 SQL MCP 执行查询 |
| explaining_result | 正在生成摘要/图表/洞察 |
| awaiting_slot_fill | 等待用户补充槽位 |
| resumed_after_clarification | 澄清后恢复执行成功 |

### export_task.status

| 状态值 | 中文含义 |
|---|---|
| pending | 等待执行 |
| running | 正在导出 |
| succeeded | 导出成功 |
| failed | 导出失败 |
| awaiting_human_review | 等待人工审核 |

### clarification_event.status

| 状态值 | 中文含义 |
|---|---|
| pending | 等待用户回复 |
| resolved | 用户已回复，澄清已解决 |

### 错误码速查

| 错误码 | 中文含义 |
|---|---|
| SQL_GUARD_BLOCKED | SQL 安全检查未通过 |
| ANALYTICS_METRIC_PERMISSION_DENIED | 指标权限不足 |
| ANALYTICS_DATA_SOURCE_PERMISSION_DENIED | 数据源权限不足 |
| ANALYTICS_DATA_SCOPE_DENIED | 数据范围权限不足 |
| ANALYTICS_RUN_NOT_FOUND | 经营分析任务不存在 |
| ANALYTICS_EXPORT_FAILED | 导出失败 |
| ANALYTICS_REVIEW_INVALID_STATUS | 审核状态不合法 |

---

> 本文档基于当前仓库实际代码编写，覆盖了经营分析 Agent 从用户输入到结果返回的 11 个核心场景。
> 所有英文状态值均配有中文解释，所有示例均基于新疆能源集团经营分析业务语境。
