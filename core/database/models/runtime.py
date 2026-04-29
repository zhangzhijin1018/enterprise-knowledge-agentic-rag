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
    __table_args__ = {"comment": "任务运行表：保存工作流运行主状态与审计主对象"}

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


class SlotSnapshot(TimestampMixin, Base):
    """槽位快照表。

    业务作用：
    - 保存任务执行时的必填槽位、已收集槽位和缺失槽位；
    - 让系统能判断“是否满足最小可执行条件”；
    - 为澄清、恢复执行和多轮填槽提供持久化位置。
    """

    __tablename__ = "slot_snapshots"
    __table_args__ = {"comment": "槽位快照表：保存任务补槽、澄清与恢复执行状态"}

    # 数据库内部主键。
    id: Mapped[int] = mapped_column(
        build_bigint_type(),
        primary_key=True,
        autoincrement=True,
        comment="数据库内部主键",
    )

    # 关联运行 ID，一次 run 只保留一个当前槽位快照。
    run_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("task_runs.run_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        comment="关联任务运行 ID",
    )

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


class ClarificationEvent(TimestampMixin, Base):
    """澄清事件表。

    业务作用：
    - 记录系统发出的澄清问题；
    - 记录用户补充回复与已解析槽位；
    - 支撑“用户补充后恢复原任务”而不是创建全新任务。
    """

    __tablename__ = "clarification_events"
    __table_args__ = {"comment": "澄清事件表：记录系统追问、用户补充和补槽结果"}

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
    run_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("task_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        comment="关联任务运行 ID",
    )

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

    # 解决时间。
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="解决时间")


class SQLAudit(Base):
    """SQL 审计表。

    业务作用：
    - 记录经营分析链路中的 SQL 生成、安全检查、执行结果；
    - 即使当前阶段还是最小规则式 SQL Builder，也必须把审计对象先立起来；
    - 后续当系统升级到 LLM 辅助 SQL 生成、更多表查询和更严格权限治理时，
      审计数据仍然可以沿用，不需要重新设计主链路。
    """

    __tablename__ = "sql_audits"
    __table_args__ = {"comment": "SQL 审计表：存储经营分析 SQL 生成、安全校验与执行审计记录"}

    # 数据库内部主键。
    id: Mapped[int] = mapped_column(
        build_bigint_type(),
        primary_key=True,
        autoincrement=True,
        comment="数据库内部主键",
    )

    # 关联任务运行 ID。
    run_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="关联任务运行 ID")

    # 发起用户 ID。当前阶段保持可空，便于兼容本地测试和历史骨架。
    user_id: Mapped[int | None] = mapped_column(
        build_bigint_type(),
        nullable=True,
        comment="发起用户 ID",
    )

    # 数据库类型，例如 postgres、sqlite、mock。
    db_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="数据库类型")

    # 指标或分析范围说明，便于快速检索审计记录。
    metric_scope: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="指标或分析范围说明")

    # SQL Builder 原始生成 SQL。
    generated_sql: Mapped[str] = mapped_column(Text, nullable=False, comment="原始生成 SQL")

    # SQL Guard 安全检查后的 SQL。当前阶段一般是补 LIMIT 或拒绝执行后的保留值。
    checked_sql: Mapped[str | None] = mapped_column(Text, nullable=True, comment="安全检查后的 SQL")

    # 是否通过安全检查。
    is_safe: Mapped[bool] = mapped_column(nullable=False, default=False, comment="是否通过安全检查")

    # 如果被拦截，这里记录拦截原因。
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="拦截原因")

    # 执行状态，例如 created、blocked、succeeded、failed。
    execution_status: Mapped[str] = mapped_column(String(32), nullable=False, comment="执行状态")

    # 返回行数，用于前端展示和审计回放。
    row_count: Mapped[int | None] = mapped_column(nullable=True, comment="返回行数")

    # 查询耗时，单位毫秒。
    latency_ms: Mapped[int | None] = mapped_column(nullable=True, comment="查询耗时（毫秒）")

    # 扩展信息。当前阶段可存槽位、group_by、compare_target 等附加上下文。
    metadata_json: Mapped[dict] = mapped_column(
        build_json_type(),
        nullable=False,
        default=dict,
        name="metadata",
        comment="扩展信息",
    )

    # 审计记录创建时间。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="创建时间",
    )


class AnalyticsExportTask(TimestampMixin, Base):
    """经营分析导出任务表。

    业务作用：
    - 保存一次经营分析导出任务的状态流转；
    - 串联 analytics run 与最终导出产物；
    - 为后续 Celery 异步任务、对象存储和 Report MCP 远端化预留稳定主对象。
    """

    __tablename__ = "analytics_export_tasks"
    __table_args__ = {"comment": "经营分析导出任务表：存储导出状态、产物路径与导出元数据"}

    # 数据库内部主键。
    id: Mapped[int] = mapped_column(
        build_bigint_type(),
        primary_key=True,
        autoincrement=True,
        comment="数据库内部主键",
    )

    # 对外稳定导出任务 ID。
    export_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, comment="导出任务唯一 ID")

    # 关联经营分析运行 ID。
    run_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("task_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        comment="关联经营分析运行 ID",
    )

    # 发起导出的用户 ID。
    user_id: Mapped[int | None] = mapped_column(
        build_bigint_type(),
        nullable=True,
        comment="发起导出的用户 ID",
    )

    # 导出类型，例如 json、markdown、docx、pdf。
    export_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="导出类型")

    # 导出模板类型。当前阶段支持 weekly_report、monthly_report 或通用模板。
    # 该字段的意义不是改变底层分析结果，而是决定“如何把既有分析结果组织成更接近交付物的结构”。
    export_template: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="导出模板类型")

    # 导出任务状态，例如 pending、running、succeeded、failed。
    status: Mapped[str] = mapped_column(String(32), nullable=False, comment="导出任务状态")

    # 是否需要人工审核。
    review_required: Mapped[bool] = mapped_column(nullable=False, default=False, comment="是否需要人工审核")

    # 审核状态，例如 not_required、pending、approved、rejected。
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_required", comment="审核状态")

    # 审核级别，例如 low、medium、high。
    review_level: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="审核级别")

    # 审核原因摘要。用于解释为什么命中 Human Review 策略。
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="审核原因摘要")

    # 关联审核任务 ID。
    review_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="关联审核任务 ID")

    # 导出文件名。
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="导出文件名")

    # 本地文件路径或未来对象存储 URI。
    artifact_path: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="导出产物路径")

    # 对前端展示友好的产物 URI。当前阶段可与 artifact_path 相同。
    file_uri: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="导出产物访问 URI")

    # 适合列表和详情页快速展示的内容预览。
    content_preview: Mapped[str | None] = mapped_column(Text, nullable=True, comment="导出内容预览")

    # 扩展元数据，例如 placeholder 标记、transport 模式、导出来源。
    metadata_json: Mapped[dict] = mapped_column(
        build_json_type(),
        nullable=False,
        default=dict,
        name="metadata",
        comment="导出扩展元数据",
    )

    # 审核人用户 ID。
    reviewer_id: Mapped[int | None] = mapped_column(
        build_bigint_type(),
        nullable=True,
        comment="审核人用户 ID",
    )

    # 审核人显示名。
    reviewer_name: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="审核人显示名")

    # 审核完成时间。
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="审核完成时间")

    # 任务完成时间。
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="任务完成时间")


