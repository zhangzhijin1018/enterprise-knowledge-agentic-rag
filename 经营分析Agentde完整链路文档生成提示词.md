请基于当前仓库，新增并完善经营分析 Agent 的完整链路文档。

本轮只做文档和验收清单更新，不要改核心业务代码，不要扩展新功能，不要新增新的子 Agent。

请先阅读以下文档：

- AGENTS.md
- docs/ARCHITECTURE.md
- docs/AGENT_WORKFLOW.md
- docs/API_DESIGN.md
- docs/DB_DESIGN.md
- docs/TECH_SELECTION.md
- docs/PROMPT_ENGINEERING.md
- 如存在：
  - docs/SUPERVISOR_ANALYTICS_STATE_MACHINE.md
  - docs/SUPERVISOR_ANALYTICS_PERSISTENCE_BOUNDARY.md

需要新增或重点完善：

- docs/ANALYTICS_AGENT_E2E_WORKFLOW.md
- docs/ANALYTICS_AGENT_ACCEPTANCE_CHECKLIST.md

------

# 一、文档总体目标

`docs/ANALYTICS_AGENT_E2E_WORKFLOW.md` 不能写成纯架构说明。

它必须写成一份“真实用户问句驱动的经营分析链路教程”。

目标是让读者可以通过几个实际问句，跟着系统一步步理解：

- 用户问了什么；
- 系统识别出了什么；
- 是否需要澄清；
- 是否触发 LLM；
- 是否触发 ReAct Planning；
- SQL 怎么生成；
- SQL Guard 怎么检查；
- SQL Gateway 怎么执行；
- 摘要、图表、洞察、报告块怎么返回；
- 状态表怎么变化；
- 导出和人工审核怎么走。

文档必须使用中文。

每个英文状态值、字段名、技术名第一次出现时，都要给中文解释。

------

# 二、文档写作硬性要求

请严格遵守：

1. 通过真实用户问句讲链路，不要只写抽象流程。
2. 每个关键 JSON 字段都要有中文注释或中文字段说明表。
3. 所有中间生成内容都要给实际示例，包括：
   - 澄清问题；
   - LLM Slot Fallback 输出；
   - ReAct Planning 的 thought/action/observation；
   - Summary 摘要；
   - Chart Spec 图表描述；
   - Insight Cards 洞察卡片；
   - Report Blocks 报告块；
   - Export Task 导出任务；
   - Review Task 审核任务。
4. 不要写“略”“待补充”“省略字段”。
5. 示例可以使用 mock/sample 经营数据，但必须业务合理。
6. 不要暴露真实密钥、真实连接串、真实敏感数据。
7. 不要要求真实 LLM API Key。
8. 所有示例要围绕能源集团经营分析语境，例如：
   - 发电量；
   - 收入；
   - 成本；
   - 利润；
   - 新疆区域；
   - 北疆区域；
   - 哈密电站；
   - 吐鲁番电站。

------

# 三、文档必须覆盖的 11 个场景

请在 `docs/ANALYTICS_AGENT_E2E_WORKFLOW.md` 中至少覆盖下面 11 个场景。

每个场景都按下面结构写：

- 用户问句；
- 这个场景要解决什么问题；
- 系统执行步骤；
- 关键输入输出示例；
- 状态变化；
- 最终返回给用户的内容；
- 字段中文说明。

------

## 场景 1：简单明确查询

用户问句：

“查询新疆区域 2024 年 3 月的发电量”

必须展示：

- 用户输入；
- Planner 识别结果；
- SlotValidator 判断结果；
- SQL Builder 输入输出；
- SQL Guard 输入输出；
- SQL Gateway 请求和返回；
- Summary 摘要示例；
- Chart Spec 图表示例；
- Insight Cards 洞察卡片示例；
- task_run 状态变化；
- analytics_result_repository 保存重结果的说明。

请使用如下业务数据示例：

