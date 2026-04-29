# ANALYTICS_DATA_SOURCE.md

# 经营分析真实数据源设计说明

## 1. 文档定位

本文档专门解释经营分析真实数据源的一期设计结论，重点说明：

- 为什么一期默认优先 PostgreSQL；
- 为什么保留 `local_analytics` 作为 demo / fallback；
- `analytics_metrics_daily / analytics_metric_definitions / analytics_org_dimensions` 三张核心表如何协同；
- 分区、索引、治理字段与代码定义之间的映射关系。

这份文档的目标不是替代 `DB_DESIGN.md`，而是给经营分析模块单独提供一份更聚焦的设计说明，便于团队评审、DBA 落地和后续面试讲解。

---

## 2. 一期数据源选型结论

### 2.1 平台元数据库

平台元数据库继续统一使用 PostgreSQL，主要承载：

- 会话
- 多轮澄清
- task_run
- SQL 审计
- export task
- analytics review
- 数据源注册配置

### 2.2 真实经营分析数据源

一期默认优先以 PostgreSQL 作为真实经营分析数据源参考实现。

同时系统也支持未来接入：

- 企业已有只读 PostgreSQL
- 企业已有只读 MySQL
- 企业已有数仓视图

但当前代码、SQL 脚本和文档以 PostgreSQL 为第一参考实现统一定型。

### 2.3 为什么仍保留 local_analytics

`local_analytics` 保留的原因：

- 本地研发与测试不应被真实企业库阻塞；
- analytics 主链路、export、review、report 模板都需要稳定 demo 源；
- 可以作为真实企业库不可用时的 fallback。

### 2.4 enterprise_readonly 的定位

`enterprise_readonly` 继续作为真实经营分析只读数据源的默认 key。

这意味着：

- 代码层、文档层、配置层都围绕统一 key 工作；
- 后续替换连接串、启用真实库或 repository override 时，不需要改 AnalyticsService 主链路。

---

## 3. 三张核心表的职责拆分

### 3.1 analytics_metrics_daily

经营分析日粒度事实表。

职责：

- 承接发电量、收入、成本、利润、产量等日粒度指标；
- 为趋势分析、区域汇总、站点排名、同比/环比提供统一事实数据；
- 为部门范围过滤和治理校验提供基础字段。

### 3.2 analytics_metric_definitions

指标维表。

职责：

- 沉淀指标编码、展示名称、聚合方式、敏感级别、业务域；
- 与当前 `MetricCatalog` 结构方向对齐；
- 未来逐步替换部分代码内置指标定义。

### 3.3 analytics_org_dimensions

组织维表。

职责：

- 统一组织、区域、电站、部门映射关系；
- 支持部门范围过滤、组织口径治理和下钻分析；
- 为后续多部门、多组织树治理预留基础维度表。

---

## 4. 与当前代码定义的映射关系

### 4.1 SchemaRegistry

当前 `SchemaRegistry` 仍保留默认事实表定义，主要原因是：

- 本地 demo/fallback 仍要跑通；
- SQL Builder、SQL Guard、SQL Gateway 仍需要稳定默认 schema；
- 但其字段定义已经与 `analytics_metrics_daily` 对齐：
  - `biz_date`
  - `metric_code`
  - `metric_name`
  - `metric_value`
  - `region_code`
  - `region_name`
  - `station_code`
  - `station_name`
  - `department_code`
  - `department_name`
  - `business_domain`
  - `data_version`

### 4.2 MetricCatalog

当前 `MetricCatalog` 仍保留默认指标目录，但其结构方向已向 `analytics_metric_definitions` 对齐，至少包括：

- `metric_code`
- `metric_name`
- `display_name`
- `unit`
- `aggregation_type`
- `business_domain`
- `sensitivity_level`

### 4.3 DataSourceRegistry

当前 `DataSourceRegistry` 负责：

- 默认内置数据源
- `enterprise_readonly`
- repository override

这意味着数据源定义已经不再停留于“代码里只写死一个 local_analytics”。

---

## 5. 分区与索引策略摘要

### 5.1 按月分区

`analytics_metrics_daily` 一期按月分区，适合：

- 月度趋势
- 周报/月报
- 近一月 / 近几月查询
- 冷热数据分层与归档

### 5.2 重点索引

一期重点索引包括：

- `(biz_date, metric_code)`
- `(biz_date, metric_code, region_code)`
- `(biz_date, metric_code, station_code)`
- `(biz_date, department_code)`
- `(metric_code, department_code, biz_date)`

这些索引分别服务于：

- 趋势分析
- 区域汇总
- 站点排名
- 部门过滤
- 指标治理与审计

---

## 6. 当前实现边界

当前阶段已经完成：

- 数据源注册中心
- 数据源 repository
- PostgreSQL 可实施级 SQL 脚本
- SchemaRegistry / MetricCatalog 对齐

当前阶段尚未完成：

- Alembic 正式迁移落库
- 企业真实只读 PostgreSQL 全量数据接入
- 多数据源统一管理 API
- 完整 DBA 级容量规划与归档自动化

因此本轮结论是：

> 经营分析真实数据源的“一期数据库设计”已经定型，但正式落库与性能优化属于下一轮工作。
