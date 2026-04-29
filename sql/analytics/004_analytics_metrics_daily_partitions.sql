-- 004_analytics_metrics_daily_partitions.sql
-- 用途：
--   为 analytics_metrics_daily 创建默认分区和月分区示例。
-- 说明：
--   一期按月分区，原因如下：
--   1. 经营分析最常见查询是月度趋势、近一月、近几月、月报；
--   2. 分区裁剪可以显著降低扫描范围；
--   3. 后续归档、冷数据管理和历史分区维护更容易操作。

-- 默认分区：
-- 用于兜底写入异常日期数据，避免因缺分区导致整批任务失败。
CREATE TABLE IF NOT EXISTS analytics_metrics_daily_default
    PARTITION OF analytics_metrics_daily DEFAULT;

COMMENT ON TABLE analytics_metrics_daily_default IS '经营分析日粒度事实表默认分区：兜底接收未显式建分区的日期数据';

-- 2024年4月分区示例
CREATE TABLE IF NOT EXISTS analytics_metrics_daily_2024_04
    PARTITION OF analytics_metrics_daily
    FOR VALUES FROM ('2024-04-01') TO ('2024-05-01');

COMMENT ON TABLE analytics_metrics_daily_2024_04 IS '经营分析日粒度事实表 2024-04 月分区';

-- 2024年5月分区示例
CREATE TABLE IF NOT EXISTS analytics_metrics_daily_2024_05
    PARTITION OF analytics_metrics_daily
    FOR VALUES FROM ('2024-05-01') TO ('2024-06-01');

COMMENT ON TABLE analytics_metrics_daily_2024_05 IS '经营分析日粒度事实表 2024-05 月分区';
