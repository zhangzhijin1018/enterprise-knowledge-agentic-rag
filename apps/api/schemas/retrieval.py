"""检索验证接口 Schema。"""

from pydantic import BaseModel, Field


class RetrievalSearchRequest(BaseModel):
    """最小检索请求。"""

    query: str = Field(description="检索查询文本")
    top_k: int | None = Field(default=None, description="返回结果条数")
    knowledge_base_ids: list[str] = Field(default_factory=list, description="知识库过滤条件")
    business_domain: str | None = Field(default=None, description="业务域过滤条件")
    chunk_types: list[str] = Field(default_factory=list, description="指定检索的 chunk 类型")


class RetrievalParentChunkData(BaseModel):
    """父块回扩信息。"""

    chunk_uuid: str = Field(description="父块 UUID")
    chunk_type: str = Field(description="父块类型")
    content_preview: str = Field(description="父块内容")
    metadata: dict = Field(default_factory=dict, description="父块扩展元数据")


class RetrievalSearchItem(BaseModel):
    """检索命中项。"""

    chunk_uuid: str = Field(description="命中切片 UUID")
    document_id: str = Field(description="所属文档 ID")
    parent_chunk_uuid: str | None = Field(default=None, description="父块 UUID")
    chunk_type: str = Field(description="切片类型")
    score: float = Field(description="融合分数")
    content_preview: str = Field(description="命中切片内容")
    metadata: dict = Field(default_factory=dict, description="切片扩展元数据")
    parent_chunk: RetrievalParentChunkData | None = Field(default=None, description="父块回扩信息")


class RetrievalSearchResponseData(BaseModel):
    """检索响应数据。"""

    items: list[RetrievalSearchItem] = Field(default_factory=list, description="命中列表")
    total: int = Field(description="结果数量")
