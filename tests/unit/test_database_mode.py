"""数据库模式选择测试。

当前测试目标不是验证真实 PostgreSQL 通信，
而是验证第二轮最关键的基础设施规则已经稳定：
1. 没有 DATABASE_URL 时，系统自动回退到内存模式；
2. 有 DATABASE_URL 时，默认优先进入数据库模式；
3. 如果显式要求内存模式，即使配置了数据库也会回退。
"""

from core.config.settings import Settings
from core.database.session import build_engine
from core.database.session import reset_database_runtime_state


def teardown_function() -> None:
    """每个测试后重置全局 engine/session 缓存。"""

    reset_database_runtime_state()


def test_settings_falls_back_to_in_memory_without_database_url() -> None:
    """没有配置 DATABASE_URL 时，应自动回退到内存模式。"""

    settings = Settings(database_url=None)

    assert settings.is_database_configured is False
    assert settings.should_use_database is False
    assert settings.repository_mode == "in_memory"
    assert build_engine(settings=settings) is None


def test_settings_prefers_database_when_database_url_is_configured() -> None:
    """配置 DATABASE_URL 后，默认应优先进入数据库模式。"""

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        database_enabled=True,
        use_in_memory_repository=False,
    )

    assert settings.is_database_configured is True
    assert settings.should_use_database is True
    assert settings.repository_mode == "database"
    assert build_engine(settings=settings) is not None


def test_settings_can_force_in_memory_even_when_database_url_exists() -> None:
    """显式要求内存模式时，即使有数据库配置也应回退。"""

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        database_enabled=True,
        use_in_memory_repository=True,
    )

    assert settings.is_database_configured is True
    assert settings.should_use_database is False
    assert settings.repository_mode == "in_memory"
    assert build_engine(settings=settings) is None
