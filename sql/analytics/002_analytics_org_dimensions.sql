-- 002_analytics_org_dimensions.sql
-- 用途：
--   创建经营分析组织维表 analytics_org_dimensions。
-- 说明：
--   该表用于统一承接组织、区域、电站、部门之间的映射关系，
--   便于后续做部门范围过滤、组织下钻、区域排名和电站排名。

CREATE TABLE IF NOT EXISTS analytics_org_dimensions (
    id BIGSERIAL PRIMARY KEY,
    org_code VARCHAR(128) NOT NULL UNIQUE,
    org_name VARCHAR(255) NOT NULL,
    org_type VARCHAR(64) NOT NULL,
    parent_org_code VARCHAR(128),
    region_code VARCHAR(64),
    station_code VARCHAR(64),
    department_code VARCHAR(64),
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE analytics_org_dimensions IS '经营分析组织维表：统一组织、区域、电站、部门等维度映射';

COMMENT ON COLUMN analytics_org_dimensions.id IS '数据库内部主键';
COMMENT ON COLUMN analytics_org_dimensions.org_code IS '组织统一编码';
COMMENT ON COLUMN analytics_org_dimensions.org_name IS '组织统一名称';
COMMENT ON COLUMN analytics_org_dimensions.org_type IS '组织类型，例如 group、region、station、department';
COMMENT ON COLUMN analytics_org_dimensions.parent_org_code IS '父级组织编码，用于组织树和逐级下钻';
COMMENT ON COLUMN analytics_org_dimensions.region_code IS '区域编码，用于区域范围过滤和区域聚合';
COMMENT ON COLUMN analytics_org_dimensions.station_code IS '电站编码，用于电站范围过滤和电站排名';
COMMENT ON COLUMN analytics_org_dimensions.department_code IS '部门编码，用于经营分析部门范围治理和数据授权';
COMMENT ON COLUMN analytics_org_dimensions.is_enabled IS '是否启用该组织维度记录';
COMMENT ON COLUMN analytics_org_dimensions.metadata IS '扩展元数据，例如组织标签、上报系统来源、治理附加信息等';
COMMENT ON COLUMN analytics_org_dimensions.created_at IS '创建时间';
COMMENT ON COLUMN analytics_org_dimensions.updated_at IS '更新时间';