- 新疆区域 2024 年 3 月总发电量：12800 MWh；
- 哈密电站：4200 MWh；
- 吐鲁番电站：3100 MWh；
- 北疆风电场：2900 MWh；
- 南疆光伏站：2600 MWh。

必须给出类似下面的槽位示例，并给每个字段中文说明：

字段说明表形式即可：

| 字段       | 示例值                   | 中文含义             |
| ---------- | ------------------------ | -------------------- |
| metric     | 发电量                   | 用户要查询的经营指标 |
| time_range | 2024-03-01 到 2024-03-31 | 查询时间范围         |
| org_scope  | 新疆区域                 | 查询组织范围         |
| group_by   | station                  | 按电站分组           |

------

## 场景 2：缺少指标，需要澄清

用户问句：

“帮我看一下新疆区域上个月的情况”

必须展示：

- 规则识别出了 `time_range` 和 `org_scope`；
- 但缺少 `metric`；
- SlotValidator 判断不可执行；
- 创建 clarification_event；
- 创建 slot_snapshot；
- task_run.status 变成 awaiting_user_clarification；
- 返回给用户的澄清问题。

澄清问题示例：

“你想查看哪个经营指标？例如：发电量、收入、成本、利润。”

必须解释这些字段：

| 字段               | 示例值                   | 中文含义                      |
| ------------------ | ------------------------ | ----------------------------- |
| need_clarification | true                     | 是否需要用户补充信息          |
| clarification_id   | clar_001                 | 澄清事件 ID，后续恢复执行要用 |
| question           | 你想查看哪个经营指标？   | 返回给用户的追问问题          |
| target_slots       | metric                   | 本次希望用户补充的槽位        |
| suggested_options  | 发电量、收入、成本、利润 | 给用户的候选选项              |

------

## 场景 3：缺少时间，需要澄清

用户问句：

“查询新疆区域发电量”

必须展示：

- 已识别 `metric=发电量`；
- 已识别 `org_scope=新疆区域`；
- 缺少 `time_range`；
- 返回澄清问题。

澄清问题示例：

“你想查询哪个时间范围？例如：上个月、本月、2024 年 3 月、近 30 天。”

------

## 场景 4：澄清后恢复执行

接场景 2。

用户补充：

“看发电量”

必须展示：

- 用户通过 `clarification_id` 回复；
- 系统读取 clarification_event；
- 系统读取 slot_snapshot；
- 合并补充槽位；
- 更新 clarification_event.status 为 resolved；
- 更新 slot_snapshot；
- 复用原 run_id；
- task_run.status 从 awaiting_user_clarification 变成 executing；
- 重新进入 StateGraph；
- 成功执行 SQL；
- task_run.status 最终变成 succeeded。

必须明确说明：

“恢复 workflow 不是恢复原来的 Python 线程，而是根据 run_id、clarification_id、slot_snapshot 重新构造状态，并重新进入 StateGraph 执行。”

请给出状态变化表：

| 阶段       | task_run.status             | 中文含义         |
| ---------- | --------------------------- | ---------------- |
| 初次缺槽位 | awaiting_user_clarification | 等待用户补充信息 |
| 用户补充后 | executing                   | 重新进入执行中   |
| 查询完成   | succeeded                   | 执行成功         |

------

## 场景 5：复杂问题触发 ReAct Planning

用户问句：

“分析新疆区域近三个月发电量下降的原因，并和去年同期对比，看哪些电站拖累最大”

必须展示：

- 为什么这是复杂问题；
- AnalyticsReactPlanningPolicy 为什么判断需要 ReAct；
- ReAct 只在 analytics_plan 节点内部运行；
- ReAct 不生成 SQL；
- ReAct 不执行 SQL；
- ReAct 不绕过 SQL Guard；
- ReAct 输出必须经过 ReactPlanValidator；
- 后续仍然走 SQL Builder、SQL Guard、SQL Gateway。

必须展示 ReAct 子循环示例：

Step 1：

字段说明：

