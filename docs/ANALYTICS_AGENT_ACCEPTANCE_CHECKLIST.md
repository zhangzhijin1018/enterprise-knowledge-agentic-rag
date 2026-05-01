# 经营分析 Agent 验收清单

> 本文档是经营分析 Agent 的验收检查清单，用于确保链路文档、代码实现和业务需求的完整对齐。
>
> 更新时间：2026-04-29
>
> 与 `docs/ANALYTICS_AGENT_E2E_WORKFLOW.md` 配套使用。

---

## 一、链路文档验收

### 1.1 场景覆盖

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| 场景 1：简单明确查询 | 必须 | ✅ | "查询新疆区域 2024 年 3 月的发电量"，三要素齐全，一次性成功 |
| 场景 2：缺少指标，需要澄清 | 必须 | ✅ | "帮我看一下新疆区域上个月的情况"，返回 missing_required_slot |
| 场景 3：缺少时间，需要澄清 | 必须 | ✅ | "查询新疆区域发电量"，返回 time_range missing |
| 场景 4：澄清后恢复执行 | 必须 | ✅ | 用户回答"看发电量"，系统恢复 task_run 状态 |
| 场景 5：ReAct Planning 复杂问题 | 必须 | ✅ | "分析下降原因，和去年对比，看拖累最大的电站" |
| 场景 6：LLM Slot Fallback 低置信 | 必须 | ✅ | "新疆那边最近电量咋样"，LLM 补强槽位 |
| 场景 7：SQL Guard 阻断 | 必须 | ✅ | SQL 缺少部门过滤被阻断，不可重试 |
| 场景 8：SQL Gateway 临时失败重试 | 必须 | ✅ | timeout 可重试一次，与 Guard blocked 区分 |
| 场景 9：图表/洞察/报告块降级 | 必须 | ✅ | Chart Spec 失败不影响主查询，degraded=true |
| 场景 10：导出报告 | 必须 | ✅ | 基于已保存结果（非重新查库）生成导出文件 |
| 场景 11：高风险导出进入人工审核 | 必须 | ✅ | ReviewPolicy 评估+审批通过后恢复导出 |

### 1.2 文档质量要求

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| 每个场景有实际用户问句 | 必须 | ✅ | 每个场景以真实问句开头 |
| 每个场景有实际输入输出示例 | 必须 | ✅ | 包含完整 JSON 示例，不是只写抽象说明 |
| 所有关键字段有中文解释 | 必须 | ✅ | 使用字段说明表，英文值配中文含义 |
| 展示了 LLM 生成内容 | 必须 | ✅ | 包括 fallback 输出、ReAct thought/action/observation、summary、chart_spec、insight_cards |
| 展示了完整状态变化 | 必须 | ✅ | task_run、clarification_event、slot_snapshot、export_task、review_task 的状态变化 |
| 适合非英语熟练读者阅读 | 必须 | ✅ | 所有英文状态值配中文解释 |
| 文档像教程而非代码注释合集 | 必须 | ✅ | 每个场景遵循统一模板 |
| 每个场景有关键结论 | 必须 | ✅ | 每个场景末尾总结关键要点 |
| 示例使用能源集团经营分析语境 | 必须 | ✅ | 发电量、收入、成本、利润、新疆区域、哈密电站等 |

### 1.3 必须展示的系统生成内容

| 内容类型 | 是否覆盖 | 说明 |
|---|---|---|
| 澄清问题 | ✅ | 场景 2、3 展示了 clarification 完整示例 |
| LLM Slot Fallback 输出 | ✅ | 场景 6 展示了字段说明表 |
| ReAct Planning thought/action/observation | ✅ | 场景 5 展示了 2 步 ReAct 示例 |
| Summary 摘要 | ✅ | 场景 1 展示了多种摘要生成方式 |
| Chart Spec 图表描述 | ✅ | 场景 1 展示了 bar 类型、字段说明表 |
| Insight Cards 洞察卡片 | ✅ | 场景 1 展示了 ranking 类型 |
| Report Blocks 报告块 | ✅ | 场景 1 展示了 8 种 block_type |
| Export Task 导出任务 | ✅ | 场景 10 展示了字段说明表 |
| Review Task 审核任务 | ✅ | 场景 11 展示了完整审核流程 |
| SQL Guard 阻断错误 | ✅ | 场景 7 展示了阻断结果 |
| Retry History | ✅ | 场景 8 展示了 retry_history 字段 |
| Degraded Features | ✅ | 场景 9 展示了降级功能列表 |

---

## 二、功能实现验收

### 2.1 主链路

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| analytics/query 接口可正常调用 | 必须 | ✅ | `POST /api/v1/analytics/query` |
| analytics/runs/{run_id} 详情可读取 | 必须 | ✅ | `GET /api/v1/analytics/runs/{run_id}` |
| 多轮对话会话承接正确 | 必须 | ✅ | conversation_id 贯穿多轮 |
| 会话历史消息可查询 | 必须 | ✅ | 通过 clarifications 体系 |
| conversation_memory 记录上次分析上下文 | 必须 | ✅ | upsert_memory |

### 2.2 规划与语义

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| SemanticResolver 可以别口语化表达 | 必须 | ✅ | "上个月"、"近三个月"、"新疆那边" |
| SlotValidator 校验必填与冲突 | 必须 | ✅ | metric、time_range 缺一不可 |
| ClarificationGenerator 生成结构化澄清 | 必须 | ✅ | classification_type + target_slots + suggested_options |
| 多轮上下文可承接 | 必须 | ✅ | 继承上一轮 metric / time_range / org_scope |
| 增量槽位更新 | 必须 | ✅ | "换成收入"、"按月看"、"再看一下同比" |
| LLM Slot Fallback 有边界控制 | 必须 | ✅ | should_use + confidence + validator |
| ReAct Planning 有边界控制 | 必须 | ✅ | 不生成 SQL、不绕过 Guard、只输出规划 |

