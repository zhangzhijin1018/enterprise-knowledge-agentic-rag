"""文档上传与文档元数据应用服务。"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from core.common import error_codes
from core.common.exceptions import AppException
from core.common.response import build_response_meta
from core.config.settings import Settings
from core.repositories.document_chunk_repository import DocumentChunkRepository
from core.repositories.document_repository import DocumentRepository
from core.security.auth import UserContext


class DocumentService:
    """文档上传应用服务。

    当前阶段只做三件事：
    1. 接收上传文件；
    2. 保存到本地开发目录；
    3. 持久化最小文档元数据。

    这条链路的价值是：
    - 为后续 OCR、Chunk、Embedding、Milvus 建立稳定入口；
    - 让文档对象先拥有稳定 ID、存储路径和状态字段；
    - 保持 router 不直接接触文件系统和数据库。
    """

    def __init__(
        self,
        document_repository: DocumentRepository,
        document_chunk_repository: DocumentChunkRepository,
        settings: Settings,
    ) -> None:
        """显式注入文档仓储和配置对象。"""

        self.document_repository = document_repository
        self.document_chunk_repository = document_chunk_repository
        self.settings = settings

    async def upload_document(
        self,
        file: UploadFile,
        knowledge_base_id: str,
        business_domain: str,
        department_id: int | None,
        security_level: str | None,
        user_context: UserContext,
    ) -> dict:
        """上传文档并创建最小元数据记录。

        关键说明：
        - 当前保存到 `storage/uploads/` 是“本地开发存储占位”；
        - 后续可替换为 MinIO、OSS、S3 等对象存储，而不改变 router 契约；
        - `parse_status` 和 `index_status` 统一从 `pending` 起步，
          为后续异步解析和索引任务预留入口。
        """

        original_filename = Path(file.filename or "uploaded_file.bin").name
        document_id = self._generate_document_id()
        title = Path(original_filename).stem or document_id
        file_type = self._infer_file_type(original_filename)

        # 使用 UploadFile.read() 读取上传内容，是当前最直接、最稳定的最小实现。
        # 由于本轮不做大文件分片、对象存储和异步上传优化，因此先完整读入内存即可。
        content = await file.read()
        file_size = len(content)

        upload_dir = self._resolve_upload_dir()
        upload_dir.mkdir(parents=True, exist_ok=True)

        storage_filename = f"{document_id}_{original_filename}"
        storage_path = upload_dir / storage_filename

        # 这里使用本地文件系统写入，是开发阶段的最小占位方案。
        # 后续如果接对象存储，主要替换这一段以及 storage_uri 生成逻辑，
        # 不需要改 router / service 的输入输出契约。
        storage_path.write_bytes(content)

        try:
            document = self.document_repository.create_document(
                document_id=document_id,
                knowledge_base_id=knowledge_base_id,
                title=title,
                filename=original_filename,
                file_type=file_type,
                file_size=file_size,
                storage_uri=str(storage_path.resolve()),
                business_domain=business_domain,
                department_id=department_id,
                security_level=security_level,
                uploaded_by=user_context.user_id,
                metadata={
                    "original_filename": original_filename,
                    "async_parse_task_placeholder": True,
                },
            )
        except Exception:
            # 如果元数据落库失败，但文件已经写入本地开发目录，则主动清理占位文件，
            # 避免出现“磁盘上有文件、数据库里没记录”的脏数据。
            if storage_path.exists():
                storage_path.unlink()
            raise

        return {
            "data": {
                "document_id": document["document_id"],
                "title": document["title"],
                "parse_status": document["parse_status"],
                "index_status": document["index_status"],
            },
            "meta": build_response_meta(is_async=True),
        }

    def get_document_detail(self, document_id: str, user_context: UserContext) -> dict:
        """查询当前用户可访问的文档详情。"""

        document = self._get_accessible_document_or_raise(
            document_id=document_id,
            user_context=user_context,
        )
        return {
            "data": self._serialize_document_detail(document),
            "meta": build_response_meta(),
        }

    def list_documents(
        self,
        page: int,
        page_size: int,
        knowledge_base_id: str | None,
        business_domain: str | None,
        user_context: UserContext,
    ) -> dict:
        """分页查询当前用户已上传的文档列表。"""

        items, total = self.document_repository.list_documents(
            page=page,
            page_size=page_size,
            knowledge_base_id=knowledge_base_id,
            business_domain=business_domain,
            uploaded_by=user_context.user_id,
        )

        serialized_items = [
            {
                "document_id": item["document_id"],
                "knowledge_base_id": item["knowledge_base_id"],
                "title": item["title"],
                "filename": item["filename"],
                "business_domain": item["business_domain"],
                "parse_status": item["parse_status"],
                "index_status": item["index_status"],
                "created_at": item["created_at"].isoformat(),
            }
            for item in items
        ]

        return {
            "data": {
                "items": serialized_items,
                "total": total,
            },
            "meta": build_response_meta(
                page=page,
                page_size=page_size,
                total=total,
            ),
        }

    def _get_accessible_document_or_raise(
        self,
        document_id: str,
        user_context: UserContext,
    ) -> dict:
        """读取当前用户可访问的文档记录。

        当前阶段先沿用最稳妥的默认规则：
        - 普通用户只能访问自己上传的文档；
        - 后续如果要支持管理员、审计员、知识库管理员跨用户查看，
          可在这里增加角色与权限判断。
        """

        document = self.document_repository.get_by_document_id(document_id)
        if document is None:
            raise AppException(
                error_code=error_codes.DOCUMENT_NOT_FOUND,
                message="指定文档不存在",
                status_code=404,
                detail={"document_id": document_id},
            )

        if document["uploaded_by"] is not None and document["uploaded_by"] != user_context.user_id:
            raise AppException(
                error_code=error_codes.PERMISSION_DENIED,
                message="当前用户无权访问该文档",
                status_code=403,
                detail={
                    "document_id": document_id,
                    "resource_type": "document",
                    "owner_user_id": document["uploaded_by"],
                    "current_user_id": user_context.user_id,
                },
            )

        return document

    def _resolve_upload_dir(self) -> Path:
        """解析本地开发上传目录。

        规则：
        - 如果配置的是绝对路径，直接使用；
        - 如果配置的是相对路径，则相对于项目根目录（当前工作目录）解析。
        """

        upload_dir = Path(self.settings.local_upload_dir).expanduser()
        if upload_dir.is_absolute():
            return upload_dir
        return Path.cwd() / upload_dir

    def _serialize_document_detail(self, document: dict) -> dict:
        """把仓储返回的文档字典转换成接口详情结构。"""

        return {
            "document_id": document["document_id"],
            "knowledge_base_id": document["knowledge_base_id"],
            "title": document["title"],
            "filename": document["filename"],
            "file_type": document["file_type"],
            "file_size": document["file_size"],
            "storage_uri": document["storage_uri"],
            "business_domain": document["business_domain"],
            "department_id": document["department_id"],
            "security_level": document["security_level"],
            "parse_status": document["parse_status"],
            "index_status": document["index_status"],
            "chunk_count": self.document_chunk_repository.count_by_document_id(document["document_id"]),
            "uploaded_by": document["uploaded_by"],
            "metadata": document["metadata"],
            "created_at": document["created_at"].isoformat(),
            "updated_at": document["updated_at"].isoformat(),
        }

    def _generate_document_id(self) -> str:
        """生成带业务前缀的文档 ID。"""

        return f"doc_{uuid4().hex[:12]}"

    def _infer_file_type(self, filename: str) -> str:
        """根据文件名推断文件类型。

        当前采用最小规则：
        - 优先使用文件扩展名；
        - 如果没有扩展名，则回退为 `unknown`。
        """

        suffix = Path(filename).suffix.lower().lstrip(".")
        return suffix or "unknown"
