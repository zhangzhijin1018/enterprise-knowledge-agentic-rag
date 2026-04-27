"""多轮会话相关 ORM 模型骨架。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database.base import Base, TimestampMixin, build_bigint_type, build_json_type


class Conversation(TimestampMixin, Base):
    """会话表。

    业务作用：
    - 保存多轮对话的会话级信息；
    - 承载当前状态、当前路由、最近运行任务等上下文；
    - 为后续会话列表、消息回放、任务恢复提供根对象。
    """

    __tablename__ = "conversations"

    # 数据库内部主键。
    id: Mapped[int] = mapped_column(
        build_bigint_type(),
        primary_key=True,
        autoincrement=True,
        comment="数据库内部主键",
    )

    # 对外稳定会话标识，前后端与 Trace 查询优先使用该字段。
    # 当前阶段实际采用 conv_xxx 这类业务前缀字符串，而不是原生 UUID 文本。
    # 这样做是为了与当前 API 设计文档保持一致，并且让 ID 在日志和调试中更直观。
    conversation_uuid: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        nullable=False,
        comment="对外稳定会话标识",
    )

    # 会话所属用户 ID。
    user_id: Mapped[int] = mapped_column(
        build_bigint_type(),
        nullable=False,
        comment="会话所属用户 ID",
    )

    # 会话标题，通常由首轮问题摘要生成。
    title: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="会话标题")

    # 当前主要业务路由，例如 chat、analytics、contract_review。
    current_route: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="当前主要业务路由")

    # 会话当前状态，例如 active、cancelled。
    current_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", comment="会话状态")

    # 最近一次任务运行 ID，用于快速定位当前会话最新执行上下文。
    last_run_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="最近一次任务运行 ID")

    # 会话扩展元数据。后续可放业务提示、前端展示标签等扩展信息。
    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        build_json_type(),
        nullable=False,
        default=dict,
        comment="会话扩展信息",
    )


class ConversationMessage(Base):
    """会话消息表。

    业务作用：
    - 保存 user / assistant / system 等消息明细；
    - 为多轮上下文承接、消息回放和审计提供基础数据；
    - 后续可扩展结构化消息内容与附件引用。
    """

    __tablename__ = "conversation_messages"

    # 数据库内部主键。
    id: Mapped[int] = mapped_column(
        build_bigint_type(),
        primary_key=True,
        autoincrement=True,
        comment="数据库内部主键",
    )

    # 所属会话 ID。
    conversation_id: Mapped[int] = mapped_column(
        build_bigint_type(),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属会话 ID",
    )

    # 对外稳定消息标识。当前阶段采用 msg_xxx 风格的业务字符串。
    message_uuid: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        nullable=False,
        comment="对外稳定消息标识",
    )

    # 消息角色，如 user、assistant、system。
    role: Mapped[str] = mapped_column(String(32), nullable=False, comment="消息角色")

    # 消息类型，如 text、answer、clarification。
    message_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text", comment="消息类型")

    # 消息原文。
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="消息原文")

    # 结构化消息内容，例如引用、澄清目标槽位、按钮动作等。
    structured_content: Mapped[dict] = mapped_column(
        build_json_type(),
        nullable=False,
        default=dict,
        comment="结构化消息内容",
    )

    # 关联任务运行 ID。
    related_run_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="关联任务运行 ID")

    # 创建时间，用于消息回放排序和审计。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="创建时间",
    )


class ConversationMemory(Base):
    """会话记忆表。

    业务作用：
    - 保存短期记忆快照，而不是每次都从长消息列表中推断；
    - 为指代消解、上下文继承、任务恢复提供稳定数据入口；
    - 第一阶段只做骨架，后续逐步细化 memory 字段策略。
    """

    __tablename__ = "conversation_memory"

    # 数据库内部主键。
    id: Mapped[int] = mapped_column(
        build_bigint_type(),
        primary_key=True,
        autoincrement=True,
        comment="数据库内部主键",
    )

    # 所属会话 ID，一对一关系。
    conversation_id: Mapped[int] = mapped_column(
        build_bigint_type(),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        comment="所属会话 ID",
    )

    # 最近一次业务路由。
    last_route: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="最近业务路由")

    # 最近一次使用的业务专家名称。
    last_agent: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="最近使用的业务专家")

    # 最近一次主对象，例如合同、制度、项目。
    last_primary_object: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="最近主对象")

    # 最近一次分析指标。
    last_metric: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="最近分析指标")

    # 最近一次时间范围。
    last_time_range: Mapped[dict] = mapped_column(
        build_json_type(),
        nullable=False,
        default=dict,
        comment="最近时间范围",
    )

    # 最近一次组织范围。
    last_org_scope: Mapped[dict] = mapped_column(
        build_json_type(),
        nullable=False,
        default=dict,
        comment="最近组织范围",
    )

    # 最近一次知识库范围。
    last_kb_scope: Mapped[dict] = mapped_column(
        build_json_type(),
        nullable=False,
        default=dict,
        comment="最近知识库范围",
    )

    # 最近一次报告 ID。
    last_report_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="最近报告 ID")

    # 最近一次合同 ID。
    last_contract_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="最近合同 ID")

    # 短期记忆快照。
    short_term_memory: Mapped[dict] = mapped_column(
        build_json_type(),
        nullable=False,
        default=dict,
        comment="短期会话记忆快照",
    )

    # 更新时间。每次上下文继承、补槽或任务恢复后都应刷新该字段。
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )
