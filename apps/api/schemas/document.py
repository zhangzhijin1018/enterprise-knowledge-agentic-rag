"""文档上传与文档元数据接口 Schema。

当前阶段还不实现 OCR、Chunk、Embedding 和 Milvus，
但要先把“文档入口”和“元数据返回结构”稳定下来。
这样后续前端、异步任务和 RAG 链路都可以围绕同一套字段演进。
"""

from pydantic import BaseModel, Field


class DocumentUploadResponseData(BaseModel):
    """文档上传成功后的最小返回数据。"""

    # 对外稳定文档标识，后续 OCR、Chunk、Embedding、检索日志都会依赖该 ID 串联。
    document_id: str = Field(description="文档 ID")

    # 文档标题。当前阶段默认由文件名去掉扩展名后生成。
    title: str = Field(description="文档标题")

    # 解析状态。当前阶段固定初始化为 pending，表示后续解析链路尚未执行。
    parse_status: str = Field(description="解析状态")

    # 索引状态。当前阶段固定初始化为 pending，表示后续向量索引链路尚未执行。
    index_status: str = Field(description="索引状态")


class DocumentDetailResponseData(BaseModel):
    """单个文档详情返回模型。"""

    # 对外稳定文档标识。
    document_id: str = Field(description="文档 ID")

    # 所属知识库 ID，使用对外稳定的 kb_xxx 风格标识。
    knowledge_base_id: str = Field(description="所属知识库 ID")

    # 文档标题。
    title: str = Field(description="文档标题")

    # 原始文件名。
    filename: str = Field(description="原始文件名")

    # 文件类型，例如 pdf、docx、txt。
    file_type: str = Field(description="文件类型")

    # 文件大小，单位字节。
    file_size: int | None = Field(default=None, description="文件大小（字节）")

    # 当前本地开发存储路径占位。后续可替换为对象存储 URI。
    storage_uri: str = Field(description="存储路径或 URI")

    # 文档所属业务域，例如 policy、safety、project。
    business_domain: str = Field(description="业务域")

    # 所属部门 ID。当前阶段仅保留元数据字段，不做真实部门关联校验。
    department_id: int | None = Field(default=None, description="所属部门 ID")

    # 安全级别，例如 public、internal、confidential。
    security_level: str | None = Field(default=None, description="安全级别")

    # 解析状态。
    parse_status: str = Field(description="解析状态")

    # 索引状态。
    index_status: str = Field(description="索引状态")

    # 当前文档已生成的切片数量。后续前端可据此展示“是否已完成解析与切片”。
    chunk_count: int = Field(description="切片数量")

    # 上传人用户 ID。
    uploaded_by: int | None = Field(default=None, description="上传人 ID")

    # 扩展元数据。
    metadata: dict = Field(default_factory=dict, description="扩展元数据")

    # 创建时间。
    created_at: str = Field(description="创建时间")

    # 更新时间。
    updated_at: str = Field(description="更新时间")


class DocumentListItem(BaseModel):
    """文档列表项。"""

    # 对外稳定文档标识。
    document_id: str = Field(description="文档 ID")

    # 所属知识库 ID。
    knowledge_base_id: str = Field(description="所属知识库 ID")

    # 文档标题。
    title: str = Field(description="文档标题")

    # 原始文件名。
    filename: str = Field(description="原始文件名")

    # 文档所属业务域。
    business_domain: str = Field(description="业务域")

    # 解析状态。
    parse_status: str = Field(description="解析状态")

    # 索引状态。
    index_status: str = Field(description="索引状态")

    # 创建时间。
    created_at: str = Field(description="创建时间")


class DocumentListResponseData(BaseModel):
    """文档列表响应数据。"""

    # 当前页文档列表。
    items: list[DocumentListItem] = Field(default_factory=list, description="文档列表")

    # 满足条件的总记录数。
    total: int = Field(description="总记录数")


class DocumentParseResponseData(BaseModel):
    """手动触发文档解析后的返回数据。"""

    # 对外稳定文档标识。
    document_id: str = Field(description="文档 ID")

    # 当前解析状态。
    parse_status: str = Field(description="解析状态")

    # 本次解析后总切片数。
    chunk_count: int = Field(description="切片总数")

    # 父块数量，用于观察结构级块的生成结果。
    parent_chunk_count: int = Field(description="父块数量")

    # 子块数量，用于观察检索级块的生成结果。
    child_chunk_count: int = Field(description="子块数量")
