"""经营分析审核任务 Repository。"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from core.database.models import AnalyticsReviewTask

_ANALYTICS_REVIEW_TASKS: dict[str, dict] = {}


def _utcnow() -> datetime:
    """返回当前 UTC 时间。"""

    return datetime.now(timezone.utc)


def _generate_review_id() -> str:
    """生成带业务前缀的审核任务 ID。"""

    return f"rev_{uuid4().hex[:12]}"


def reset_in_memory_analytics_review_store() -> None:
    """重置审核任务内存存储。"""

    _ANALYTICS_REVIEW_TASKS.clear()


class AnalyticsReviewRepository:
    """经营分析审核任务数据访问层。"""

    def __init__(self, session: Session | None = None) -> None:
        self.session = session

    def _use_database(self) -> bool:
        """判断当前是否使用数据库模式。"""

        return self.session is not None

    def _serialize_review_task(self, review_task: AnalyticsReviewTask) -> dict:
        """把 ORM 审核任务对象转换成统一字典结构。"""

        return {
            "review_id": review_task.review_id,
            "subject_type": review_task.subject_type,
            "subject_id": review_task.subject_id,
            "run_id": review_task.run_id,
            "requester_user_id": review_task.requester_user_id,
            "review_status": review_task.review_status,
            "review_level": review_task.review_level,
            "review_reason": review_task.review_reason,
            "reviewer_id": review_task.reviewer_id,
            "reviewer_name": review_task.reviewer_name,
            "review_comment": review_task.review_comment,
            "metadata": review_task.metadata_json or {},
            "created_at": review_task.created_at,
            "updated_at": review_task.updated_at,
            "reviewed_at": review_task.reviewed_at,
        }

    def create_review_task(
        self,
        *,
        subject_type: str,
        subject_id: str,
        run_id: str,
        requester_user_id: int | None,
        review_status: str,
        review_level: str,
        review_reason: str,
        metadata: dict | None = None,
    ) -> dict:
        """创建审核任务记录。"""

        if self._use_database():
            review_task = AnalyticsReviewTask(
                review_id=_generate_review_id(),
                subject_type=subject_type,
                subject_id=subject_id,
                run_id=run_id,
                requester_user_id=requester_user_id,
                review_status=review_status,
                review_level=review_level,
                review_reason=review_reason,
                reviewer_id=None,
                reviewer_name=None,
                review_comment=None,
                metadata_json=metadata or {},
                reviewed_at=None,
            )
            self.session.add(review_task)
            self.session.flush()
            self.session.refresh(review_task)
            return self._serialize_review_task(review_task)

        now = _utcnow()
        review_id = _generate_review_id()
        record = {
            "review_id": review_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "run_id": run_id,
            "requester_user_id": requester_user_id,
            "review_status": review_status,
            "review_level": review_level,
            "review_reason": review_reason,
            "reviewer_id": None,
            "reviewer_name": None,
            "review_comment": None,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
            "reviewed_at": None,
        }
        _ANALYTICS_REVIEW_TASKS[review_id] = record
        return record

    def update_review_task(self, review_id: str, **updates) -> dict | None:
        """更新审核任务状态与审核结论。"""

        if self._use_database():
            statement = select(AnalyticsReviewTask).where(AnalyticsReviewTask.review_id == review_id)
            review_task = self.session.execute(statement).scalar_one_or_none()
            if review_task is None:
                return None
            for key, value in updates.items():
                if key == "metadata":
                    review_task.metadata_json = value
                    continue
                if hasattr(review_task, key):
                    setattr(review_task, key, value)
            self.session.flush()
            self.session.refresh(review_task)
            return self._serialize_review_task(review_task)

        record = _ANALYTICS_REVIEW_TASKS.get(review_id)
        if record is None:
            return None
        record.update(updates)
        record["updated_at"] = _utcnow()
        return record

    def get_review_task(self, review_id: str) -> dict | None:
        """读取单个审核任务。"""

        if self._use_database():
            statement = select(AnalyticsReviewTask).where(AnalyticsReviewTask.review_id == review_id)
            review_task = self.session.execute(statement).scalar_one_or_none()
            if review_task is None:
                return None
            return self._serialize_review_task(review_task)

        return _ANALYTICS_REVIEW_TASKS.get(review_id)

    def get_by_subject(self, *, subject_type: str, subject_id: str) -> dict | None:
        """按主题对象读取最近一次审核任务。"""

        if self._use_database():
            statement = (
                select(AnalyticsReviewTask)
                .where(
                    AnalyticsReviewTask.subject_type == subject_type,
                    AnalyticsReviewTask.subject_id == subject_id,
                )
                .order_by(desc(AnalyticsReviewTask.created_at))
            )
            review_task = self.session.execute(statement).scalars().first()
            return self._serialize_review_task(review_task) if review_task else None

        candidates = [
            item
            for item in _ANALYTICS_REVIEW_TASKS.values()
            if item["subject_type"] == subject_type and item["subject_id"] == subject_id
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: item["created_at"], reverse=True)[0]