| 字段         | 示例值                                               | 中文含义                       |
| ------------ | ---------------------------------------------------- | ------------------------------ |
| thought      | 用户问题包含趋势、同比和电站排名，需要确认指标和维度 | 模型的简短规划思考摘要         |
| action       | metric_catalog_lookup                                | 只读工具调用，用来查询指标目录 |
| action_input | query=发电量                                         | 工具输入参数                   |

Observation 示例：

| 字段              | 示例值           | 中文含义         |
| ----------------- | ---------------- | ---------------- |
| matched           | true             | 是否匹配到指标   |
| metric            | 发电量           | 匹配到的指标名称 |
| metric_code       | power_generation | 指标编码         |
| sensitivity_level | medium           | 指标敏感级别     |

Step 2：

展示 `schema_registry_lookup` 的 action 和 observation。

Final plan candidate 示例字段说明：

| 字段           | 示例值   | 中文含义                   |
| -------------- | -------- | -------------------------- |
| metric         | 发电量   | 主指标                     |
| time_range     | 近三个月 | 时间范围                   |
| org_scope      | 新疆区域 | 组织范围                   |
| group_by       | station  | 按电站分组                 |
| compare_target | yoy      | 同比                       |
| sort_direction | asc      | 升序，用于找拖累最大的电站 |
| top_n          | 5        | 返回前 5 个结果            |
| confidence     | 0.86     | ReAct 对规划结果的置信度   |

------

## 场景 6：规则低置信触发 LLM Slot Fallback

用户问句：

“新疆那边最近电量咋样”

必须展示：

- 规则可能识别出 `org_scope=新疆区域`；
- 规则可能识别出 `time_range=近一个月`；
- 但 `电量` 到底是不是 `发电量` 可能低置信；
- LLM Slot Fallback 只做槽位补强；
- 它不是 ReAct；
- 它不生成 SQL；
- 它的输出必须经过 AnalyticsSlotFallbackValidator。

必须给出 LLM Slot Fallback 输出示例，并用字段说明表解释：

| 字段       | 示例值                                           | 中文含义                   |
| ---------- | ------------------------------------------------ | -------------------------- |
| metric     | 发电量                                           | LLM 补强出的指标           |
| time_range | 近一个月                                         | LLM 或规则识别出的时间范围 |
| org_scope  | 新疆区域                                         | 组织范围                   |
| confidence | 0.78                                             | 置信度                     |
| should_use | true                                             | 是否建议使用这次补强结果   |
| reason     | 用户口语中的“电量”在经营分析语境中通常对应发电量 | LLM 给出的简短原因         |

------

## 场景 7：SQL Guard 阻断

用户问句：

“查询所有区域所有用户明细”

必须展示：

- 为什么这个请求可能有风险；
- SQL Builder 可能产生不符合治理要求的查询；
- SQL Guard 检查失败；
- SQL Guard blocked 不能重试；
- 不能通过 ReAct 或 LLM 绕过；
- task_run.status 变成 failed；
- 返回错误。

错误字段说明：

| 字段           | 示例值                             | 中文含义                   |
| -------------- | ---------------------------------- | -------------------------- |
| success        | false                              | 请求是否成功               |
| error_code     | SQL_GUARD_BLOCKED                  | SQL 安全检查失败错误码     |
| message        | SQL 安全检查未通过                 | 给用户或前端展示的错误信息 |
| blocked_reason | 缺少部门过滤条件或访问了非白名单表 | 被阻断的原因               |

------

## 场景 8：SQL Gateway 临时失败重试

用户问句：

“查询新疆区域 2024 年 3 月发电量”

必须模拟：

- 第一次 SQL Gateway Timeout；
- 系统判断这是临时错误，可以重试；
- 第二次执行成功；
- retry_history 有记录；
- 最终 task_run.status=succeeded。

必须解释：

- SQL Gateway 超时可以重试；
- SQL Guard blocked 不可重试；
- 权限失败不可重试。

retry_history 字段说明：

