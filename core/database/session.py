"""数据库 Session 管理。

设计目标：
- 为未来真实 PostgreSQL 接入保留标准 SQLAlchemy 边界；
- 在第一阶段没有数据库时，也不阻塞 API 骨架启动；
- 让 Repository 可以逐步从“内存实现”切换到“真实 Session 实现”。
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from core.config import Settings, get_settings

_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None


def reset_database_runtime_state() -> None:
    """重置数据库运行时缓存。

    业务意义：
    - 生产服务通常只会初始化一次 engine，不需要频繁重置；
    - 但测试环境经常需要在不同数据库 URL 之间切换；
    - 如果不显式清空全局缓存，测试用例可能复用到错误的 engine/session factory。
    """

    global _ENGINE, _SESSION_FACTORY

    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None
    _SESSION_FACTORY = None


def build_engine(settings: Settings | None = None) -> Engine | None:
    """按配置决定是否创建真实数据库引擎。

    第二轮的设计目标是：
    - 没有配置数据库时，项目仍可启动；
    - 一旦提供了 DATABASE_URL，默认优先走真实数据库；
    - 只有显式要求内存模式时，才回退到 in-memory Repository。
    """

    global _ENGINE, _SESSION_FACTORY

    if _ENGINE is not None:
        return _ENGINE

    active_settings = settings or get_settings()
    if not active_settings.should_use_database:
        return None

    engine_kwargs: dict = {
        "echo": active_settings.database_echo,
        "future": True,
    }
    if active_settings.database_url.startswith("sqlite"):
        # SQLite 仅用于本地自动化验证 ORM 路径，不作为生产技术栈。
        # 对于 :memory: 数据库，必须复用同一个连接池实例，
        # 否则不同 Session 会看到不同的内存库，测试结果会不稳定。
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        engine_kwargs["poolclass"] = StaticPool
    else:
        # PostgreSQL 等真实数据库优先使用更稳妥的连接池参数。
        # 这些参数不会改变业务逻辑，但能让第二轮的“真实数据库可接入”边界更完整。
        engine_kwargs["pool_pre_ping"] = active_settings.database_pool_pre_ping
        engine_kwargs["pool_recycle"] = active_settings.database_pool_recycle

    _ENGINE = create_engine(
        active_settings.database_url,
        **engine_kwargs,
    )
    _SESSION_FACTORY = sessionmaker(
        bind=_ENGINE,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )
    return _ENGINE


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session] | None:
    """获取 Session 工厂。"""

    if _SESSION_FACTORY is not None:
        return _SESSION_FACTORY
    build_engine(settings=settings)
    return _SESSION_FACTORY


def get_db_session() -> Iterator[Session | None]:
    """提供 FastAPI 依赖风格的数据库 Session。

    当前如果数据库模式未启用，则 yield `None`。

    这样做的业务意义是：
    - API 层和 Service 层完全不用知道“现在是数据库模式还是内存模式”；
    - Repository 只需要根据是否拿到真实 Session 决定走哪条实现；
    - 这能保证第二轮尽量不改外层 API 契约。
    """

    session_factory = get_session_factory()
    if session_factory is None:
        yield None
        return

    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
