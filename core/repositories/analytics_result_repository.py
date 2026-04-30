"""经营分析重结果 Repository。

为什么需要单独的结果仓储：
1. output_snapshot 轻量化后，tables / insight_cards / report_blocks / chart_spec
   等重内容不再写入 task_run.output_snapshot；
2. 这些重内容需要单独存储，供 run detail、export 等场景按需读取；
3. 当前阶段采用"内存 + 可选数据库"模式，与项目其他 Repository 保持一致。

设计原则：
- Repository 只做数据访问，不负责内容拼装；
- 按 run_id 存取，与 task_run 一一对应；
- 支持按 output_mode 返回不同粒度的数据。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database.models import AnalyticsResultRecord

_ANALYTICS_RESULTS: dict[str, dict] = {}


def reset_in_memory_analytics_result_store() -> None:
    """重置重结果内存存储。"""

    _ANALYTICS_RESULTS.clear()


class AnalyticsResultRepository:
    """经营分析重结果数据访问层。

    这一层的定位是“重结果态”：
    1. 专门承接 tables / chart_spec / insight_cards / report_blocks 这类大 JSON；
    2. 防止 task_run.output_snapshot 因为重复存储大对象而持续膨胀；
    3. 让 run detail、export、report 渲染按需读取重结果，而不是每次先读 task_run 再做大 JSON 解析。
    """

    def __init__(self, session: Session | None = None) -> None:
        self.session = session

    def _use_database(self) -> bool:
        """判断当前是否使用数据库模式。"""

        return self.session is not None

    def _serialize_record(self, record: AnalyticsResultRecord) -> dict:
        """把 ORM 记录还原成统一 heavy_result 结构。"""

        masking_result = record.masking_result_json or {}
        metadata = record.metadata_json or {}
        return {
            "tables": record.tables_json or [],
            "insight_cards": record.insight_cards_json or [],
            "report_blocks": record.report_blocks_json or [],
            "chart_spec": record.chart_spec_json or None,
            "sql_explain": metadata.get("sql_explain"),
            "safety_check_result": metadata.get("safety_check_result"),
            "permission_check_result": masking_result.get("permission_check_result"),
            "data_scope_result": masking_result.get("data_scope_result"),
            "audit_info": metadata.get("audit_info"),
            "masked_fields": masking_result.get("masked_fields", []),
            "effective_filters": masking_result.get("effective_filters", {}),
            "timing_breakdown": metadata.get("timing_breakdown", {}),
        }

    def save_heavy_result(self, *, run_id: str, heavy_result: dict) -> None:
        """保存重内容结果。

        为什么不直接继续写 task_run.output_snapshot：
        - task_run 是权威运行态，应该偏轻量、偏索引友好；
        - heavy_result 更像“最终分析产物”，适合放在独立仓储里按需读取；
        - 这样可以显著降低 task_run 的读写压力和重复序列化成本。
        """

        if self._use_database():
            statement = select(AnalyticsResultRecord).where(AnalyticsResultRecord.run_id == run_id)
            record = self.session.execute(statement).scalar_one_or_none()
            masking_result = {
                "masked_fields": heavy_result.get("masked_fields", []),
                "effective_filters": heavy_result.get("effective_filters", {}),
                "permission_check_result": heavy_result.get("permission_check_result"),
                "data_scope_result": heavy_result.get("data_scope_result"),
            }
            metadata = {
                "sql_explain": heavy_result.get("sql_explain"),
                "safety_check_result": heavy_result.get("safety_check_result"),
                "audit_info": heavy_result.get("audit_info"),
                "timing_breakdown": heavy_result.get("timing_breakdown", {}),
            }
            if record is None:
                record = AnalyticsResultRecord(
                    run_id=run_id,
                    tables_json=heavy_result.get("tables", []),
                    insight_cards_json=heavy_result.get("insight_cards", []),
                    report_blocks_json=heavy_result.get("report_blocks", []),
                    chart_spec_json=heavy_result.get("chart_spec") or {},
                    masking_result_json=masking_result,
                    metadata_json=metadata,
                )
                self.session.add(record)
            else:
                record.tables_json = heavy_result.get("tables", [])
                record.insight_cards_json = heavy_result.get("insight_cards", [])
                record.report_blocks_json = heavy_result.get("report_blocks", [])
                record.chart_spec_json = heavy_result.get("chart_spec") or {}
                record.masking_result_json = masking_result
                record.metadata_json = metadata
            self.session.flush()
            return

        _ANALYTICS_RESULTS[run_id] = heavy_result

    def get_heavy_result(self, run_id: str) -> dict | None:
        """读取重内容结果。"""

        if self._use_database():
            statement = select(AnalyticsResultRecord).where(AnalyticsResultRecord.run_id == run_id)
            record = self.session.execute(statement).scalar_one_or_none()
            if record is None:
                return None
            return self._serialize_record(record)

        return _ANALYTICS_RESULTS.get(run_id)

    def get_tables(self, run_id: str) -> list[dict]:
        """读取结果表。"""

        heavy = _ANALYTICS_RESULTS.get(run_id)
        if heavy is None:
            return []
        return heavy.get("tables", [])

    def get_insight_cards(self, run_id: str) -> list[dict]:
        """读取洞察卡片。"""

        heavy = _ANALYTICS_RESULTS.get(run_id)
        if heavy is None:
            return []
        return heavy.get("insight_cards", [])

    def get_report_blocks(self, run_id: str) -> list[dict]:
        """读取报告块。"""

        heavy = _ANALYTICS_RESULTS.get(run_id)
        if heavy is None:
            return []
        return heavy.get("report_blocks", [])

    def get_chart_spec(self, run_id: str) -> dict | None:
        """读取图表描述。"""

        heavy = _ANALYTICS_RESULTS.get(run_id)
        if heavy is None:
            return None
        return heavy.get("chart_spec")

    def delete_heavy_result(self, run_id: str) -> None:
        """删除重内容结果。"""

        if self._use_database():
            statement = select(AnalyticsResultRecord).where(AnalyticsResultRecord.run_id == run_id)
            record = self.session.execute(statement).scalar_one_or_none()
            if record is not None:
                self.session.delete(record)
                self.session.flush()
            return

        _ANALYTICS_RESULTS.pop(run_id, None)