### 2.3 SQL 治理

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| SQLBuilder 生成 schema-aware SQL | 必须 | ✅ | 基于槽位和 schema 构造，非自由生成 |
| SQLGuard 做只读校验 | 必须 | ✅ | 必须以 SELECT 开头 |
| SQLGuard 做 DDL/DML 禁止 | 必须 | ✅ | INSERT/UPDATE/DELETE/DROP 等 |
| SQLGuard 做多语句禁止 | 必须 | ✅ | 禁止分号分隔多语句 |
| SQLGuard 做表白名单 | 必须 | ✅ | 只允许 analytics_metrics_daily |
| SQLGuard 做部门过滤 | 必须 | ✅ | department_code 必须存在 |
| SQLGuard 自动补 LIMIT | 必须 | ✅ | 默认 LIMIT 500 |
| SQLGuard blocked 不可重试 | 必须 | ✅ | 与 Gateway timeout 区分 |
| SQL 审计记录 | 必须 | ✅ | SQLAuditRepository 记录每次执行 |

### 2.4 执行与结果

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| SQL Gateway 走 MCP server | 必须 | ✅ | 进程内 SQL MCP Server |
| 执行超时可重试 | 必须 | ✅ | TimeoutError 可重试一次 |
| DataMaskingService 脱敏 | 必须 | ✅ | station 字段在缺权限时脱敏 |
| Summary 生成 | 必须 | ✅ | 根据 group_by/compare_target 生成不同摘要 |
| Insight Cards 生成 | 必须 | ✅ | 按规则生成 ranking/trend/comparison/anomaly |
| Report Blocks 生成 | 必须 | ✅ | 8 种 block_type |
| Chart Spec 生成 | 必须 | ✅ | 按 group_by 决定 chart_type |

### 2.5 存储与性能

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| output_snapshot 轻量化 | 必须 | ✅ | 不含 tables/insight_cards/report_blocks/chart_spec |
| 重结果写入 analytics_result_repository | 必须 | ✅ | tables/insight_cards/report_blocks/chart_spec 单独存储 |
| output_mode 分级返回 | 必须 | ✅ | lite/standard/full |
| slot_snapshot 保存中间态 | 必须 | ✅ | 供恢复执行使用 |
| clarification_event 独立存储 | 必须 | ✅ | 可审计的交互事件 |

### 2.6 权限与安全

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| 指标级权限控制 | 必须 | ✅ | analytics:metric:{name} |
| 数据源级权限控制 | 必须 | ✅ | required_permissions / allowed_roles |
| 部门范围过滤 | 必须 | ✅ | department_filter_column |
| 会话归属验证 | 必须 | ✅ | conversation.user_id == current_user_id |
| 运行详情隔离 | 必须 | ✅ | 不同用户不可查看他人 run |

### 2.7 多点分析

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| 分组查询支持（group_by） | 必须 | ✅ | station / region / month |
| 对比查询支持（compare_target） | 必须 | ✅ | mom（环比）/ yoy（同比） |
| TopN 查询支持 | 必须 | ✅ | top_n + sort_direction |
| 组织范围切换 | 必须 | ✅ | "新疆换成北疆"、"只看哈密电站" |
| 指标切换 | 必须 | ✅ | "换成收入" |
| 多指标冲突澄清 | 必须 | ✅ | "再把成本也加进来" → slot_conflict |

### 2.8 导出与审核

| 检查项 | 是否必须 | 状态 | 说明 |
|---|---|---|---|
| 多格式导出 | 必须 | ✅ | json/markdown/docx/pdf |
| 导出模板支持 | 必须 | ✅ | weekly_report/monthly_report |
| Review Policy 确定性评估 | 必须 | ✅ | 本地规则，非 LLM |
| 审核状态流转 | 必须 | ✅ | pending → approved/rejected |
| 审核通过后恢复导出 | 必须 | ✅ | resume_export_after_review |

---

## 三、前后端联调验收

| 检查项 | 说明 |
|---|---|
| conversation_id 正确承接多轮 | 多轮对话使用同一 conversation_id |
| clarification_id 正确传递 | 澄清返回 clarification_id，回复时带上 |
| run_id / trace_id 贯穿所有链路 | 所有业务链路可追踪 |
| awaiting_user_clarification / waiting_review / awaiting_human_review 状态前端可展示 | 不同状态不同 UI |
| output_mode 正确控制返回粒度 | lite 用于列表页，standard 用于详情页，full 用于导出 |
| 错误码统一 | 所有错误返回包含 error_code 和 message |

---

## 四、回归检查项

| 检查项 | 说明 |
|---|---|
| 简单三要素查询一次成功 | metric + time_range + org_scope 齐全 |
| 缺指标返回澄清，回复后继续执行 | 完整澄清闭环 |
| 缺时间返回澄清 | 不同于缺指标的澄清文案 |
| 多轮继承上下文 | "再按月看"、"换成收入" |
| SQL 审计有记录 | 每次执行都有 audit 可查询 |
| 脱敏生效 | 敏感字段缺少权限时脱敏 |
| 导出产物可访问 | 生成文件路径可访问 |
| 审核拒绝不生成文件 | rejected 后不执行导出 |

---

> 本清单与 `docs/ANALYTICS_AGENT_E2E_WORKFLOW.md` 配套使用。链路文档中的 11 个场景均需通过本清单的对应检查项。