| 字段          | 示例值                | 中文含义       |
| ------------- | --------------------- | -------------- |
| node_name     | analytics_execute_sql | 发生重试的节点 |
| attempt       | 1                     | 第几次尝试     |
| error_type    | TimeoutError          | 错误类型       |
| error_message | SQL Gateway 请求超时  | 错误信息       |

------

## 场景 9：图表、洞察、报告块降级

用户问句：

“生成新疆区域 2024 年 3 月发电量的完整分析”

必须模拟：

- SQL 执行成功；
- Summary 成功；
- Chart Spec 失败；
- Insight Cards 成功；
- Report Blocks 失败；
- 最终主查询成功；
- degraded=true；
- degraded_features 记录降级功能。

必须明确说明：

- 图表、洞察、报告块可以降级；
- SQL 执行失败不能降级成成功；
- 系统不能编造查询结果。

必须给出最终返回示例：

| 字段              | 示例值                                 | 中文含义       |
| ----------------- | -------------------------------------- | -------------- |
| summary           | 2024 年 3 月新疆区域发电量为 12800 MWh | 摘要           |
| degraded          | true                                   | 是否发生降级   |
| degraded_features | chart_spec, report_blocks              | 发生降级的功能 |
| row_count         | 4                                      | 查询结果行数   |

------

## 场景 10：导出报告

用户操作：

“把这次分析导出成 PDF”

必须展示：

- 用户基于 run_id 发起导出；
- 系统读取 task_run 的轻量 output_snapshot；
- 系统从 analytics_result_repository 读取重结果；
- Report MCP 生成文件；
- 返回 export_task。

必须说明：

- task_run.output_snapshot 不保存完整 rows；
- 完整表格、图表、洞察、报告块从 analytics_result_repository 读取；
- 导出不是重新查询数据库，而是基于已保存结果生成报告。

export_task 字段说明：

| 字段            | 示例值     | 中文含义              |
| --------------- | ---------- | --------------------- |
| export_id       | export_001 | 导出任务 ID           |
| run_id          | run_001    | 对应的经营分析任务 ID |
| format          | pdf        | 导出格式              |
| status          | running    | 导出任务状态          |
| review_required | false      | 是否需要人工审核      |

------

## 场景 11：高风险导出进入人工审核

用户操作：

“导出包含敏感经营指标的完整报告”

必须展示：

- Review Policy 判断需要审核；
- 创建 review_task；
- export_task.status=awaiting_human_review；
- 审核通过后恢复导出；
- 审核拒绝后终止导出。

review_task 字段说明：

| 字段          | 示例值                                 | 中文含义                   |
| ------------- | -------------------------------------- | -------------------------- |
| review_id     | review_001                             | 审核任务 ID                |
| subject_type  | analytics_export                       | 审核对象类型：经营分析导出 |
| subject_id    | export_001                             | 被审核的导出任务 ID        |
| review_status | pending                                | 审核状态：等待审核         |
| review_reason | 导出内容包含敏感经营指标，需要人工复核 | 审核原因                   |

审核通过示例：

| 字段           | 示例值                 | 中文含义 |
| -------------- | ---------------------- | -------- |
| review_status  | approved               | 审核通过 |
| reviewer_name  | 经营管理部审核员       | 审核人   |
| review_comment | 允许导出，仅限内部使用 | 审核意见 |

审核拒绝示例：

| 字段           | 示例值                             | 中文含义 |
| -------------- | ---------------------------------- | -------- |
| review_status  | rejected                           | 审核拒绝 |
| reviewer_name  | 经营管理部审核员                   | 审核人   |
| review_comment | 导出范围过大，请缩小区域或时间范围 | 审核意见 |

------

# 四、必须展示的系统生成内容

文档中必须明确展示下面这些内容的实际示例：

1. 澄清问题；
2. LLM Slot Fallback 输出；
3. ReAct Planning 的 thought/action/observation；
4. Summary 摘要；
5. Chart Spec 图表描述；
6. Insight Cards 洞察卡片；
7. Report Blocks 报告块；
8. Export Task；
9. Review Task；
10. SQL Guard 阻断错误；
11. Retry History；
12. Degraded Features。

