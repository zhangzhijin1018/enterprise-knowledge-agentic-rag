"""SQLAlchemy 基础声明。

当前阶段虽然还不强依赖真实 PostgreSQL 启动，
但模型层必须先定好 ORM 基类和公共字段风格，
否则后续模型一多就容易出现命名、时间字段、注释风格不统一的问题。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, JSON, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """项目 ORM 基类。

    统一命名约定的作用：
    - 便于 Alembic 迁移输出稳定的约束名；
    - 便于数据库排障与索引排查；
    - 避免不同模型作者各写一套约束命名风格。
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def build_bigint_type():
    """构造跨数据库兼容的整型主键类型。

    设计原因：
    - 生产环境目标数据库仍然是 PostgreSQL，对应 BIGINT / BIGSERIAL 风格；
    - 但本地自动化测试如果完全依赖真实 PostgreSQL，开发迭代会明显变慢；
    - 因此这里仅在 SQLite 测试场景下退化为 Integer，
      让 SQLAlchemy ORM 路径可以快速被验证；
    - 这不会改变项目生产技术栈，只是让测试环境更容易跑通。
    """

    return BigInteger().with_variant(Integer, "sqlite")


def build_json_type():
    """构造跨数据库兼容的 JSON 类型。

    设计原因：
    - 生产 PostgreSQL 仍优先使用 JSONB，便于后续做更强的 JSON 查询与索引；
    - 测试环境下使用数据库无关的 JSON，避免因为方言差异阻塞 ORM 路径验证。
    """

    return JSON().with_variant(JSONB, "postgresql")


class TimestampMixin:
    """通用时间字段混入。

    第一阶段先统一 `created_at` / `updated_at` 两个字段，
    后续绝大多数业务表都会复用这一模式。
    """

    # 创建时间，用于审计对象首次落库时刻。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="创建时间",
    )

    # 更新时间，用于记录最近一次状态或内容变更时刻。
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )
