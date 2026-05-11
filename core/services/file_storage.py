"""统一的文件存储服务。

支持多种存储后端：
- local: 本地文件系统（开发环境）
- oss: 阿里云 OSS（生产环境）
- s3: AWS S3 / 兼容 S3 的存储（MinIO、ceph 等）
- minio: MinIO 对象存储（私有化部署）

使用方式：
```python
storage = FileStorageFactory.create()
url = await storage.save(file_data, "contract.pdf")
```
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config.settings import Settings

logger = logging.getLogger(__name__)


class BaseStorage(ABC):
    """存储抽象基类。"""

    @abstractmethod
    async def save(self, file_data: bytes, filename: str, prefix: str = "files") -> str:
        """保存文件并返回访问 URL。

        Args:
            file_data: 文件二进制内容
            filename: 原始文件名
            prefix: 存储路径前缀

        Returns:
            存储后的访问 URL
        """
        pass

    @abstractmethod
    async def get_url(self, storage_path: str) -> str:
        """获取文件的访问 URL。

        Args:
            storage_path: 存储路径

        Returns:
            访问 URL
        """
        pass

    @abstractmethod
    async def delete(self, storage_path: str) -> bool:
        """删除文件。

        Args:
            storage_path: 存储路径

        Returns:
            是否删除成功
        """
        pass

    @abstractmethod
    async def exists(self, storage_path: str) -> bool:
        """检查文件是否存在。

        Args:
            storage_path: 存储路径

        Returns:
            是否存在
        """
        pass

    @abstractmethod
    async def get_file_bytes(self, storage_path: str) -> bytes:
        """获取文件的二进制内容。

        Args:
            storage_path: 存储路径

        Returns:
            文件二进制内容
        """
        pass


class LocalStorage(BaseStorage):
    """本地文件系统存储。

    适用于开发环境和小型部署。
    生产环境建议使用云存储。
    """

    def __init__(self, base_path: str):
        """初始化本地存储。

        Args:
            base_path: 本地存储根目录
        """
        self.base_path = Path(base_path).expanduser()
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def save(self, file_data: bytes, filename: str, prefix: str = "files") -> str:
        """保存文件到本地。

        Args:
            file_data: 文件二进制内容
            filename: 原始文件名
            prefix: 存储路径前缀

        Returns:
            存储路径（相对于 base_path）
        """
        # 生成唯一文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_hash = hashlib.md5(file_data).hexdigest()[:8]
        safe_filename = self._sanitize_filename(filename)
        storage_filename = f"{timestamp}_{file_hash}_{safe_filename}"

        # 构建存储路径
        storage_dir = self.base_path / prefix
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = storage_dir / storage_filename

        # 写入文件
        storage_path.write_bytes(file_data)

        logger.info(f"文件已保存到本地: {storage_path}")

        # 返回相对路径
        return str(storage_path.relative_to(self.base_path))

    async def get_url(self, storage_path: str) -> str:
        """获取本地文件的访问 URL。

        本地文件通过静态文件服务访问。

        Args:
            storage_path: 存储路径

        Returns:
            访问 URL（本地路径）
        """
        return f"/storage/{storage_path}"

    async def delete(self, storage_path: str) -> bool:
        """删除本地文件。

        Args:
            storage_path: 存储路径

        Returns:
            是否删除成功
        """
        try:
            file_path = self.base_path / storage_path
            if file_path.exists():
                file_path.unlink()
                logger.info(f"本地文件已删除: {file_path}")
                return True
            return False
        except Exception as e:
            logger.error(f"删除本地文件失败: {e}")
            return False

    async def exists(self, storage_path: str) -> bool:
        """检查本地文件是否存在。

        Args:
            storage_path: 存储路径

        Returns:
            是否存在
        """
        return (self.base_path / storage_path).exists()

    async def get_file_bytes(self, storage_path: str) -> bytes:
        """获取本地文件的二进制内容。

        Args:
            storage_path: 存储路径

        Returns:
            文件二进制内容
        """
        file_path = self.base_path / storage_path
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {storage_path}")
        return file_path.read_bytes()

    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除不安全字符。

        Args:
            filename: 原始文件名

        Returns:
            清理后的文件名
        """
        # 保留字母、数字、中文、连字符、下划线和点
        import re
        safe = re.sub(r"[^\w\-\u4e00-\u9fa5.]", "_", filename)
        # 限制长度
        if len(safe) > 100:
            name, ext = safe.rsplit(".", 1) if "." in safe else (safe, "")
            safe = name[:95] + "." + ext if ext else name[:100]
        return safe


