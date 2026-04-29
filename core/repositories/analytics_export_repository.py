"""经营分析导出任务 Repository。

当前阶段该 Repository 负责：
1. 保存导出任务状态流转；
2. 延续“数据库优先 + 内存回退”模式；
3. 为后续 Celery 异步化、对象存储、Report MCP 远端服务预留稳定持久化边界。

注意：
- Repository 只做数据访问；
- 不负责导出内容拼装；
- 不负责真正生成文件。
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from core.database.models import AnalyticsExportTask

_ANALYTICS_EXPORT_TASKS: dict[str, dict] = {}


def _utcnow() -> datetime:
    """返回当前 UTC 时间。"""

    return datetime.now(timezone.utc)


def _generate_export_id() -> str:
    """生成带业务前缀的导出任务 ID。"""

    return f"exp_{uuid4().hex[:12]}"


def reset_in_memory_analytics_export_store() -> None:
    """重置导出任务内存存储。"""

    _ANALYTICS_EXPORT_TASKS.clear()


class AnalyticsExportRepository:
    """经营分析导出任务数据访问层。"""

    def __init__(self, session: Session | None = None) -> None:
        self.session = session

    def _use_database(self) -> bool:
        """判断当前是否使用数据库模式。"""

        return self.session is not None

    def _serialize_export_task(self, export_task: AnalyticsExportTask) -> dict:
        """把 ORM 导出任务对象转换成统一字典结构。"""

        return {
            "export_id": export_task.export_id,
            "run_id": export_task.run_id,
            "user_id": export_task.user_id,
            "export_type": export_task.export_type,
            "status": export_task.status,
            "review_required": export_task.review_required,
            "review_status": export_task.review_status,
            "review_level": export_task.review_level,
            "review_reason": export_task.review_reason,
            "review_id": export_task.review_id,
            "filename": export_task.filename,
            "artifact_path": export_task.artifact_path,
            "file_uri": export_task.file_uri,
            "content_preview": export_task.content_preview,
            "metadata": export_task.metadata_json or {},
            "reviewer_id": export_task.reviewer_id,
            "reviewer_name": export_task.reviewer_name,
            "created_at": export_task.created_at,
            "updated_at": export_task.updated_at,
            "reviewed_at": export_task.reviewed_at,
            "finished_at": export_task.finished_at,
        }

    def create_export_task(
        self,
        *,
        run_id: str,
        user_id: int | None,
        export_type: str,
        status: str,
        filename: str | None = None,
        artifact_path: str | None = None,
        file_uri: str | None = None,
        content_preview: str | None = None,
        review_required: bool = False,
        review_status: str = "not_required",
        review_level: str | None = None,
        review_reason: str | None = None,
        review_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """创建一条导出任务记录。"""

        if self._use_database():
            export_task = AnalyticsExportTask(
                export_id=_generate_export_id(),
                run_id=run_id,
                user_id=user_id,
                export_type=export_type,
                status=status,
                review_required=review_required,
                review_status=review_status,
                review_level=review_level,
                review_reason=review_reason,
                review_id=review_id,
                filename=filename,
                artifact_path=artifact_path,
                file_uri=file_uri,
                content_preview=content_preview,
                metadata_json=metadata or {},
                reviewer_id=None,
                reviewer_name=None,
                reviewed_at=None,
                finished_at=None,
            )
            self.session.add(export_task)
            self.session.flush()
            self.session.refresh(export_task)
            return self._serialize_export_task(export_task)

        now = _utcnow()
        export_id = _generate_export_id()
        record = {
            "export_id": export_id,
            "run_id": run_id,
            "user_id": user_id,
            "export_type": export_type,
            "status": status,
            "review_required": review_required,
            "review_status": review_status,
            "review_level": review_level,
            "review_reason": review_reason,
            "review_id": review_id,
            "filename": filename,
            "artifact_path": artifact_path,
            "file_uri": file_uri,
            "content_preview": content_preview,
            "metadata": metadata or {},
            "reviewer_id": None,
            "reviewer_name": None,
            "created_at": now,
            "updated_at": now,
            "reviewed_at": None,
            "finished_at": None,
        }
        _ANALYTICS_EXPORT_TASKS[export_id] = record
        return record

    def update_export_task(self, export_id: str, **updates) -> dict | None:
        """更新导出任务状态与产物信息。"""

        if self._use_database():
            statement = select(AnalyticsExportTask).where(AnalyticsExportTask.export_id == export_id)
            export_task = self.session.execute(statement).scalar_one_or_none()
            if export_task is None:
                return None
            for key, value in updates.items():
                if key == "metadata":
                    export_task.metadata_json = value
                    continue
                if hasattr(export_task, key):
                    setattr(export_task, key, value)
            self.session.flush()
            self.session.refresh(export_task)
            return self._serialize_export_task(export_task)

        record = _ANALYTICS_EXPORT_TASKS.get(export_id)
        if record is None:
            return None
        record.update(updates)
        record["updated_at"] = _utcnow()
        return record

    def get_export_task(self, export_id: str) -> dict | None:
        """读取单个导出任务。"""

        if self._use_database():
            statement = select(AnalyticsExportTask).where(AnalyticsExportTask.export_id == export_id)
            export_task = self.session.execute(statement).scalar_one_or_none()
            if export_task is None:
                return None
            return self._serialize_export_task(export_task)

        return _ANALYTICS_EXPORT_TASKS.get(export_id)

    def list_by_run_id(self, run_id: str) -> list[dict]:
        """列出某个分析任务关联的全部导出任务。"""

        if self._use_database():
            statement = (
                select(AnalyticsExportTask)
                .where(AnalyticsExportTask.run_id == run_id)
                .order_by(desc(AnalyticsExportTask.created_at))
            )
            rows = list(self.session.execute(statement).scalars())
            return [self._serialize_export_task(item) for item in rows]

        return sorted(
            [item for item in _ANALYTICS_EXPORT_TASKS.values() if item["run_id"] == run_id],
            key=lambda item: item["created_at"],
            reverse=True,
        )
