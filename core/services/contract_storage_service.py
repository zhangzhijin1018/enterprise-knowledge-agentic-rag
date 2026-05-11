"""合同文件存储服务。

负责合同文件的上传、存储和元数据管理。

设计说明：
- 合同文件存储在独立目录，与知识库文档分开
- 支持多种存储后端（本地/OSS/S3）
- 元数据存储在 PostgreSQL（使用文档仓储）
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import UploadFile

from core.common import error_codes
from core.common.exceptions import AppException
from core.common.response import build_response_meta
from core.config.settings import Settings, get_settings
from core.repositories.document_repository import DocumentRepository
from core.security.auth import UserContext
from core.services.file_storage import BaseStorage, FileStorageFactory

logger = logging.getLogger(__name__)


class ContractStorageService:
    """合同文件存储服务。

    职责：
    1. 接收合同文件上传
    2. 保存到配置的存储后端
    3. 管理合同元数据

    存储路径：contracts/{contract_file_id}_{filename}
    """

    # 合同存储路径前缀
    STORAGE_PREFIX = "contracts"

    # 允许的文件类型
    ALLOWED_FILE_TYPES = {"pdf", "doc", "docx", "txt"}

    def __init__(
        self,
        storage: BaseStorage | None = None,
        document_repository: DocumentRepository | None = None,
        settings: Settings | None = None,
    ):
        """初始化合同存储服务。

        Args:
            storage: 文件存储实例，默认使用工厂创建
            document_repository: 文档仓储实例，用于存储元数据
            settings: 配置实例
        """
        self._storage = storage
        self._document_repository = document_repository
        self._settings = settings or get_settings()

    @property
    def storage(self) -> BaseStorage:
        """获取文件存储实例。"""
        if self._storage is None:
            self._storage = FileStorageFactory.create(self._settings)
        return self._storage

    async def upload_contract(
        self,
        file: UploadFile,
        contract_name: str,
        contract_type: str,
        contract_category: str,
        department_id: str | None,
        user_context: UserContext,
    ) -> dict:
        """上传合同文件。

        Args:
            file: 上传的文件
            contract_name: 合同名称
            contract_type: 合同类型
            contract_category: 合同分类
            department_id: 部门代码
            user_context: 用户上下文

        Returns:
            包含 contract_file_id 等信息的响应
        """
        # 1. 验证文件
        original_filename = Path(file.filename or "contract.bin").name
        file_type = self._infer_file_type(original_filename)

        if file_type not in self.ALLOWED_FILE_TYPES:
            raise AppException(
                error_code=error_codes.INVALID_FILE_TYPE,
                message=f"不支持的文件类型，仅支持: {', '.join(self.ALLOWED_FILE_TYPES)}",
                status_code=400,
                detail={"file_type": file_type},
            )

        # 2. 读取文件内容
        content = await file.read()
        file_size = len(content)

        # 限制文件大小（100MB）
        max_size = 100 * 1024 * 1024
        if file_size > max_size:
            raise AppException(
                error_code=error_codes.FILE_TOO_LARGE,
                message="文件大小超过限制（最大 100MB）",
                status_code=400,
                detail={"file_size": file_size, "max_size": max_size},
            )

        # 3. 生成合同文件 ID
        contract_file_id = self._generate_contract_file_id()

        # 4. 保存文件
        try:
            storage_path = await self.storage.save(
                file_data=content,
                filename=original_filename,
                prefix=self.STORAGE_PREFIX,
            )
            logger.info(f"合同文件已保存: {contract_file_id} -> {storage_path}")
        except Exception as e:
            logger.error(f"保存合同文件失败: {e}")
            raise AppException(
                error_code=error_codes.STORAGE_ERROR,
                message="文件保存失败",
                status_code=500,
            )

        # 5. 存储元数据（使用现有文档仓储）
        metadata = {
            "contract_name": contract_name,
            "contract_type": contract_type,
            "contract_category": contract_category,
            "department_id": department_id,
            "original_filename": original_filename,
            "file_size": file_size,
        }

        try:
            if self._document_repository:
                self._document_repository.create_document(
                    document_id=contract_file_id,
                    knowledge_base_id="contracts",  # 合同库固定知识库 ID
                    title=contract_name,
                    filename=original_filename,
                    file_type=file_type,
                    file_size=file_size,
                    storage_uri=storage_path,
                    business_domain="contract",
                    department_id=None,
                    security_level=None,
                    uploaded_by=user_context.user_id,
                    metadata=metadata,
                )
        except Exception as e:
            logger.error(f"存储合同元数据失败: {e}")
            # 文件已保存，元数据失败不影响主流程
            # 清理已保存的文件
            await self.storage.delete(storage_path)

        # 6. 返回结果
        return {
            "data": {
                "contract_file_id": contract_file_id,
                "contract_name": contract_name,
                "contract_type": contract_type,
                "contract_category": contract_category,
                "filename": original_filename,
                "file_size": file_size,
                "file_type": file_type,
                "storage_url": await self.storage.get_url(storage_path),
            },
            "meta": build_response_meta(),
        }

    async def get_contract_detail(
        self,
        contract_file_id: str,
        user_context: UserContext,
    ) -> dict:
        """获取合同详情。

        Args:
            contract_file_id: 合同文件 ID
            user_context: 用户上下文

        Returns:
            合同详情
        """
        if self._document_repository is None:
            raise AppException(
                error_code=error_codes.INTERNAL_ERROR,
                message="文档仓储未初始化",
                status_code=500,
            )

        document = self._document_repository.get_by_document_id(contract_file_id)
        if document is None:
            raise AppException(
                error_code=error_codes.DOCUMENT_NOT_FOUND,
                message="合同文件不存在",
                status_code=404,
                detail={"contract_file_id": contract_file_id},
            )

        # 验证权限
        if document["uploaded_by"] != user_context.user_id and user_context.user_role != "admin":
            raise AppException(
                error_code=error_codes.PERMISSION_DENIED,
                message="无权访问该合同",
                status_code=403,
            )

        metadata = document.get("metadata", {})

        return {
            "data": {
                "contract_file_id": document["document_id"],
                "contract_name": metadata.get("contract_name", document["title"]),
                "contract_type": metadata.get("contract_type"),
                "contract_category": metadata.get("contract_category"),
                "filename": document["filename"],
                "file_type": document["file_type"],
                "file_size": document["file_size"],
                "storage_url": await self.storage.get_url(document["storage_uri"]),
                "department_id": metadata.get("department_id"),
                "uploaded_by": document["uploaded_by"],
                "created_at": document["created_at"].isoformat(),
            },
            "meta": build_response_meta(),
        }

    async def list_contracts(
        self,
        page: int,
        page_size: int,
        contract_type: str | None,
        contract_category: str | None,
        department_id: str | None,
        user_context: UserContext,
    ) -> dict:
        """分页查询合同列表。

        Args:
            page: 页码
            page_size: 每页条数
            contract_type: 合同类型过滤
            contract_category: 合同分类过滤
            department_id: 部门过滤
            user_context: 用户上下文

        Returns:
            合同列表
        """
        if self._document_repository is None:
            return {
                "data": {"items": [], "total": 0},
                "meta": build_response_meta(page=page, page_size=page_size, total=0),
            }

        # 查询合同库文档
        items, total = self._document_repository.list_documents(
            page=page,
            page_size=page_size,
            knowledge_base_id="contracts",
            business_domain=None,
            uploaded_by=None,
        )

        # 过滤和转换
        filtered_items = []
        for item in items:
            metadata = item.get("metadata", {})

            # 权限过滤：只显示自己上传的或管理员可见全部
            if item["uploaded_by"] != user_context.user_id and user_context.user_role != "admin":
                continue

            # 类型过滤
            if contract_type and metadata.get("contract_type") != contract_type:
                continue
            if contract_category and metadata.get("contract_category") != contract_category:
                continue
            if department_id and metadata.get("department_id") != department_id:
                continue

            filtered_items.append({
                "contract_file_id": item["document_id"],
                "contract_name": metadata.get("contract_name", item["title"]),
                "contract_type": metadata.get("contract_type"),
                "contract_category": metadata.get("contract_category"),
                "filename": item["filename"],
                "file_type": item["file_type"],
                "file_size": item["file_size"],
                "created_at": item["created_at"].isoformat(),
            })

        return {
            "data": {
                "items": filtered_items,
                "total": total,
            },
            "meta": build_response_meta(page=page, page_size=page_size, total=total),
        }

    async def delete_contract(
        self,
        contract_file_id: str,
        user_context: UserContext,
    ) -> dict:
        """删除合同文件。

        Args:
            contract_file_id: 合同文件 ID
            user_context: 用户上下文

        Returns:
            删除结果
        """
        if self._document_repository is None:
            raise AppException(
                error_code=error_codes.INTERNAL_ERROR,
                message="文档仓储未初始化",
                status_code=500,
            )

        document = self._document_repository.get_by_document_id(contract_file_id)
        if document is None:
            raise AppException(
                error_code=error_codes.DOCUMENT_NOT_FOUND,
                message="合同文件不存在",
                status_code=404,
            )

        # 验证权限
        if document["uploaded_by"] != user_context.user_id and user_context.user_role != "admin":
            raise AppException(
                error_code=error_codes.PERMISSION_DENIED,
                message="无权删除该合同",
                status_code=403,
            )

        # 删除文件
        storage_uri = document.get("storage_uri")
        if storage_uri:
            await self.storage.delete(storage_uri)

        # 删除元数据
        self._document_repository.delete(contract_file_id)

        logger.info(f"合同文件已删除: {contract_file_id}")

        return {
            "data": {"deleted": True, "contract_file_id": contract_file_id},
            "meta": build_response_meta(),
        }

    def _generate_contract_file_id(self) -> str:
        """生成合同文件 ID。"""
        return f"contract_{uuid4().hex[:12]}"

    def _infer_file_type(self, filename: str) -> str:
        """根据文件名推断文件类型。"""
        suffix = Path(filename).suffix.lower().lstrip(".")
        type_map = {
            "pdf": "pdf",
            "doc": "doc",
            "docx": "docx",
            "txt": "txt",
            "word": "docx",
        }
        return type_map.get(suffix, suffix)
