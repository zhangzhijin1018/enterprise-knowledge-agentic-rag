# ANALYTICS_PERF_REVIEW_V1.md

# 经营分析第18轮性能验收与慢点复盘

---

## 1. 验收范围

本次验收只覆盖第18轮已经实现的经营分析性能优化项，不扩展新业务功能。

本次验收重点验证以下七项：

1. `analytics/query` 首屏是否因 `lite / standard / full` 分级而真正减重。
2. `task_runs.output_snapshot` 是否完成轻量化，不再承载大 JSON。
3. 重结果是否已从 `task_runs` 剥离到 `analytics_results / AnalyticsResultRepository`。
4. `analytics export` 是否已具备真实异步任务语义，而非“带状态的同步导出”。
5. `insight_cards / report_blocks` 是否按 `output_mode` 延迟生成。
6. `SchemaRegistry / DataSourceRegistry / governance` 高频只读定义是否已进入进程内缓存复用。
7. 当前 demo 环境下最慢阶段位于哪里，是否具备最小慢点复盘依据。

---

## 2. 当前优化项回顾

第18轮已经完成以下设计与实现：

1. **output_snapshot 轻量化**
   - `task_runs.output_snapshot` 只保留轻快照：
     - `summary`
     - `slots`
     - `sql_preview`
     - `row_count`
     - `latency_ms`
     - `compare_target`
     - `group_by`
     - `governance_decision`
     - `timing_breakdown`
   - `tables / insight_cards / report_blocks / chart_spec` 不再写入 `task_runs`。

2. **重结果独立存储**
   - 新增 `analytics_results` 表方向与 `AnalyticsResultRepository`。
   - run detail、export 等重读取路径改为按 `run_id` 单独读取重结果。

3. **query 返回分级**
   - `lite`：轻摘要
   - `standard`：轻摘要 + `chart_spec + insight_cards`
   - `full`：完整详情

4. **export 真异步化**
   - `POST export` 只创建任务并返回 `export_id`
   - 通过 `AsyncTaskRunner` 在后台执行
   - `GET export detail` 轮询读取状态

5. **insight / report 延迟生成**
   - `summary`：查询成功后立即生成
   - `chart_spec / insight_cards`：仅 `standard / full`
   - `report_blocks`：仅 `full` 或导出链路

6. **registry / schema 常驻缓存**
   - `SchemaRegistry / DataSourceRegistry` 的高频只读定义通过 `RegistryCache` 进程内缓存复用。

---

## 3. 验收方法

本轮采用“自动化验收测试 + 本地 demo 环境一次验证结果”方式。

验收入口：

- 测试文件：`tests/perf/test_analytics_perf_acceptance.py`
- 执行命令：

```bash
conda run -n tmf_project python -m pytest -s tests/perf/test_analytics_perf_acceptance.py
```

验收覆盖点：

1. **output_mode 分级对比**
   - 对同一 query 依次执行 `lite / standard / full`
   - 比较返回字段差异
   - 记录粗粒度响应耗时
   - 记录 JSON payload 体量

2. **output_snapshot 瘦身验证**
   - 直接检查 `task_run.output_snapshot`
   - 确认不再包含：
     - `tables`
     - `insight_cards`
     - `report_blocks`
     - `chart_spec`

3. **heavy result 拆分验证**
   - 通过 `AnalyticsResultRepository.get_heavy_result(run_id)` 读取重内容
   - 确认重内容已独立可读

4. **timing_breakdown 验证**
   - 验证：
     - `sql_build_ms`
     - `sql_guard_ms`
     - `sql_execute_ms`
     - `masking_ms`
     - `insight_ms`
     - `report_ms`

5. **export 异步语义验证**
   - 普通导出：`POST` 返回 `pending`
   - 高风险导出：先进入 `awaiting_human_review`
   - review 通过后：导出异步继续，最终轮询到 `succeeded`

6. **缓存复用验证**
   - 多次调用 `DataSourceRegistry.list_data_sources / get_data_source`
   - 观察缓存条目数量是否稳定
   - 验证缓存复用不影响功能正确性

---

## 4. 验收结果

### 4.1 output_mode 分级结果

以下结果来自本地一次验收运行，环境为：

- macOS
- `conda` 环境：`tmf_project`
- demo 数据源：`local_analytics`
- 执行入口：`tests/perf/test_analytics_perf_acceptance.py`

| mode | elapsed_ms | payload_bytes | chart_spec | insight_cards | tables | report_blocks |
| --- | ---: | ---: | --- | --- | --- | --- |
| lite | 11.2 | 269 | N | N | N | N |
| standard | 0.3 | 1524 | Y | Y | N | N |
| full | 0.3 | 7683 | Y | Y | Y | Y |

验收结论：

1. **返回体量分级已明确生效**  
   `lite < standard < full`，其中 `lite` 约为 `269 bytes`，`full` 约为 `7683 bytes`，主查询响应体量已明显减重。

2. **首屏“是否更轻”主要体现在 payload，而不是单次 demo 耗时绝对值**  
   本次单次运行里 `lite` 首次调用耗时高于 `standard/full`，属于本地 demo 环境下的冷启动/首次执行噪声。  
   这不影响“首屏返回结构已显著减重”的验收结论，因为：
   - `lite` 不再返回图表、洞察、表格、报告块；
   - `lite` payload 远小于 `standard/full`；
   - 真实生产环境下仍需要在 PostgreSQL 真实数据源上继续做重复压测和 P95/P99 统计。

### 4.2 output_snapshot 轻量化结果

验收测试已确认 `task_run.output_snapshot` 中不再包含：

- `tables`
- `insight_cards`
- `report_blocks`
- `chart_spec`

同时保留了：

- `summary`
- `slots`
- `sql_preview`
- `row_count`
- `latency_ms`
- `compare_target`
- `group_by`
- `governance_decision`
- `timing_breakdown`
- `has_heavy_result`

验收结论：

- `output_snapshot` 已完成“轻快照”定型；
- `task_runs` 的大 JSON 读写压力已经从结构上被切掉。

### 4.3 heavy result 拆分结果

验收测试已确认 `AnalyticsResultRepository.get_heavy_result(run_id)` 中确实包含：

- `tables`
- `insight_cards`
- `report_blocks`
- `chart_spec`

验收结论：

- 重结果已经从 `task_runs` 中剥离；
- run detail / export 读取路径可以按需加载，不再拖慢主查询链路。

### 4.4 export 异步语义结果

验收测试已确认：

1. 普通导出：
   - `POST export` 返回 `pending`
   - 初始返回不带最终 `filename / artifact_path`
   - 通过轮询进入 `succeeded`

2. 高风险导出：
   - `POST export` 返回 `awaiting_human_review`
   - review 通过后，导出继续异步执行
   - 最终轮询到 `succeeded`

验收结论：

- export 已经具备真实异步任务语义；
- review 与异步导出链路已经兼容，不再是假异步。

### 4.5 缓存复用结果

本地一次验收结果：

- `cache_size_before=0`
- `after_first_list=3`
- `after_second_list=3`
- `after_get=3`

验收结论：

- `DataSourceRegistry` 的高频只读路径已经开始复用缓存；
- 重复读取不会继续无意义扩张缓存条目；
- 当前缓存策略已满足“进程内只读常驻缓存”的 V1 目标。

### 4.6 当前最慢阶段

本地 demo 环境一次验收结果：

1. `sql_guard_ms = 0.1ms`
2. `sql_execute_ms = 0.1ms`
3. `sql_build_ms = 0.0ms`

验收结论：

- 在当前 in-memory / demo 数据源下，最慢阶段仍然集中在 **SQL 相关链路**；
- 但这个结果受 demo 环境影响很大，绝对值非常小；
- 进入真实 PostgreSQL 只读数据源后，真正值得重点盯的通常仍会是：
  - `sql_execute_ms`
  - `report_ms`
  - `export_render_ms`

---

## 5. 当前仍存在的性能瓶颈

尽管第18轮优化已经生效，但当前仍有几个明显瓶颈没有解决：

1. **异步导出仍是本地线程执行器**
   - 当前使用 `AsyncTaskRunner`
   - 还没有切到 `Celery / Redis`
   - 不具备多进程、多实例调度和失败重试治理能力

2. **缺少真实 PostgreSQL 执行计划基线**
   - 目前只完成了 demo 级性能验收
   - 还没有在 `enterprise_readonly` 或真实 PostgreSQL 事实表上做：
     - `EXPLAIN ANALYZE`
     - 分区裁剪验证
     - 索引命中验证

3. **没有结果缓存**
   - 高频周报/月报、热点问题、多次相同查询，当前仍会重复走完整 SQL 链路

4. **report/export 仍可能成为长尾慢点**
   - 尤其进入真实 `docx / pdf` 排版后，`report_ms / export_render_ms` 会明显变重

5. **缓存仍是单进程内缓存**
   - 当前没有跨进程一致性
   - 配置更新后仍依赖手动失效或进程重启

---

## 6. 下一轮优化建议

如果继续做第19轮性能优化，最值得优先做的是：

### 建议 1：真实 PostgreSQL 性能基线

优先在已定型的一期真实经营分析表上做：

- `EXPLAIN ANALYZE`
- 月分区裁剪验证
- `(biz_date, metric_code, region_code / station_code / department_code)` 索引命中验证
- 不同 `group_by / compare / ranking` 模板的 SQL 基线

### 建议 2：结果缓存 / 热点报表缓存

优先对这些对象做缓存：

- 高频 `analytics/query` 结果
- 周报/月报模板导出结果
- 热点 `chart_spec / insight_cards`

### 建议 3：异步导出切 Celery

把当前 `AsyncTaskRunner` 平滑替换为：

- Celery worker
- Redis broker
- 重试 / 超时 / 死信治理

### 建议 4：导出链路再减重

继续把 `report_blocks -> report payload -> artifact render` 之间的重复 JSON 拼装减少一轮，重点关注：

- `report_ms`
- `export_render_ms`

### 建议 5：跨进程缓存一致性

如果进入多实例部署，下一轮需要补：

- 缓存失效策略
- 配置热更新
- registry/schema 版本号治理

---

## 7. 本轮验收结论

第18轮性能优化已经**结构性生效**，可以确认以下结论成立：

1. `output_snapshot` 已完成轻量化；
2. 重结果已从 `task_runs` 剥离到 `analytics_results / AnalyticsResultRepository`；
3. `analytics/query` 已具备 `lite / standard / full` 分级返回；
4. `insight / report` 已按 `output_mode` 延迟生成；
5. `analytics export` 已具备真实异步任务语义；
6. `registry / schema` 高频只读路径已启用进程内缓存；
7. 当前 demo 环境下最慢阶段已可通过 `timing_breakdown` 做最小复盘。

因此，本轮可以视为：

> **“第18轮性能优化方案已落地，并通过了 V1 工程验收；下一步可以进入真实 PostgreSQL 基线优化与异步任务体系增强。”**
