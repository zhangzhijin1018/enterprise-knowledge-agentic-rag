# Prompt 工程治理规范（一期）

本文档用于约束项目内所有 LLM 调用、Prompt 模板、结构化输出和安全校验。  
核心结论：**业务代码不能直接写大段 Prompt，也不能直接调用具体模型 SDK；所有 LLM 能力必须经过统一 Gateway、Prompt Registry、Pydantic Schema 和 Validator。**

---

## 1. 总体原则

本项目的 LLM 能力定位是“受控增强”，不是让模型直接接管业务执行。

统一链路如下：

```text
业务 Service / Workflow Node
  -> PromptRegistry 加载模板
  -> PromptRenderer 渲染变量
  -> LLMGateway 调用模型
  -> Pydantic Structured Output 解析
  -> Validator 二次校验
  -> 返回安全业务对象
```

这样设计的原因：

- 模型供应商会变，业务代码不应该绑定具体 SDK；
- Prompt 是可迭代资产，需要文件化、版本化、可审查；
- LLM 输出天然不可信，影响业务决策前必须结构化并二次校验；
- 经营分析会访问真实经营数据，LLM 不能绕过 SQL Builder / SQL Guard / SQL Gateway。

---

## 2. Prompt 目录与命名

Prompt 模板统一放在：

```text
core/prompts/templates/{domain}/{prompt_name}.j2
```

当前已登记的 Prompt：

| Prompt 名称 | 业务域 | 用途 | 输出 Schema |
|---|---|---|---|
| `analytics/react_planner_system` | analytics | 复杂经营分析局部 ReAct planning 系统边界 | `ReactStepOutput` |
| `analytics/react_planner_user` | analytics | 复杂经营分析局部 ReAct planning 用户上下文 | `ReactStepOutput` |
| `analytics/slot_fallback_system` | analytics | 规则低置信时的槽位补强系统边界 | `AnalyticsSlotFallbackOutput` |
| `analytics/slot_fallback_user` | analytics | 规则低置信时的槽位补强用户上下文 | `AnalyticsSlotFallbackOutput` |

后续命名建议：

- `analytics/clarification_system`
- `analytics/summary_system`
- `contract/risk_review_system`
- `report/outline_system`

Prompt Catalog 位置：

```text
core/prompts/catalog.py
```

Catalog 用于记录 Prompt 的用途、输入变量、输出 Schema、风险等级、owner 和版本，便于生产审查和后续版本管理。

---

## 3. 禁止事项

以下做法禁止进入业务代码：

- 禁止在 service、node、repository 中散落大段 Prompt 字符串；
- 禁止业务代码直接调用 OpenAI、DashScope、DeepSeek、vLLM 等具体 SDK；
- 禁止 LLM 输出直接驱动 SQL 执行；
- 禁止 LLM 直接更新 `task_run`、`review`、`export` 等权威状态；
- 禁止 LLM 绕过权限、SQL Guard、数据范围治理和 Human Review；
- 禁止把完整 Prompt、完整模型输出、完整推理链写入 `task_run.output_snapshot`。

如果需要调试，只能保存轻量摘要，例如：

```text
prompt_name
model
trace_id
structured_output_schema
validator_result
fallback_used
```

---

## 4. 输出 Schema 与 Validator

所有会影响业务决策的 LLM 输出必须 Pydantic 化。

当前经营分析有两类 LLM 输出：

1. `AnalyticsSlotFallbackOutput`
   - 用于规则 Planner 低置信时补槽；
   - 只能输出 slots、clarification 建议、confidence；
   - 必须经过 `AnalyticsSlotFallbackValidator`。

2. `ReactStepOutput`
   - 用于复杂经营分析的局部 ReAct planning；
   - 最终只能产出 plan candidate；
   - 必须经过 `ReactPlanValidator`。

Validator 是硬边界。Prompt 只能告诉模型“应该怎么做”，Validator 才决定“哪些字段真的能进入业务主链”。

---

## 5. 经营分析 LLM 能力边界

