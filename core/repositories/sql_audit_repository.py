"""SQL 审计 Repository。

当前阶段该 Repository 负责两件事：
1. 把经营分析中的 SQL 生成、安全检查、执行结果落成审计记录；
2. 延续项目一贯的“数据库优先 + 内存回退”模式，保证本地无数据库时也能联调。

注意：
- 审计 Repository 不负责生成 SQL，也不负责执行 SQL；
- 它只负责稳定保存审计事实，避免业务逻辑和审计逻辑混在一起。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from core.database.models import SQLAudit

_SQL_AUDITS: dict[str, list[dict]] = {}


def _utcnow() -> datetime:
    """返回当前 UTC 时间。"""

    return datetime.now(timezone.utc)


def reset_in_memory_sql_audit_store() -> None:
    """重置 SQL 审计内存存储。"""

    _SQL_AUDITS.clear()


class SQLAuditRepository:
    """SQL 审计数据访问层。"""

    def __init__(self, session: Session | None = None) -> None:
        self.session = session

    def _use_database(self) -> bool:
        """判断当前是否使用数据库模式。"""

        return self.session is not None

    def _serialize_audit(self, audit: SQLAudit) -> dict:
        """把 ORM 审计对象转换成统一字典。"""

        return {
            "run_id": audit.run_id,
            "user_id": audit.user_id,
            "db_type": audit.db_type,
            "metric_scope": audit.metric_scope,
            "generated_sql": audit.generated_sql,
            "checked_sql": audit.checked_sql,
            "is_safe": audit.is_safe,
            "blocked_reason": audit.blocked_reason,
            "execution_status": audit.execution_status,
            "row_count": audit.row_count,
            "latency_ms": audit.latency_ms,
            "metadata": audit.metadata_json or {},
            "created_at": audit.created_at,
        }

    def create_audit(
        self,
        *,
        run_id: str,
        user_id: int | None,
        db_type: str,
        metric_scope: str | None,
        generated_sql: str,
        checked_sql: str | None,
        is_safe: bool,
        blocked_reason: str | None,
        execution_status: str,
        row_count: int | None,
        latency_ms: int | None,
        metadata: dict | None = None,
    ) -> dict:
        """创建一条 SQL 审计记录。"""

        if self._use_database():
            audit = SQLAudit(
                run_id=run_id,
                user_id=user_id,
                db_type=db_type,
                metric_scope=metric_scope,
                generated_sql=generated_sql,
                checked_sql=checked_sql,
                is_safe=is_safe,
                blocked_reason=blocked_reason,
                execution_status=execution_status,
                row_count=row_count,
                latency_ms=latency_ms,
                metadata_json=metadata or {},
            )
            self.session.add(audit)
            self.session.flush()
            self.session.refresh(audit)
            return self._serialize_audit(audit)

        record = {
            "run_id": run_id,
            "user_id": user_id,
            "db_type": db_type,
            "metric_scope": metric_scope,
            "generated_sql": generated_sql,
            "checked_sql": checked_sql,
            "is_safe": is_safe,
            "blocked_reason": blocked_reason,
            "execution_status": execution_status,
            "row_count": row_count,
            "latency_ms": latency_ms,
            "metadata": metadata or {},
            "created_at": _utcnow(),
        }
        _SQL_AUDITS.setdefault(run_id, []).append(record)
        return record

    def list_by_run_id(self, run_id: str) -> list[dict]:
        """读取某个 run 的全部 SQL 审计记录。"""

        if self._use_database():
            statement = (
                select(SQLAudit)
                .where(SQLAudit.run_id == run_id)
                .order_by(desc(SQLAudit.created_at))
            )
            rows = list(self.session.execute(statement).scalars())
            return [self._serialize_audit(item) for item in rows]

        return list(_SQL_AUDITS.get(run_id, []))

    def get_latest_by_run_id(self, run_id: str) -> dict | None:
        """获取某个 run 最新的一条 SQL 审计记录。"""

        rows = self.list_by_run_id(run_id)
        if not rows:
            return None
        return rows[0]