class AnalyticsReviewTask(TimestampMixin, Base):
    """经营分析审核任务表。

    业务作用：
    - 保存高风险经营分析导出对应的 Human Review 主对象；
    - 让“导出任务状态”和“审核任务状态”分离建模，避免把审批过程全部塞进 export metadata；
    - 为后续审批列表、审核超时、审批事件流水和异步恢复执行预留稳定主对象。
    """

    __tablename__ = "analytics_review_tasks"
    __table_args__ = {"comment": "经营分析审核任务表：存储导出前人工审核状态与审计信息"}

    # 数据库内部主键。
    id: Mapped[int] = mapped_column(
        build_bigint_type(),
        primary_key=True,
        autoincrement=True,
        comment="数据库内部主键",
    )

    # 对外稳定审核任务 ID。
    review_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, comment="审核任务唯一 ID")

    # 审核主题类型。当前阶段固定为 analytics_export。
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="审核主题类型")

    # 审核主题对象 ID。当前阶段主要对应 export_id。
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="审核主题对象 ID")

    # 关联经营分析运行 ID。
    run_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("task_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        comment="关联经营分析运行 ID",
    )

    # 提交导出的原始请求用户 ID。
    requester_user_id: Mapped[int | None] = mapped_column(
        build_bigint_type(),
        nullable=True,
        comment="提交导出的原始请求用户 ID",
    )

    # 当前审核状态。
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", comment="审核状态")

    # 审核级别。
    review_level: Mapped[str] = mapped_column(String(32), nullable=False, comment="审核级别")

    # 审核原因。
    review_reason: Mapped[str] = mapped_column(Text, nullable=False, comment="审核原因")

    # 审核人用户 ID。
    reviewer_id: Mapped[int | None] = mapped_column(
        build_bigint_type(),
        nullable=True,
        comment="审核人用户 ID",
    )

    # 审核人显示名。
    reviewer_name: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="审核人显示名")

    # 审核意见。
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="审核意见")

    # 扩展元数据，例如策略命中细节、治理摘要、导出类型等。
    metadata_json: Mapped[dict] = mapped_column(
        build_json_type(),
        nullable=False,
        default=dict,
        name="metadata",
        comment="审核扩展元数据",
    )

    # 审核完成时间。
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="审核完成时间")


class DataSourceConfig(TimestampMixin, Base):
    """数据源注册配置表。

    业务作用：
    - 把经营分析 data source 从“纯代码硬编码”提升为“可配置注册中心”；
    - 支持启用/停用、描述、连接地址和权限要求等元数据；
    - 当前阶段即使数据库里没有记录，也可以回退到内置默认数据源，不影响本地开发和测试。
    """

    __tablename__ = "data_source_configs"
    __table_args__ = {"comment": "经营分析数据源注册配置表：支持数据源动态注册与启停"}

    # 数据库内部主键。
    id: Mapped[int] = mapped_column(
        build_bigint_type(),
        primary_key=True,
        autoincrement=True,
        comment="数据库内部主键",
    )

    # 数据源唯一标识，例如 local_analytics、enterprise_readonly。
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, comment="数据源唯一标识")

    # 数据源展示名称或简要描述。
    description: Mapped[str] = mapped_column(String(255), nullable=False, comment="数据源描述")

    # 数据源数据库类型，例如 sqlite、postgresql、mysql。
    db_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="数据源数据库类型")

    # 数据源连接地址。当前阶段允许为空，表示继续走默认内置样例源。
    connection_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True, comment="数据源连接地址")

    # 访问该数据源所需权限集合。
    required_permissions: Mapped[list] = mapped_column(
        build_json_type(),
        nullable=False,
        default=list,
        comment="访问该数据源所需权限集合",
    )

    # 允许访问该数据源的角色集合。
    allowed_roles: Mapped[list] = mapped_column(
        build_json_type(),
        nullable=False,
        default=list,
        comment="允许访问该数据源的角色集合",
    )

    # 是否启用该数据源。
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True, comment="是否启用该数据源")

    # 扩展元数据，预留表映射、路由标签、脱敏策略等配置。
    metadata_json: Mapped[dict] = mapped_column(
        build_json_type(),
        nullable=False,
        default=dict,
        name="metadata",
        comment="扩展元数据",
    )
