"""知识库与文档相关 ORM 模型骨架。"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database.base import Base, TimestampMixin, build_bigint_type, build_json_type


class KnowledgeBase(TimestampMixin, Base):
    """知识库表。

    当前阶段暂不实现知识库管理接口，
    但文档元数据已经需要一个“所属知识库”的承载对象。
    因此这里先落一个最小骨架，为后续知识库权限、文档归属和检索范围控制做准备。
    """

    __tablename__ = "knowledge_bases"
    __table_args__ = {"comment": "知识库表：定义知识库基础信息"}

    # 数据库内部主键。
    id: Mapped[int] = mapped_column(
        build_bigint_type(),
        primary_key=True,
        autoincrement=True,
        comment="数据库内部主键",
    )

    # 对外稳定知识库标识，例如 kb_xxx。
    kb_uuid: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        nullable=False,
        comment="对外稳定知识库标识",
    )

    # 知识库名称。当前阶段若没有真实知识库管理入口，可先由占位逻辑生成。
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="知识库名称")

    # 业务域，例如 policy、safety、project。
    business_domain: Mapped[str] = mapped_column(String(64), nullable=False, comment="业务域")

    # 知识库说明。
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="知识库说明")

    # 知识库状态，例如 active、disabled。
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", comment="知识库状态")

    # 扩展元数据。
    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        build_json_type(),
        nullable=False,
        default=dict,
        comment="扩展元数据",
    )


class Document(TimestampMixin, Base):
    """文档表。

    业务作用：
    - 保存知识库中文档的元数据；
    - 作为 OCR、Chunk、Embedding、Milvus 索引等后续链路的入口对象；
    - 当前阶段只负责“上传 + 元数据落库”，不承载真实解析逻辑。
    """

    __tablename__ = "documents"
    __table_args__ = {"comment": "文档表：存储知识库中文档的元数据"}

    # 数据库内部主键。
    id: Mapped[int] = mapped_column(
        build_bigint_type(),
        primary_key=True,
        autoincrement=True,
        comment="数据库内部主键",
    )

    # 对外稳定文档标识，前后端与后续异步任务优先使用该字段。
    document_uuid: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        nullable=False,
        comment="对外稳定文档标识",
    )

    # 所属知识库内部主键。
    knowledge_base_id: Mapped[int] = mapped_column(
        build_bigint_type(),
        nullable=False,
        comment="所属知识库 ID",
    )

    # 文档标题。
    title: Mapped[str] = mapped_column(String(500), nullable=False, comment="文档标题")

    # 原始文件名。
    filename: Mapped[str] = mapped_column(String(500), nullable=False, comment="原始文件名")

    # 文件类型，例如 pdf、docx、txt。
    file_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="文件类型")

    # 文件大小，单位字节。
    file_size: Mapped[int | None] = mapped_column(build_bigint_type(), nullable=True, comment="文件大小（字节）")

    # 当前存储路径。当前阶段是本地开发目录占位，后续可替换为对象存储 URI。
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False, comment="对象存储 URI 或本地开发路径")

    # 业务域。
    business_domain: Mapped[str] = mapped_column(String(64), nullable=False, comment="文档所属业务域")

    # 所属部门 ID。当前阶段保留字段，不接真实部门模型。
    department_id: Mapped[int | None] = mapped_column(build_bigint_type(), nullable=True, comment="所属部门 ID")

    # 文档版本号。当前阶段默认 1。
    version_no: Mapped[int] = mapped_column(nullable=False, default=1, comment="文档版本号")

    # 文档生效日期。当前阶段暂不在上传接口中使用，但先保留数据结构。
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="生效日期")

    # 安全级别。
    security_level: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="安全级别")

    # 访问范围规则。后续可扩展知识库权限、部门范围和密级控制。
    access_scope: Mapped[dict] = mapped_column(
        build_json_type(),
        nullable=False,
        default=dict,
        comment="访问范围规则",
    )

    # 解析状态。当前阶段上传后默认 pending。
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", comment="解析状态")

    # 索引状态。当前阶段上传后默认 pending。
    index_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", comment="索引状态")

    # 上传人 ID。当前阶段直接记录当前用户 ID，不接真实 users 外键。
    uploaded_by: Mapped[int | None] = mapped_column(build_bigint_type(), nullable=True, comment="上传人 ID")

    # 扩展元数据。
    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        build_json_type(),
        nullable=False,
        default=dict,
        comment="扩展元数据",
    )