Chart Spec 示例内容可以使用：

| 字段       | 示例值                          | 中文含义         |
| ---------- | ------------------------------- | ---------------- |
| chart_type | bar                             | 图表类型：柱状图 |
| title      | 新疆区域 2024 年 3 月发电量对比 | 图表标题         |
| x_axis     | station                         | X 轴字段：电站   |
| y_axis     | power_generation                | Y 轴字段：发电量 |
| unit       | MWh                             | 指标单位         |

Insight Cards 示例内容可以使用：

| 字段        | 示例值                                                 | 中文含义           |
| ----------- | ------------------------------------------------------ | ------------------ |
| title       | 哈密电站发电量最高                                     | 洞察标题           |
| description | 哈密电站 3 月发电量为 4200 MWh，占新疆区域总量的 32.8% | 洞察描述           |
| severity    | info                                                   | 洞察级别：普通信息 |

Report Blocks 示例内容可以使用：

| 字段    | 示例值                          | 中文含义         |
| ------- | ------------------------------- | ---------------- |
| type    | heading                         | 报告块类型：标题 |
| content | 新疆区域 2024 年 3 月发电量分析 | 报告块内容       |

也可以额外给出 paragraph、table 类型的报告块示例。

------

# 五、文档风格要求

文档要像教程，不要像代码注释合集。

每个场景按这个模板写：

1. 用户问句；
2. 这个场景为什么重要；
3. 系统执行步骤；
4. 中间输入输出示例；
5. 字段中文说明；
6. 状态变化；
7. 最终用户看到的结果；
8. 本场景的关键结论。

所有英文状态值都要有中文解释，例如：

| 状态值                      | 中文含义         |
| --------------------------- | ---------------- |
| executing                   | 执行中           |
| awaiting_user_clarification | 等待用户补充信息 |
| succeeded                   | 执行成功         |
| failed                      | 执行失败         |
| awaiting_human_review       | 等待人工审核     |

------

# 六、同步更新验收清单

请同步更新：

- docs/ANALYTICS_AGENT_ACCEPTANCE_CHECKLIST.md

增加一节：

## 链路文档验收

至少包含以下检查项：

| 检查项                 | 是否必须 | 说明                                                         |
| ---------------------- | -------- | ------------------------------------------------------------ |
| 覆盖 11 类用户场景     | 必须     | 简单查询、澄清、恢复、ReAct、Slot Fallback、SQL Guard、重试、降级、导出、审核等 |
| 有实际用户问句         | 必须     | 每个场景必须以真实问句开头                                   |
| 有实际输入输出         | 必须     | 不能只写抽象说明                                             |
| 字段有中文解释         | 必须     | 所有关键字段都要中文说明                                     |
| 展示 LLM 生成内容      | 必须     | 包括 fallback、ReAct、摘要、图表、洞察、报告                 |
| 展示状态变化           | 必须     | task_run、clarification_event、slot_snapshot、export_task、review_task |
| 适合非英语熟练读者阅读 | 必须     | 英文状态值必须配中文解释                                     |

------

# 七、实现约束

本轮只允许修改文档和必要的 README/Makefile 说明。

不要改核心业务代码。

不要新增新的业务能力。

不要扩其他子 Agent。

不要接 LangGraph checkpoint。

不要引入新的依赖。

不要要求真实 LLM API Key。

不要写真实密钥、真实连接串或敏感数据。

------

# 八、输出要求

完成后请输出：

1. 新增和修改了哪些文件；
2. `docs/ANALYTICS_AGENT_E2E_WORKFLOW.md` 覆盖了哪些场景；
3. 每个场景是否都有实际问句；
4. 是否展示了 LLM 生成内容；
5. 是否给关键字段加了中文解释；
6. 是否更新了 `docs/ANALYTICS_AGENT_ACCEPTANCE_CHECKLIST.md`；
7. 后续如何阅读这份文档来理解经营分析完整链路。