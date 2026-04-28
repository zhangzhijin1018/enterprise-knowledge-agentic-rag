"""文档上传、解析与元数据查询路由。

当前阶段只实现：
- 文档上传；
- 文档解析；
- 文档详情查询；
- 文档列表查询。

注意：
- router 只负责接收 multipart/form-data、查询参数和路径参数；
- 文件保存和元数据落库都交给 service；
- 不在这里直接写文件系统或数据库逻辑。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile

from apps.api.deps import (
    get_current_user_context,
    get_document_parse_service,
    get_document_service,
)
from apps.api.schemas.common import SuccessResponse
from core.common.response import build_success_response
from core.security.auth import UserContext
from core.services.document_parse_service import DocumentParseService
from core.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=SuccessResponse)
async def upload_document(
    request: Request,
    file: UploadFile = File(description="上传文件"),
    knowledge_base_id: str = Form(description="目标知识库 ID"),
    business_domain: str = Form(description="业务域"),
    department_id: int | None = Form(default=None, description="所属部门 ID"),
    security_level: str | None = Form(default=None, description="安全级别"),
    document_service: DocumentService = Depends(get_document_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """上传文档并创建最小元数据记录。"""

    result = await document_service.upload_document(
        file=file,
        knowledge_base_id=knowledge_base_id,
        business_domain=business_domain,
        department_id=department_id,
        security_level=security_level,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )


@router.get("/{document_id}", response_model=SuccessResponse)
def get_document_detail(
    request: Request,
    document_id: str,
    document_service: DocumentService = Depends(get_document_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """查询单个文档详情。"""

    result = document_service.get_document_detail(
        document_id=document_id,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )


@router.post("/{document_id}/parse", response_model=SuccessResponse)
def parse_document(
    request: Request,
    document_id: str,
    document_parse_service: DocumentParseService = Depends(get_document_parse_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """手动触发某个文档的最小解析与切片流程。"""

    result = document_parse_service.parse_document(
        document_id=document_id,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )


@router.get("", response_model=SuccessResponse)
def list_documents(
    request: Request,
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    knowledge_base_id: str | None = Query(default=None, description="知识库过滤条件"),
    business_domain: str | None = Query(default=None, description="业务域过滤条件"),
    document_service: DocumentService = Depends(get_document_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """分页查询当前用户可访问的文档列表。"""

    result = document_service.list_documents(
        page=page,
        page_size=page_size,
        knowledge_base_id=knowledge_base_id,
        business_domain=business_domain,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )
