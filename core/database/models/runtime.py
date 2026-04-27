"""运行态相关 ORM 模型骨架。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from core.database.base import Base, TimestampMixin, build_bigint_type, build_json_type


class TaskRun(TimestampMixin, Base):
    """任务运行表。

    业务作用：
    - 保存一次工作流执行的主状态；
    - 串联 conversation、trace、clarification、review 等运行态数据；
    - 为恢复执行、错误追踪和任务列表查询提供核心对象。
    """

    __tablename__ = "task_runs"

    # 数据库内部主键。
    id: Mapped[int] = mapped_column(
        build_bigint_type(),
        primary_key=True,
        autoincrement=True,
        comment="数据库内部主键",
    )

    # 任务运行唯一 ID，对外暴露时优先使用该字段。
    run_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, comment="任务运行唯一 ID")

    # 任务 ID。允许一个任务在重试、恢复后映射到多个 run。
    task_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="任务 ID")

    # 父任务 ID。后续可用于子任务、委托任务、A2A 风格任务恢复。
    parent_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="父任务 ID")

    # 所属会话 ID。
    conversation_id: Mapped[int | None] = mapped_column(
        build_bigint_type(),
        ForeignKey("conversations.id"),
        nullable=True,
        comment="所属会话 ID",
    )

    # 发起用户 ID。
    user_id: Mapped[int | None] = mapped_column(
        build_bigint_type(),
        nullable=True,
        comment="发起用户 ID",
    )

    # Trace 标识。
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="Trace 标识")

    # 任务类型，例如 chat、analytics、contract_review。
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="任务类型")

    # 路由结果。
    route: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="路由结果")

    # 选中的业务专家。
    selected_agent: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="选中的业务专家")

    # 选中的能力或工具。
    selected_capability: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="选中的能力或工具")

    # 风险等级。
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="low", comment="风险等级")

    # 审核状态。
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_required", comment="审核状态")

    # 任务主状态。
    status: Mapped[str] = mapped_column(String(32), nullable=False, comment="任务主状态")

    # 任务子状态。
    sub_status: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="任务子状态")

    # 输入快照，用于审计和恢复执行。
    input_snapshot: Mapped[dict] = mapped_column(
        build_json_type(),
        nullable=False,
        default=dict,
        comment="输入快照",
    )

    # 输出快照，用于结果回放和问题排查。
    output_snapshot: Mapped[dict] = mapped_column(
        build_json_type(),
        nullable=False,
        default=dict,
        comment="输出快照",
    )

    # 上下文快照，用于记录本轮工作流继承了哪些上下文。
    context_snapshot: Mapped[dict] = mapped_column(
        build_json_type(),
        nullable=False,
        default=dict,
        comment="上下文快照",
    )

    # 重试次数。
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0, comment="重试次数")

    # 错误码。
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="错误码")

    # 错误信息。
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="错误信息")

    # 开始时间。
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="开始时间")

    # 完成时间。
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="完成时间")


class SlotSnapshot(Base):
    """槽位快照表。

    业务作用：
    - 保存任务执行时的必填槽位、已收集槽位和缺失槽位；
    - 让系统能判断“是否满足最小可执行条件”；
    - 为澄清、恢复执行和多轮填槽提供持久化位置。
    """

    __tablename__ = "slot_snapshots"

    # 数据库内部主键。
    id: Mapped[int] = mapped_column(
        build_bigint_type(),
        primary_key=True,
        autoincrement=True,
        comment="数据库内部主键",
    )

    # 关联运行 ID，一次 run 只保留一个当前槽位快照。
    run_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, comment="关联任务运行 ID")

    # 任务类型。
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="任务类型")

    # 必填槽位列表。
    required_slots: Mapped[list] = mapped_column(
        build_json_type(),
        nullable=False,
        default=list,
        comment="必填槽位列表",
    )

    # 已收集槽位。
    collected_slots: Mapped[dict] = mapped_column(
        build_json_type(),
        nullable=False,
        default=dict,
        comment="已收集槽位",
    )

    # 缺失槽位。
    missing_slots: Mapped[list] = mapped_column(
        build_json_type(),
        nullable=False,
        default=list,
        comment="缺失槽位",
    )

    # 是否满足最小可执行条件。
    min_executable_satisfied: Mapped[bool] = mapped_column(nullable=False, default=False, comment="是否满足最小可执行条件")

    # 是否正在等待用户补充信息。
    awaiting_user_input: Mapped[bool] = mapped_column(nullable=False, default=False, comment="是否等待用户补充信息")

    # 恢复执行入口步骤。
    resume_step: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="恢复执行入口步骤")

    # 更新时间。
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )


class ClarificationEvent(Base):
    """澄清事件表。

    业务作用：
    - 记录系统发出的澄清问题；
    - 记录用户补充回复与已解析槽位；
    - 支撑“用户补充后恢复原任务”而不是创建全新任务。
    """

    __tablename__ = "clarification_events"

    # 数据库内部主键。
    id: Mapped[int] = mapped_column(
        build_bigint_type(),
        primary_key=True,
        autoincrement=True,
        comment="数据库内部主键",
    )

    # 对外稳定澄清事件标识。当前阶段采用 clr_xxx 风格的业务字符串。
    clarification_uuid: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        nullable=False,
        comment="对外稳定澄清事件标识",
    )

    # 关联任务运行 ID。
    run_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="关联任务运行 ID")

    # 所属会话 ID。
    conversation_id: Mapped[int | None] = mapped_column(
        build_bigint_type(),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True,
        comment="所属会话 ID",
    )

    # 系统发出的澄清问题。
    question_text: Mapped[str] = mapped_column(Text, nullable=False, comment="系统发出的澄清问题")

    # 本轮要补齐的槽位。
    target_slots: Mapped[list] = mapped_column(
        build_json_type(),
        nullable=False,
        default=list,
        comment="目标槽位列表",
    )

    # 用户回复。
    user_reply: Mapped[str | None] = mapped_column(Text, nullable=True, comment="用户回复内容")

    # 已解析出的槽位结果。
    resolved_slots: Mapped[dict] = mapped_column(
        build_json_type(),
        nullable=False,
        default=dict,
        comment="已解析槽位结果",
    )

    # 当前澄清状态，例如 pending、resolved。
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", comment="澄清状态")

    # 创建时间。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="创建时间",
    )

    # 解决时间。
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="解决时间")
