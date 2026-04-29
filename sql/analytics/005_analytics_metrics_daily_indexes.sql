-- 005_analytics_metrics_daily_indexes.sql
-- 用途：
--   为 analytics_metrics_daily 创建一期核心索引与唯一约束建议。
-- 说明：
--   以下索引重点服务于趋势查询、区域汇总、站点排名、部门过滤、指标级治理等场景。

-- 趋势分析 / 近一月 / 近几月查询：
-- 常见条件是 biz_date + metric_code，因此该索引优先服务时间趋势与单指标汇总。
CREATE INDEX IF NOT EXISTS idx_analytics_metrics_daily_biz_date_metric_code
    ON analytics_metrics_daily (biz_date, metric_code);

COMMENT ON INDEX idx_analytics_metrics_daily_biz_date_metric_code IS '服务趋势分析、月度查询、按指标时间过滤';

-- 区域汇总 / 区域排名：
-- 常见条件是 biz_date + metric_code，再按 region_code 聚合或过滤。
CREATE INDEX IF NOT EXISTS idx_analytics_metrics_daily_biz_date_metric_code_region_code
    ON analytics_metrics_daily (biz_date, metric_code, region_code);

COMMENT ON INDEX idx_analytics_metrics_daily_biz_date_metric_code_region_code IS '服务区域汇总、区域排名、区域过滤';

-- 电站汇总 / 电站排名：
-- 常见条件是 biz_date + metric_code，再按 station_code 聚合或过滤。
CREATE INDEX IF NOT EXISTS idx_analytics_metrics_daily_biz_date_metric_code_station_code
    ON analytics_metrics_daily (biz_date, metric_code, station_code);

COMMENT ON INDEX idx_analytics_metrics_daily_biz_date_metric_code_station_code IS '服务电站汇总、电站排名、电站过滤';

-- 部门范围过滤：
-- 经营分析治理里 department_code 很关键，该索引优先服务部门数据范围裁剪。
CREATE INDEX IF NOT EXISTS idx_analytics_metrics_daily_biz_date_department_code
    ON analytics_metrics_daily (biz_date, department_code);

COMMENT ON INDEX idx_analytics_metrics_daily_biz_date_department_code IS '服务部门范围过滤、按时间裁剪后的部门治理查询';

-- 指标权限 + 部门范围联合场景：
-- 常见于“某部门能否查某指标”的治理型查询和审计检查。
CREATE INDEX IF NOT EXISTS idx_analytics_metrics_daily_metric_code_department_code_biz_date
    ON analytics_metrics_daily (metric_code, department_code, biz_date);

COMMENT ON INDEX idx_analytics_metrics_daily_metric_code_department_code_biz_date IS '服务指标权限、部门范围治理与审计场景';

-- 唯一索引建议：
-- 用于避免重复导入同一业务日期、同一指标、同一区域/电站/部门、同一数据版本的数据。
-- 这里使用 COALESCE 兜底空值，减少 region/station 空值造成的唯一性缺口。
CREATE UNIQUE INDEX IF NOT EXISTS uq_analytics_metrics_daily_business_key
    ON analytics_metrics_daily (
        biz_date,
        metric_code,
        COALESCE(region_code, ''),
        COALESCE(station_code, ''),
        department_code,
        data_version
    );

COMMENT ON INDEX uq_analytics_metrics_daily_business_key IS '避免重复导入同一业务口径、同一日期、同一组织范围的数据';
