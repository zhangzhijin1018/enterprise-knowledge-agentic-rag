-- 003_analytics_metrics_daily.sql
-- 用途：
--   创建经营分析日粒度事实表 analytics_metrics_daily。
-- 说明：
--   一期默认优先以 PostgreSQL 作为真实经营分析只读数据源的参考实现；
--   该表设计与当前 SchemaRegistry / SQL Builder / SQL Guard 的字段命名保持一致，
--   便于后续把 local_analytics demo 源平滑切换到 enterprise_readonly 真实只读源。

CREATE TABLE IF NOT EXISTS analytics_metrics_daily (
    id BIGSERIAL NOT NULL,
    biz_date DATE NOT NULL,
    metric_code VARCHAR(128) NOT NULL,
    metric_name VARCHAR(128) NOT NULL,
    metric_value NUMERIC(24, 6) NOT NULL,
    region_code VARCHAR(64),
    region_name VARCHAR(128),
    station_code VARCHAR(64),
    station_name VARCHAR(128),
    department_code VARCHAR(64) NOT NULL,
    department_name VARCHAR(128),
    business_domain VARCHAR(64) NOT NULL DEFAULT 'analytics',
    data_version VARCHAR(64) NOT NULL DEFAULT 'v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, biz_date)
) PARTITION BY RANGE (biz_date);

COMMENT ON TABLE analytics_metrics_daily IS '经营分析日粒度事实表：用于承接发电量、收入、成本、利润等指标的日粒度分析数据';

COMMENT ON COLUMN analytics_metrics_daily.id IS '数据库内部主键，配合 biz_date 作为分区表主键';
COMMENT ON COLUMN analytics_metrics_daily.biz_date IS '业务日期，经营分析趋势、同比、环比和时间过滤的核心字段';
COMMENT ON COLUMN analytics_metrics_daily.metric_code IS '指标编码，例如 generation、revenue、cost、profit';
COMMENT ON COLUMN analytics_metrics_daily.metric_name IS '指标名称，例如 发电量、收入、成本、利润';
COMMENT ON COLUMN analytics_metrics_daily.metric_value IS '指标值';
COMMENT ON COLUMN analytics_metrics_daily.region_code IS '区域编码，用于区域汇总、区域排名和区域范围过滤';
COMMENT ON COLUMN analytics_metrics_daily.region_name IS '区域名称，用于区域维度展示';
COMMENT ON COLUMN analytics_metrics_daily.station_code IS '电站编码，用于电站汇总、电站排名和电站范围过滤';
COMMENT ON COLUMN analytics_metrics_daily.station_name IS '电站名称，用于电站维度展示';
COMMENT ON COLUMN analytics_metrics_daily.department_code IS '部门编码，用于经营分析部门范围治理和数据过滤';
COMMENT ON COLUMN analytics_metrics_daily.department_name IS '部门名称，用于经营分析结果展示';
COMMENT ON COLUMN analytics_metrics_daily.business_domain IS '业务域，例如 new_energy、finance、production';
COMMENT ON COLUMN analytics_metrics_daily.data_version IS '数据版本，用于区分不同口径、不同批次导入或修订版本';
COMMENT ON COLUMN analytics_metrics_daily.created_at IS '创建时间';
COMMENT ON COLUMN analytics_metrics_daily.updated_at IS '更新时间';