经营分析目前只有两类 LLM 能力：

- `slot fallback`：规则不足时补强 `metric / time_range / org_scope / group_by / compare_target` 等槽位；
- `react planning`：复杂问题在 `analytics_plan` 节点内部做局部规划。

共同边界：

- 不能生成 SQL；
- 不能执行 SQL；
- 不能调用 SQL Gateway；
- 不能更新 task_run；
- 不能触发 export/review；
- 不能绕过 SQL Guard；
- 最小可执行条件仍由本地 `SlotValidator` 决定。

默认配置：

```text
ANALYTICS_PLANNER_ENABLE_LLM_FALLBACK=false
ANALYTICS_REACT_PLANNER_ENABLED=false
```

本地测试默认使用 `MockLLMGateway`，不依赖真实外部模型服务。

---

## 6. 开发检查清单

新增任何 LLM 调用前，必须确认：

- 是否新增了 Prompt 模板文件；
- 是否登记到 `core/prompts/catalog.py`；
- 是否通过 `PromptRegistry` 加载；
- 是否通过 `PromptRenderer` 渲染变量；
- 是否通过 `LLMGateway` 调用；
- 是否定义了 Pydantic 输出 Schema；
- 是否有 Validator 二次校验；
- 是否补充离线单元测试；
- 是否没有把完整 Prompt / 模型输出 / 推理链写入 task_run。

---

## 7. Prompt 工程验收清单

一期 Prompt 工程验收必须覆盖：

- `core/prompts/catalog.py` 中每个 Prompt 都有 `name / domain / purpose / input_variables / output_schema / risk_level / owner / version`；
- Catalog 中登记的模板文件真实存在；
- `PromptRegistry` 能加载所有 Catalog Prompt；
- 模板里出现的 `{{ variable }}` 必须在 Catalog 的 `input_variables` 中声明；
- `PromptRenderer` 能用测试变量离线渲染所有模板；
- `MockLLMGateway` 能返回 Pydantic 结构化对象；
- JSON 解析失败与 Schema 校验失败有明确错误码；
- `AnalyticsSlotFallbackValidator / ReactPlanValidator` 能拦截 SQL、权限绕过、状态写入、导出和审核字段；
- 没有真实 `LLM_API_KEY` 时，单元测试仍然可以离线运行。

Catalog 声明变量但模板暂未使用是允许的。原因是生产治理中可能先登记兼容变量，
再通过 Prompt 版本灰度逐步使用；但模板偷偷使用未登记变量是不允许的。

---

## 8. LLM 轻量 Trace 规范

LLM 调用只记录轻量元信息，结构参考 `LLMCallMetadata`：

```text
trace_id
run_id
component
prompt_name
prompt_version
model
provider
output_schema
latency_ms
success
error_code
validator_result
fallback_used
```

不记录：

- 完整 Prompt；
- 完整模型输出；
- 完整推理链；
- 业务数据库连接串；
- 明文 API Key。

这样做是为了兼顾可观测性与数据安全：我们能知道“哪个组件、哪个 Prompt、哪个模型、哪个 Schema 出了问题”，但不会把敏感上下文塞进 `task_run.output_snapshot`。

---

## 9. Prompt Evaluation 最小数据集

当前已新增最小离线评估数据集：

```text
evals/analytics_slot_fallback_cases.jsonl
evals/analytics_react_planning_cases.jsonl
scripts/eval_prompts.py
```

每条 case 至少包含：

- `case_id`
- `task_type`
- `query`
- `expected_slots` 或 `expected_behavior`
- `forbidden_behavior`

当前脚本默认使用确定性 fake runner / Validator，不调用真实模型。  
后续可以在同一入口里接入：

- `MockLLMGateway`；
- OpenAI-compatible 私有化模型；
- RAGAS；
- 自定义 Prompt Evaluation 指标。

新增 LLM 能力时，必须同步补：

- Prompt Catalog；
- Prompt 模板；
- Pydantic Schema；
- Validator；
- 离线测试；
- 必要的 eval case。
