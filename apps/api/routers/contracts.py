"""合同文件上传与元数据查询路由。

合同文件上传流程：
1. 用户上传合同文件 → 获取 contract_file_id
2. 对话时传入 contract_file_id 进行审查

合同文件存储在独立的合同库中，与知识库文档分开管理。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile

from apps.api.deps import get_current_user_context
from apps.api.schemas.common import SuccessResponse
from core.common.response import build_success_response
from core.security.auth import UserContext
from core.services.contract_storage_service import ContractStorageService

router = APIRouter(prefix="/contracts", tags=["contracts"])


def get_contract_storage_service() -> ContractStorageService:
    """获取合同存储服务实例。"""
    return ContractStorageService()


@router.post("/upload", response_model=SuccessResponse)
async def upload_contract(
    request: Request,
    file: UploadFile = File(description="合同文件（支持 PDF、Word）"),
    contract_name: str = Form(description="合同名称"),
    contract_type: str = Form(description="合同类型（采购合同/销售合同/劳动合同等）"),
    contract_category: str = Form(
        default="general",
        description="合同分类（general/general/新建项目/设备采购/运维服务等）"
    ),
    department_id: str | None = Form(default=None, description="所属部门代码"),
    service: ContractStorageService = Depends(get_contract_storage_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """上传合同文件并创建元数据记录。

    流程：
    1. 保存文件到存储服务
    2. 创建元数据记录
    3. 返回 contract_file_id

    返回的 contract_file_id 可用于后续对话接口进行合同审查。
    """
    result = await service.upload_contract(
        file=file,
        contract_name=contract_name,
        contract_type=contract_type,
        contract_category=contract_category,
        department_id=department_id,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )


@router.get("/{contract_file_id}", response_model=SuccessResponse)
async def get_contract_detail(
    request: Request,
    contract_file_id: str,
    service: ContractStorageService = Depends(get_contract_storage_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """查询合同文件详情。"""
    result = await service.get_contract_detail(
        contract_file_id=contract_file_id,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )


@router.get("", response_model=SuccessResponse)
async def list_contracts(
    request: Request,
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    contract_type: str | None = Query(default=None, description="合同类型过滤"),
    contract_category: str | None = Query(default=None, description="合同分类过滤"),
    department_id: str | None = Query(default=None, description="部门过滤"),
    service: ContractStorageService = Depends(get_contract_storage_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """分页查询合同列表。"""
    result = await service.list_contracts(
        page=page,
        page_size=page_size,
        contract_type=contract_type,
        contract_category=contract_category,
        department_id=department_id,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )


@router.delete("/{contract_file_id}", response_model=SuccessResponse)
async def delete_contract(
    request: Request,
    contract_file_id: str,
    service: ContractStorageService = Depends(get_contract_storage_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """删除合同文件。"""
    result = await service.delete_contract(
        contract_file_id=contract_file_id,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )
