-- 001_analytics_metric_definitions.sql
-- 用途：
--   创建经营分析指标维表 analytics_metric_definitions。
-- 说明：
--   该表用于沉淀“指标业务语义 -> 物理查询口径”的基础定义，
--   与当前代码中的 MetricCatalog 方向保持一致，后续可逐步从代码默认定义迁移到数据库配置层。

CREATE TABLE IF NOT EXISTS analytics_metric_definitions (
    id BIGSERIAL PRIMARY KEY,
    metric_code VARCHAR(128) NOT NULL UNIQUE,
    metric_name VARCHAR(128) NOT NULL,
    display_name VARCHAR(128) NOT NULL,
    unit VARCHAR(64),
    aggregation_type VARCHAR(32) NOT NULL DEFAULT 'sum',
    business_domain VARCHAR(64) NOT NULL DEFAULT 'analytics',
    sensitivity_level VARCHAR(32) NOT NULL DEFAULT 'internal',
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    description TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE analytics_metric_definitions IS '经营分析指标维表：定义指标编码、展示名称、聚合方式、敏感级别和扩展元数据';

COMMENT ON COLUMN analytics_metric_definitions.id IS '数据库内部主键';
COMMENT ON COLUMN analytics_metric_definitions.metric_code IS '指标编码，例如 generation、revenue、cost、profit';
COMMENT ON COLUMN analytics_metric_definitions.metric_name IS '指标原始名称，例如 发电量、收入、成本、利润';
COMMENT ON COLUMN analytics_metric_definitions.display_name IS '前端展示名称或报表展示名称';
COMMENT ON COLUMN analytics_metric_definitions.unit IS '指标单位，例如 MWh、万元、吨';
COMMENT ON COLUMN analytics_metric_definitions.aggregation_type IS '聚合方式，例如 sum、avg、max、min';
COMMENT ON COLUMN analytics_metric_definitions.business_domain IS '业务域，例如 new_energy、finance、production';
COMMENT ON COLUMN analytics_metric_definitions.sensitivity_level IS '敏感级别，例如 internal、restricted、secret';
COMMENT ON COLUMN analytics_metric_definitions.is_enabled IS '是否启用该指标';
COMMENT ON COLUMN analytics_metric_definitions.description IS '指标业务说明，用于帮助开发、审计和后续 LLM/Planner 理解指标口径';
COMMENT ON COLUMN analytics_metric_definitions.metadata IS '扩展元数据，例如别名、默认图表类型、治理附加说明等';
COMMENT ON COLUMN analytics_metric_definitions.created_at IS '创建时间';
COMMENT ON COLUMN analytics_metric_definitions.updated_at IS '更新时间';
