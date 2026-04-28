"""本地 SQL 执行器。

当前阶段真实业务库尚未正式接入，因此这里提供一个“可替换的本地只读执行层”：
- 对外表现为真实的 SQL 执行 Gateway；
- 内部先用 SQLite 内存库 + 预置样例数据；
- 后续切到 PostgreSQL、MCP SQL Client 或只读数据仓库时，只需要替换这里。

注意：
- Service 层不应该直接操作 `sqlite3`；
- SQL 执行细节应该被封装在单独执行器中；
- 这样才能保持 `router -> service -> planner/guard -> executor` 的清晰边界。
"""

from __future__ import annotations

import sqlite3
import time


class LocalSQLExecutor:
    """本地最小只读 SQL 执行器。"""

    def __init__(self) -> None:
        """初始化执行器并准备最小样例数据。"""

        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self._bootstrap_schema_and_data()

    def _bootstrap_schema_and_data(self) -> None:
        """创建最小经营分析样例表并写入测试数据。"""

        cursor = self.connection.cursor()
        cursor.execute(
            """
            CREATE TABLE analytics_metrics_daily (
                biz_date TEXT NOT NULL,
                metric_code TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                region_name TEXT NOT NULL,
                station_name TEXT NOT NULL,
                metric_value REAL NOT NULL
            )
            """
        )

        sample_rows = [
            ("2024-03-01", "generation", "发电量", "新疆区域", "哈密电站", 1200.0),
            ("2024-03-02", "generation", "发电量", "新疆区域", "哈密电站", 1350.0),
            ("2024-03-03", "generation", "发电量", "新疆区域", "吐鲁番电站", 980.0),
            ("2024-03-04", "generation", "发电量", "北疆区域", "阿勒泰电站", 760.0),
            ("2024-03-05", "generation", "发电量", "南疆区域", "和田电站", 680.0),
            ("2024-03-01", "revenue", "收入", "新疆区域", "哈密电站", 320.0),
            ("2024-03-02", "revenue", "收入", "新疆区域", "吐鲁番电站", 305.0),
            ("2024-03-03", "cost", "成本", "新疆区域", "哈密电站", 210.0),
            ("2024-03-04", "profit", "利润", "新疆区域", "哈密电站", 110.0),
            ("2024-04-01", "generation", "发电量", "新疆区域", "哈密电站", 1400.0),
            ("2024-04-02", "generation", "发电量", "新疆区域", "吐鲁番电站", 1110.0),
        ]
        cursor.executemany(
            """
            INSERT INTO analytics_metrics_daily (
                biz_date,
                metric_code,
                metric_name,
                region_name,
                station_name,
                metric_value
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            sample_rows,
        )
        self.connection.commit()

    def execute_readonly_query(self, sql: str) -> dict:
        """执行只读 SQL 并返回结构化结果。

        返回结构尽量贴近后续 MCP / PostgreSQL 真执行器：
        - rows：结构化行数据；
        - columns：字段列表；
        - row_count：返回行数；
        - latency_ms：耗时；
        - db_type：执行器背后的数据库类型。
        """

        started_at = time.perf_counter()
        cursor = self.connection.cursor()
        cursor.execute(sql)
        rows = [dict(item) for item in cursor.fetchall()]
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        columns = list(rows[0].keys()) if rows else [item[0] for item in cursor.description or []]

        return {
            "rows": rows,
            "columns": columns,
            "row_count": len(rows),
            "latency_ms": latency_ms,
            "db_type": "sqlite",
        }