class OSSStorage(BaseStorage):
    """阿里云 OSS 存储。

    适用于阿里云部署环境。
    """

    def __init__(self, endpoint: str, access_key_id: str, access_key_secret: str,
                 bucket: str, region: str = ""):
        """初始化 OSS 存储。

        Args:
            endpoint: OSS 端点
            access_key_id: Access Key ID
            access_key_secret: Access Key Secret
            bucket: OSS Bucket 名称
            region: 区域（可选）
        """
        self.endpoint = endpoint
        self.bucket = bucket
        self.region = region

        try:
            import oss2
            auth = oss2.Auth(access_key_id, access_key_secret)
            self.bucket_obj = oss2.Bucket(auth, endpoint, bucket)
            logger.info(f"OSS 存储初始化成功: bucket={bucket}")
        except ImportError:
            logger.warning("oss2 未安装，OSS 存储将不可用。请运行: pip install oss2")
            self.bucket_obj = None
        except Exception as e:
            logger.error(f"OSS 存储初始化失败: {e}")
            self.bucket_obj = None

    async def save(self, file_data: bytes, filename: str, prefix: str = "files") -> str:
        """保存文件到 OSS。

        Args:
            file_data: 文件二进制内容
            filename: 原始文件名
            prefix: 存储路径前缀

        Returns:
            OSS 对象路径
        """
        if not self.bucket_obj:
            raise RuntimeError("OSS 未正确初始化")

        # 构建 OSS 对象名
        timestamp = datetime.now().strftime("%Y%m/%d/%H%M%S")
        safe_filename = self._sanitize_filename(filename)
        object_name = f"{prefix}/{timestamp}_{safe_filename}"

        # 上传到 OSS
        self.bucket_obj.put_object(object_name, file_data)

        logger.info(f"文件已上传到 OSS: {object_name}")

        return object_name

    async def get_url(self, storage_path: str) -> str:
        """获取 OSS 文件的访问 URL。

        Args:
            storage_path: OSS 对象路径

        Returns:
            访问 URL
        """
        if not self.bucket_obj:
            return ""

        # 生成签名 URL（默认有效期 1 小时）
        return self.bucket_obj.sign_url("GET", storage_path, 3600)

    async def delete(self, storage_path: str) -> bool:
        """删除 OSS 文件。

        Args:
            storage_path: OSS 对象路径

        Returns:
            是否删除成功
        """
        if not self.bucket_obj:
            return False

        try:
            self.bucket_obj.delete_object(storage_path)
            logger.info(f"OSS 文件已删除: {storage_path}")
            return True
        except Exception as e:
            logger.error(f"删除 OSS 文件失败: {e}")
            return False

    async def exists(self, storage_path: str) -> bool:
        """检查 OSS 文件是否存在。

        Args:
            storage_path: OSS 对象路径

        Returns:
            是否存在
        """
        if not self.bucket_obj:
            return False

        return self.bucket_obj.object_exists(storage_path)

    async def get_file_bytes(self, storage_path: str) -> bytes:
        """获取 OSS 文件的二进制内容。

        Args:
            storage_path: OSS 对象路径

        Returns:
            文件二进制内容
        """
        if not self.bucket_obj:
            raise RuntimeError("OSS 未正确初始化")

        try:
            result = self.bucket_obj.get_object(storage_path)
            return result.read()
        except Exception as e:
            logger.error(f"获取 OSS 文件失败: {e}")
            raise FileNotFoundError(f"文件不存在: {storage_path}")

    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名。"""
        import re
        safe = re.sub(r"[^\w\-\u4e00-\u9fa5.]", "_", filename)
        if len(safe) > 100:
            name, ext = safe.rsplit(".", 1) if "." in safe else (safe, "")
            safe = name[:95] + "." + ext if ext else name[:100]
        return safe


class S3Storage(BaseStorage):
    """S3 兼容存储（AWS S3、MinIO、Ceph 等）。

    适用于 AWS 环境或私有化部署（配合 MinIO）。
    """

    def __init__(self, endpoint: str, access_key: str, secret_key: str,
                 bucket: str, region: str = "us-east-1", secure: bool = False):
        """初始化 S3 存储。

        Args:
            endpoint: S3 端点（MinIO 地址等）
            access_key: Access Key
            secret_key: Secret Key
            bucket: Bucket 名称
            region: 区域
            secure: 是否使用 HTTPS
        """
        self.endpoint = endpoint
        self.bucket = bucket
        self.region = region

        try:
            import boto3
            self.s3_client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
            )

            # 确保 bucket 存在
            try:
                self.s3_client.head_bucket(Bucket=bucket)
            except Exception:
                self.s3_client.create_bucket(Bucket=bucket)

            logger.info(f"S3 存储初始化成功: bucket={bucket}, endpoint={endpoint}")
        except ImportError:
            logger.warning("boto3 未安装，S3 存储将不可用。请运行: pip install boto3")
            self.s3_client = None
        except Exception as e:
            logger.error(f"S3 存储初始化失败: {e}")
            self.s3_client = None

    async def save(self, file_data: bytes, filename: str, prefix: str = "files") -> str:
        """保存文件到 S3。

        Args:
            file_data: 文件二进制内容
            filename: 原始文件名
            prefix: 存储路径前缀

        Returns:
            S3 对象路径
        """
        if not self.s3_client:
            raise RuntimeError("S3 未正确初始化")

        # 构建对象名
        timestamp = datetime.now().strftime("%Y%m/%d/%H%M%S")
        safe_filename = self._sanitize_filename(filename)
        object_name = f"{prefix}/{timestamp}_{safe_filename}"

        # 上传到 S3
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=object_name,
            Body=file_data,
        )

        logger.info(f"文件已上传到 S3: {object_name}")

        return object_name

    async def get_url(self, storage_path: str) -> str:
        """获取 S3 文件的访问 URL。

        Args:
            storage_path: S3 对象路径

        Returns:
            访问 URL
        """
        if not self.s3_client:
            return ""

        # 生成预签名 URL（默认有效期 1 小时）
        try:
            url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": storage_path},
                ExpiresIn=3600,
            )
            return url
        except Exception as e:
            logger.error(f"生成 S3 URL 失败: {e}")
            return f"{self.endpoint}/{self.bucket}/{storage_path}"

    async def delete(self, storage_path: str) -> bool:
        """删除 S3 文件。

        Args:
            storage_path: S3 对象路径

        Returns:
            是否删除成功
        """
        if not self.s3_client:
            return False

        try:
            self.s3_client.delete_object(Bucket=self.bucket, Key=storage_path)
            logger.info(f"S3 文件已删除: {storage_path}")
            return True
        except Exception as e:
            logger.error(f"删除 S3 文件失败: {e}")
            return False

    async def exists(self, storage_path: str) -> bool:
        """检查 S3 文件是否存在。

        Args:
            storage_path: S3 对象路径

        Returns:
            是否存在
        """
        if not self.s3_client:
            return False

        try:
            self.s3_client.head_object(Bucket=self.bucket, Key=storage_path)
            return True
        except Exception:
            return False

    async def get_file_bytes(self, storage_path: str) -> bytes:
        """获取 S3 文件的二进制内容（用于 MinIO）。

        Args:
            storage_path: S3 对象路径

        Returns:
            文件二进制内容
        """
        if not self.s3_client:
            raise RuntimeError("S3 未正确初始化")

        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket,
                Key=storage_path
            )
            return response['Body'].read()
        except Exception as e:
            logger.error(f"获取 S3 文件失败: {e}")
            raise FileNotFoundError(f"文件不存在: {storage_path}")

    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名。"""
        import re
        safe = re.sub(r"[^\w\-\u4e00-\u9fa5.]", "_", filename)
        if len(safe) > 100:
            name, ext = safe.rsplit(".", 1) if "." in safe else (safe, "")
            safe = name[:95] + "." + ext if ext else name[:100]
        return safe


class FileStorageFactory:
    """文件存储工厂类。

    根据配置自动选择存储后端。
    """

    _instance: BaseStorage | None = None

    @classmethod
    def create(cls, settings: Settings | None = None) -> BaseStorage:
        """创建文件存储实例。

        Args:
            settings: 配置对象，如果为 None 则从环境变量加载

        Returns:
            存储实例
        """
        if cls._instance:
            return cls._instance

        if settings is None:
            settings = Settings()

        storage_type = getattr(settings, "storage_type", "local")

        if storage_type == "local":
            cls._instance = LocalStorage(settings.storage_local_path)
        elif storage_type == "oss":
            cls._instance = OSSStorage(
                endpoint=settings.oss_endpoint,
                access_key_id=settings.oss_access_key_id,
                access_key_secret=settings.oss_access_key_secret,
                bucket=settings.oss_bucket,
                region=settings.oss_region,
            )
        elif storage_type in ("s3", "minio"):
            cls._instance = S3Storage(
                endpoint=settings.s3_endpoint,
                access_key=settings.s3_access_key,
                secret_key=settings.s3_secret_key,
                bucket=settings.s3_bucket,
                region=settings.s3_region,
                secure=settings.s3_secure,
            )
        else:
            logger.warning(f"未知的存储类型: {storage_type}，使用本地存储")
            cls._instance = LocalStorage("storage/uploads")

        return cls._instance

    @classmethod
    def reset(cls):
        """重置存储实例（用于测试）。"""
        cls._instance = None


# 便捷函数
def get_storage() -> BaseStorage:
    """获取默认存储实例。"""
    return FileStorageFactory.create()


async def save_file(file_data: bytes, filename: str, prefix: str = "files") -> str:
    """保存文件的便捷函数。

    Args:
        file_data: 文件二进制内容
        filename: 原始文件名
        prefix: 存储路径前缀

    Returns:
        存储后的访问 URL
    """
    storage = get_storage()
    return await storage.save(file_data, filename, prefix)


async def get_file_url(storage_path: str) -> str:
    """获取文件访问 URL 的便捷函数。

    Args:
        storage_path: 存储路径

    Returns:
        访问 URL
    """
    storage = get_storage()
    return await storage.get_url(storage_path)
